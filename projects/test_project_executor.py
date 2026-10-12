from django.contrib.auth import get_user_model
from django.test import TestCase
from projects.models import Project, Task, AgentRun, ProjectExecution
from projects.ai.project_executor import (
    get_ready_tasks,
    get_execution_overview,
    handle_agent_completion,
    launch_project_swarm,
    start_project_execution,
    pause_project_execution,
    resume_project_execution,
    stop_project_execution,
    refill_project_swarm,
    continue_project_execution,
    sync_project_execution_after_task_change,

)
from unittest.mock import patch
from django.db import connection

class ProjectExecutorTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="executor_test_user",
            password="test-password-123",
        )

        self.project = Project.objects.create(
            owner=self.user,
            name="Swarm Scheduler Test",
        )

    def create_task(self, title, priority=2):
        return Task.objects.create(
            project=self.project,
            title=title,
            priority=priority,
        )
    def test_stale_agent_cannot_continue_execution(self):
        from unittest.mock import patch

        from projects.ai.project_executor import (
            continue_project_execution,
        )
        from projects.models import (
            AgentRun,
            ProjectExecution,
        )

        task = self.create_task("Outdated agent task")

        execution = ProjectExecution.objects.create(
            project=self.project,
            started_by=self.user,
            status=ProjectExecution.Status.RUNNING,
            generation=2,
        )

        stale_run = AgentRun.objects.create(
            project=self.project,
            project_execution=execution,
            execution_generation=1,
            task=task,
            user=self.user,
            status=AgentRun.Status.COMPLETED,
        )

        with patch(
            "projects.ai.project_executor.refill_project_swarm"
        ) as mock_refill:
            result = continue_project_execution(
                stale_run.pk,
                dispatch=False,
            )

        self.assertEqual(result, [])
        mock_refill.assert_not_called()
    def test_complete_project_execution_lifecycle(self):
        # Create three independent tasks and one dependent task.
        tasks = [
            self.create_task(f"Build component {i}")
            for i in range(3)
        ]
        final_task = self.create_task("Integrate components")

        for task in tasks:
            final_task.dependencies.add(task)

        # Start execution: three agents should launch.
        result = start_project_execution(
            self.project,
            self.user,
            dispatch=False,
        )

        self.assertEqual(len(result["agent_run_ids"]), 3)

        execution = ProjectExecution.objects.get(
            project=self.project,
        )

        self.assertEqual(
            execution.status,
            ProjectExecution.Status.RUNNING,
        )

        # Simulate each agent finishing, followed by human approval.
        for run_id in result["agent_run_ids"]:
            run = AgentRun.objects.get(pk=run_id)

            run.status = AgentRun.Status.COMPLETED
            run.save(update_fields=["status"])

            completion = handle_agent_completion(run.pk)
            self.assertTrue(completion["handled"])

            task = run.task
            task.refresh_from_db()
            self.assertEqual(task.status, Task.Status.REVIEW)

            task.status = Task.Status.DONE
            task.completed = True
            task.save(update_fields=["status", "completed"])

        # Human approval should unlock the dependent task.
        new_runs = sync_project_execution_after_task_change(
            self.project,
            dispatch=False,
        )

        self.assertEqual(len(new_runs), 1)
        self.assertEqual(new_runs[0].task_id, final_task.pk)

        # Complete the final agent's work.
        final_run = new_runs[0]
        final_run.status = AgentRun.Status.COMPLETED
        final_run.save(update_fields=["status"])

        completion = handle_agent_completion(final_run.pk)
        self.assertTrue(completion["handled"])

        final_task.refresh_from_db()
        self.assertEqual(final_task.status, Task.Status.REVIEW)

        # Execution must wait for final human approval.
        execution.refresh_from_db()
        self.assertEqual(
            execution.status,
            ProjectExecution.Status.RUNNING,
        )

        # Approve the final task.
        final_task.status = Task.Status.DONE
        final_task.completed = True
        final_task.save(update_fields=["status", "completed"])

        sync_project_execution_after_task_change(
            self.project,
            dispatch=False,
        )

        execution.refresh_from_db()

        self.assertEqual(
            execution.status,
            ProjectExecution.Status.COMPLETED,
        )
    def test_parallel_tasks(self):
        tasks = [
            self.create_task(f"Task {i}")
            for i in range(5)
        ]

        ready = get_ready_tasks(self.project)

        self.assertEqual(len(ready), 3)
        self.assertEqual(
            [task.pk for task in ready],
            [task.pk for task in tasks[:3]],
        )

    def test_dependencies(self):
        first = self.create_task("Build backend")
        second = self.create_task("Integrate backend")

        second.dependencies.add(first)

        ready = get_ready_tasks(self.project)

        self.assertIn(first, ready)
        self.assertNotIn(second, ready)

        first.status = Task.Status.DONE
        first.save(update_fields=["status"])

        ready = get_ready_tasks(self.project)

        self.assertIn(second, ready)

    def test_priority(self):
        low = self.create_task("Low priority", 1)
        high = self.create_task("High priority", 3)
        medium = self.create_task("Medium priority", 2)

        ready = get_ready_tasks(self.project)

        self.assertEqual(
            [task.pk for task in ready],
            [high.pk, medium.pk, low.pk],
        )

    def test_active_run_excluded(self):
        task = self.create_task("Already running")

        AgentRun.objects.create(
            project=self.project,
            task=task,
            user=self.user,
            status=AgentRun.Status.RUNNING,
        )

        ready = get_ready_tasks(self.project)

        self.assertNotIn(task, ready)

    def test_project_isolation(self):
        self.create_task("My task")

        other_project = Project.objects.create(
            owner=self.user,
            name="Other Project",
        )

        other_task = Task.objects.create(
            project=other_project,
            title="Other task",
        )

        ready = get_ready_tasks(self.project)

        self.assertNotIn(other_task, ready)
        self.assertEqual(len(ready), 1)

    def test_execution_overview(self):
        first = self.create_task("Completed")
        self.create_task("Pending")

        first.status = Task.Status.DONE
        first.save(update_fields=["status"])

        overview = get_execution_overview(self.project)

        self.assertEqual(overview["total_tasks"], 2)
        self.assertEqual(overview["completed_tasks"], 1)
        self.assertEqual(overview["remaining_tasks"], 1)
        self.assertEqual(len(overview["ready_task_ids"]), 1)
    def test_swarm_creates_three_agents(self):
        ProjectExecution.objects.create(
            project=self.project,
            started_by=self.user,
            status=ProjectExecution.Status.RUNNING,
        )

        for i in range(5):
            self.create_task(f"Task {i}")

        runs = launch_project_swarm(
            self.project,
            self.user,
            dispatch=False,
        )

        self.assertEqual(len(runs), 3)
    def test_swarm_prevents_duplicates(self):
        ProjectExecution.objects.create(
            project=self.project,
            started_by=self.user,
            status=ProjectExecution.Status.RUNNING,
        )

        for i in range(5):
            self.create_task(f"Task {i}")

        first = launch_project_swarm(
            self.project,
            self.user,
            dispatch=False,
        )

        second = launch_project_swarm(
            self.project,
            self.user,
            dispatch=False,
        )

        self.assertEqual(len(first), 3)
        self.assertEqual(len(second), 0)

    def test_swarm_respects_dependencies(self):
        ProjectExecution.objects.create(
            project=self.project,
            started_by=self.user,
            status=ProjectExecution.Status.RUNNING,
        )

        first = self.create_task("Build backend")
        second = self.create_task("Connect frontend")

        second.dependencies.add(first)

        runs = launch_project_swarm(
            self.project,
            self.user,
            dispatch=False,
        )

        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].task_id, first.pk)
    def test_task_approval_unlocks_next_agent(self):
        first = self.create_task("Build backend")
        second = self.create_task("Connect frontend")
        third = self.create_task("Test integration")

        second.dependencies.add(first)
        third.dependencies.add(second)

        # Start execution. Only Task A should be ready.
        result = start_project_execution(
            self.project,
            self.user,
            dispatch=False,
        )

        self.assertEqual(len(result["agent_run_ids"]), 1)

        first_run = AgentRun.objects.get(
            pk=result["agent_run_ids"][0]
        )

        self.assertEqual(first_run.task_id, first.pk)

        # Simulate Task A's agent finishing.
        first_run.status = AgentRun.Status.COMPLETED
        first_run.save(update_fields=["status"])

        first.status = Task.Status.REVIEW
        first.save(update_fields=["status"])

        # Human approves Task A.
        first.status = Task.Status.DONE
        first.completed = True
        first.save(update_fields=["status", "completed"])

        # Synchronize the execution.
        new_runs = sync_project_execution_after_task_change(
            self.project,
            dispatch=False,
        )

        # Task B should now receive an agent.
        self.assertEqual(len(new_runs), 1)
        self.assertEqual(new_runs[0].task_id, second.pk)

        # Task C must remain blocked.
        self.assertFalse(
            AgentRun.objects.filter(
                project=self.project,
                task=third,
            ).exists()
        )

        print(
            "PASS: Task approval unlocked the next agent "
            "while preserving dependencies"
        )
    def test_swarm_rejects_unauthorized_users(self):
        from django.core.exceptions import PermissionDenied

        other_user = get_user_model().objects.create_user(
            username="unauthorized_executor",
            password="test-password-123",
        )

        self.create_task("Private task")

        with self.assertRaises(PermissionDenied):
            launch_project_swarm(
                self.project,
                other_user,
                dispatch=False,
            )
    def test_start_execution_creates_three_agents(self):
        for i in range(5):
            self.create_task(f"Task {i}")

        result = start_project_execution(
            self.project,
            self.user,
            dispatch=False,
        )

        execution = ProjectExecution.objects.get(
            project=self.project
        )

        self.assertEqual(
            execution.status,
            ProjectExecution.Status.RUNNING,
        )

        self.assertEqual(
            len(result["agent_run_ids"]),
            3,
        )

        self.assertEqual(
            AgentRun.objects.filter(
                project=self.project,
                status=AgentRun.Status.QUEUED,
            ).count(),
            3,
        )

    def test_start_execution_is_idempotent(self):
        for i in range(5):
            self.create_task(f"Task {i}")

        first = start_project_execution(
            self.project,
            self.user,
            dispatch=False,
        )

        second = start_project_execution(
            self.project,
            self.user,
            dispatch=False,
        )

        self.assertFalse(first["already_running"])
        self.assertTrue(second["already_running"])

        self.assertEqual(
            AgentRun.objects.filter(
                project=self.project,
            ).count(),
            3,
        )

    def test_unauthorized_user_cannot_start_execution(self):
        from django.core.exceptions import PermissionDenied

        other_user = get_user_model().objects.create_user(
            username="unauthorized_start_user",
            password="test-password-123",
        )

        self.create_task("Private task")

        with self.assertRaises(PermissionDenied):
            start_project_execution(
                self.project,
                other_user,
                dispatch=False,
            )

        self.assertFalse(
            ProjectExecution.objects.filter(
                project=self.project,
            ).exists()
        )
    def test_pause_prevents_refill(self):
        for i in range(5):
            self.create_task(f"Task {i}")

        start_project_execution(
            self.project,
            self.user,
            dispatch=False,
        )

        pause_project_execution(
            self.project,
            self.user,
        )

        execution = ProjectExecution.objects.get(
            project=self.project
        )

        self.assertEqual(
            execution.status,
            ProjectExecution.Status.PAUSED,
        )

        runs = refill_project_swarm(
            self.project,
            self.user,
            dispatch=False,
        )

        self.assertEqual(len(runs), 0)

    def test_resume_restores_execution(self):
        for i in range(5):
            self.create_task(f"Task {i}")

        start_project_execution(
            self.project,
            self.user,
            dispatch=False,
        )

        pause_project_execution(
            self.project,
            self.user,
        )

        result = resume_project_execution(
            self.project,
            self.user,
            dispatch=False,
        )

        self.assertTrue(result["resumed"])

        execution = ProjectExecution.objects.get(
            project=self.project
        )

        self.assertEqual(
            execution.status,
            ProjectExecution.Status.RUNNING,
        )

    def test_stop_prevents_refill(self):
        for i in range(5):
            self.create_task(f"Task {i}")

        start_project_execution(
            self.project,
            self.user,
            dispatch=False,
        )

        stop_project_execution(
            self.project,
            self.user,
        )

        execution = ProjectExecution.objects.get(
            project=self.project
        )

        self.assertEqual(
            execution.status,
            ProjectExecution.Status.STOPPED,
        )

        runs = refill_project_swarm(
            self.project,
            self.user,
            dispatch=False,
        )

        self.assertEqual(len(runs), 0)

    def test_refill_uses_available_slot(self):
        for i in range(5):
            self.create_task(f"Task {i}")

        result = start_project_execution(
            self.project,
            self.user,
            dispatch=False,
        )

        # Simulate one agent finishing its work.
        finished_run = AgentRun.objects.get(
            pk=result["agent_run_ids"][0]
        )

        finished_run.status = AgentRun.Status.COMPLETED
        finished_run.save(update_fields=["status"])

        # Its task must leave TODO before refill.
        task = finished_run.task
        task.status = Task.Status.REVIEW
        task.save(update_fields=["status"])

        new_runs = refill_project_swarm(
            self.project,
            self.user,
            dispatch=False,
        )

        self.assertEqual(len(new_runs), 1)

        self.assertEqual(
            AgentRun.objects.filter(
                project=self.project,
                status=AgentRun.Status.QUEUED,
            ).count(),
            3,
        )
    def test_completed_swarm_agent_launches_replacement(self):
        for i in range(5):
            self.create_task(f"Task {i}")

        result = start_project_execution(
            self.project,
            self.user,
            dispatch=False,
        )

        finished_run = AgentRun.objects.get(
            pk=result["agent_run_ids"][0]
        )

        finished_run.status = AgentRun.Status.COMPLETED
        finished_run.save(update_fields=["status"])

        finished_run.task.status = Task.Status.REVIEW
        finished_run.task.save(update_fields=["status"])

        new_runs = continue_project_execution(
            finished_run.pk,
            dispatch=False,
        )

        self.assertEqual(len(new_runs), 1)

        self.assertEqual(
            AgentRun.objects.filter(
                project=self.project,
                status=AgentRun.Status.QUEUED,
            ).count(),
            3,
        )

    def test_manual_agent_does_not_continue_swarm(self):
        task = self.create_task("Manual task")

        manual_run = AgentRun.objects.create(
            project=self.project,
            task=task,
            user=self.user,
            status=AgentRun.Status.COMPLETED,
        )

        new_runs = continue_project_execution(
            manual_run.pk,
            dispatch=False,
        )

        self.assertEqual(len(new_runs), 0)

    def test_paused_swarm_does_not_continue(self):
        for i in range(5):
            self.create_task(f"Task {i}")

        result = start_project_execution(
            self.project,
            self.user,
            dispatch=False,
        )

        pause_project_execution(
            self.project,
            self.user,
        )

        finished_run = AgentRun.objects.get(
            pk=result["agent_run_ids"][0]
        )

        finished_run.status = AgentRun.Status.COMPLETED
        finished_run.save(update_fields=["status"])

        finished_run.task.status = Task.Status.REVIEW
        finished_run.task.save(update_fields=["status"])

        new_runs = continue_project_execution(
            finished_run.pk,
            dispatch=False,
        )

        self.assertEqual(len(new_runs), 0)
    def test_failed_swarm_agent_launches_replacement(self):
        # Create five independent tasks.
        for i in range(5):
            self.create_task(f"Task {i}")

        # Start execution with three queued agents.
        result = start_project_execution(
            self.project,
            self.user,
            dispatch=False,
        )

        self.assertEqual(
            len(result["agent_run_ids"]),
            3,
        )

        # Simulate one agent failing.
        failed_run = AgentRun.objects.get(
            pk=result["agent_run_ids"][0]
        )

        failed_run.status = AgentRun.Status.FAILED
        failed_run.save(update_fields=["status"])

        # The scheduler should reserve another task.
        new_runs = continue_project_execution(
            failed_run.pk,
            dispatch=False,
        )

        self.assertEqual(len(new_runs), 1)

        # Three queued agents should now exist.
        self.assertEqual(
            AgentRun.objects.filter(
                project=self.project,
                status=AgentRun.Status.QUEUED,
            ).count(),
            3,
        )

        # The failed agent must remain recorded.
        failed_run.refresh_from_db()

        self.assertEqual(
            failed_run.status,
            AgentRun.Status.FAILED,
        )
    def test_failed_task_is_not_automatically_retried(self):
        failed_task = self.create_task("Broken task")
        ready_task = self.create_task("Working task")

        AgentRun.objects.create(
            project=self.project,
            task=failed_task,
            user=self.user,
            status=AgentRun.Status.FAILED,
        )

        ready = get_ready_tasks(self.project)

        self.assertNotIn(failed_task, ready)
        self.assertIn(ready_task, ready)
    def test_start_execution_http_endpoint(self):
        from django.urls import reverse
        from django.test import override_settings
        from projects.models import ProjectExecution

        # Create three independent tasks.
        for i in range(3):
            self.create_task(f"HTTP test task {i}")

        # Log in as the project owner.
        self.client.force_login(self.user)

        url = reverse(
            "start_project_execution",
            kwargs={"project_pk": self.project.pk},
        )

        # Disable real agent execution.
        with override_settings(
            PROJIVO_EXECUTE_LIVE_DISPATCH=False
        ):
            response = self.client.post(url)

        self.assertEqual(response.status_code, 200)

        data = response.json()

        self.assertTrue(data["success"])

        self.assertEqual(
            len(data["agent_run_ids"]),
            3,
        )

        execution = ProjectExecution.objects.get(
            project=self.project,
        )

        self.assertEqual(
            execution.status,
            ProjectExecution.Status.RUNNING,
        )
    def test_swarm_dispatches_agents_to_celery(self):
        from projects.ai.project_executor import (
            launch_project_swarm,
        )
        from projects.models import ProjectExecution

        # Create an active execution.
        ProjectExecution.objects.create(
            project=self.project,
            started_by=self.user,
            status=ProjectExecution.Status.RUNNING,
        )

        # Create three independent tasks.
        for i in range(3):
            Task.objects.create(
                project=self.project,
                title=f"Dispatch task {i + 1}",
            )

        with (
            patch.object(
                connection,
                "vendor",
                "postgresql",
            ),
            patch(
                "projects.tasks.execute_agent_run_task.delay",
            ) as mock_delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            runs = launch_project_swarm(
                self.project,
                self.user,
                dispatch=True,
            )

        self.assertEqual(len(runs), 3)

        self.assertEqual(
            mock_delay.call_count,
            3,
        )

        dispatched_ids = {
            call.args[0]
            for call in mock_delay.call_args_list
        }

        expected_ids = {
            run.pk
            for run in runs
        }

        self.assertEqual(
            dispatched_ids,
            expected_ids,
        )
    def test_completed_agent_dispatches_replacement_to_celery(self):
        from unittest.mock import patch
        from django.db import connection

        # Create five independent tasks.
        for i in range(5):
            self.create_task(f"Replacement task {i}")

        # Start three agents without dispatching them.
        result = start_project_execution(
            self.project,
            self.user,
            dispatch=False,
        )

        self.assertEqual(len(result["agent_run_ids"]), 3)

        # Simulate one agent completing its task.
        finished_run = AgentRun.objects.get(
            pk=result["agent_run_ids"][0]
        )

        finished_run.status = AgentRun.Status.COMPLETED
        finished_run.save(update_fields=["status"])

        finished_run.task.status = Task.Status.REVIEW
        finished_run.task.save(update_fields=["status"])

        # Enable mocked PostgreSQL and Celery dispatch.
        with (
            patch.object(connection, "vendor", "postgresql"),
            patch(
                "projects.tasks.execute_agent_run_task.delay"
            ) as mock_delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            new_runs = continue_project_execution(
                finished_run.pk,
                dispatch=True,
            )

        # Exactly one replacement should be created.
        self.assertEqual(len(new_runs), 1)

        # Exactly one replacement should be dispatched.
        mock_delay.assert_called_once_with(
            new_runs[0].pk
        )

        # Two original agents + one replacement.
        self.assertEqual(
            AgentRun.objects.filter(
                project=self.project,
                status=AgentRun.Status.QUEUED,
            ).count(),
            3,
        )
    def test_execution_control_http_endpoints(self):
        from django.urls import reverse
        from django.test import override_settings
        from projects.models import ProjectExecution

        # Create tasks for the swarm.
        for i in range(5):
            self.create_task(f"Control test task {i}")

        self.client.force_login(self.user)

        def endpoint(action):
            return reverse(
                f"{action}_project_execution",
                kwargs={"project_pk": self.project.pk},
            )

        with override_settings(
            PROJIVO_EXECUTE_LIVE_DISPATCH=False
        ):
            # Start
            response = self.client.post(endpoint("start"))
            self.assertEqual(response.status_code, 200)

            # Pause
            response = self.client.post(endpoint("pause"))
            self.assertEqual(response.status_code, 200)

            execution = ProjectExecution.objects.get(
                project=self.project,
            )
            self.assertEqual(
                execution.status,
                ProjectExecution.Status.PAUSED,
            )

            # Resume
            response = self.client.post(endpoint("resume"))
            self.assertEqual(response.status_code, 200)

            execution.refresh_from_db()
            self.assertEqual(
                execution.status,
                ProjectExecution.Status.RUNNING,
            )

            # Stop
            response = self.client.post(endpoint("stop"))
            self.assertEqual(response.status_code, 200)

            execution.refresh_from_db()
            self.assertEqual(
                execution.status,
                ProjectExecution.Status.STOPPED,
            )

            # Check status
            response = self.client.get(
                reverse(
                    "project_execution_status",
                    kwargs={"project_pk": self.project.pk},
                )
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json()["status"],
                ProjectExecution.Status.STOPPED,
            )
    def test_unauthorized_user_cannot_control_execution(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse
        from django.test import override_settings

        User = get_user_model()

        outsider = User.objects.create_user(
            username="execute_outsider",
            password="testpassword123",
        )

        self.client.force_login(outsider)

        actions = ["start", "pause", "resume", "stop"]

        with override_settings(
            PROJIVO_EXECUTE_LIVE_DISPATCH=False
        ):
            for action in actions:
                with self.subTest(action=action):
                    url = reverse(
                        f"{action}_project_execution",
                        kwargs={
                            "project_pk": self.project.pk,
                        },
                    )

                    response = self.client.post(url)

                    self.assertIn(
                        response.status_code,
                        [403, 404],
                    )

        # Outsiders must not be able to view agent activity.
        status_url = reverse(
            "project_execution_status",
            kwargs={
                "project_pk": self.project.pk,
            },
        )

        response = self.client.get(status_url)

        self.assertIn(
            response.status_code,
            [403, 404],
        )
    def test_execution_completes_when_all_tasks_done(self):
        # Create three independent tasks.
        tasks = [
            self.create_task(f"Task {i}")
            for i in range(3)
        ]

        # Start Projivo Execute.
        result = start_project_execution(
            self.project,
            self.user,
            dispatch=False,
        )

        self.assertEqual(
            len(result["agent_run_ids"]),
            3,
        )

        # Simulate all three agents finishing.
        for run_id in result["agent_run_ids"]:
            run = AgentRun.objects.get(pk=run_id)

            run.status = AgentRun.Status.COMPLETED
            run.save(update_fields=["status"])

        # Simulate all tasks being approved.
        for task in tasks:
            task.status = Task.Status.DONE
            task.save(update_fields=["status"])

        # Trigger the completion check.
        refill_project_swarm(
            self.project,
            self.user,
            dispatch=False,
        )

        execution = ProjectExecution.objects.get(
            project=self.project,
        )

        self.assertEqual(
            execution.status,
            ProjectExecution.Status.COMPLETED,
        )
    def test_execution_waits_for_task_review(self):
        task = self.create_task("Task awaiting approval")

        result = start_project_execution(
            self.project,
            self.user,
            dispatch=False,
        )

        self.assertEqual(
            len(result["agent_run_ids"]),
            1,
        )

        run = AgentRun.objects.get(
            pk=result["agent_run_ids"][0]
        )

        # Simulate successful agent execution.
        run.status = AgentRun.Status.COMPLETED
        run.save(update_fields=["status"])

        # The agent finished, but the user
        # has not approved the task.
        task.status = Task.Status.REVIEW
        task.save(update_fields=["status"])

        refill_project_swarm(
            self.project,
            self.user,
            dispatch=False,
        )

        execution = ProjectExecution.objects.get(
            project=self.project,
        )

        # REVIEW does not count as DONE.
        self.assertEqual(
            execution.status,
            ProjectExecution.Status.RUNNING,
        )

        self.assertEqual(
            AgentRun.objects.filter(
                project=self.project,
                status__in=[
                    AgentRun.Status.QUEUED,
                    AgentRun.Status.RUNNING,
                ],
            ).count(),
            0,
        )

        print(
            "PASS: Projivo waits for human approval "
            "before completing the project"
        )
        
    def test_task_approval_automatically_completes_execution(self):
        # Create a project with one task.
        task = self.create_task("Build landing page")

        # Start Projivo Execute.
        result = start_project_execution(
            self.project,
            self.user,
            dispatch=False,
        )

        run = AgentRun.objects.get(
            pk=result["agent_run_ids"][0]
        )

        # Simulate the agent finishing.
        run.status = AgentRun.Status.COMPLETED
        run.save(update_fields=["status"])

        task.status = Task.Status.REVIEW
        task.save(update_fields=["status"])

        # The user approves the task.
        task.status = Task.Status.DONE
        task.completed = True
        task.save(
            update_fields=["status", "completed"]
        )

        # Simulate the task handler calling our new function.
        sync_project_execution_after_task_change(
            self.project,
            dispatch=False,
        )

        execution = ProjectExecution.objects.get(
            project=self.project,
        )

        self.assertEqual(
            execution.status,
            ProjectExecution.Status.COMPLETED,
        )

        print(
            "PASS: Final task approval "
            "automatically completes execution"
        )
    def test_stop_cancels_queued_agents(self):
        # Create five independent tasks.
        for i in range(5):
            self.create_task(f"Task {i}")

        # Start Execute with three queued agents.
        start_project_execution(
            self.project,
            self.user,
            dispatch=False,
        )

        self.assertEqual(
            AgentRun.objects.filter(
                project=self.project,
                status=AgentRun.Status.QUEUED,
            ).count(),
            3,
        )

        # Stop execution.
        stop_project_execution(
            self.project,
            self.user,
        )

        execution = ProjectExecution.objects.get(
            project=self.project,
        )

        # Execution should be stopped.
        self.assertEqual(
            execution.status,
            ProjectExecution.Status.STOPPED,
        )

        # All three queued agents should be cancelled.
        self.assertEqual(
            AgentRun.objects.filter(
                project_execution=execution,
                status=AgentRun.Status.CANCELLED,
            ).count(),
            3,
        )

        # No queued agents should remain.
        self.assertFalse(
            AgentRun.objects.filter(
                project_execution=execution,
                status=AgentRun.Status.QUEUED,
            ).exists()
        )
    def test_stop_cancels_running_agents(self):
        # Create three independent tasks.
        for i in range(3):
            self.create_task(f"Task {i}")

        # Start execution without dispatching workers.
        start_project_execution(
            self.project,
            self.user,
            dispatch=False,
        )

        execution = ProjectExecution.objects.get(
            project=self.project,
        )

        # Simulate one agent already running.
        running_agent = AgentRun.objects.filter(
            project_execution=execution,
            status=AgentRun.Status.QUEUED,
        ).first()

        self.assertIsNotNone(running_agent)

        running_agent.status = AgentRun.Status.RUNNING
        running_agent.save(update_fields=["status"])

        # Stop the project.
        stop_project_execution(
            self.project,
            self.user,
        )

        running_agent.refresh_from_db()
        execution.refresh_from_db()

        # Execution must be stopped.
        self.assertEqual(
            execution.status,
            ProjectExecution.Status.STOPPED,
        )

        # The running agent must be cancelled.
        self.assertEqual(
            running_agent.status,
            AgentRun.Status.CANCELLED,
        )

        # No active swarm agents should remain.
        self.assertFalse(
            AgentRun.objects.filter(
                project_execution=execution,
                status__in=[
                    AgentRun.Status.QUEUED,
                    AgentRun.Status.RUNNING,
                ],
            ).exists()
        )
    def test_stale_agent_cannot_move_task_to_review(self):
        from projects.ai.project_executor import handle_agent_completion
        from projects.models import AgentRun, ProjectExecution

        task = self.create_task("Task from previous execution")

        execution = ProjectExecution.objects.create(
            project=self.project,
            started_by=self.user,
            status=ProjectExecution.Status.RUNNING,
            generation=2,
        )

        stale_run = AgentRun.objects.create(
            project=self.project,
            project_execution=execution,
            execution_generation=1,
            task=task,
            user=self.user,
            status=AgentRun.Status.COMPLETED,
        )

        result = handle_agent_completion(stale_run.pk)

        task.refresh_from_db()

        self.assertFalse(result["handled"])
        self.assertEqual(task.status, Task.Status.TODO)