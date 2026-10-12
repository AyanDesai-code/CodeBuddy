import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from projects.models import (
    AgentRun,
    Project,
    ProjectExecution,
    Task,
)
from projects.ai.services import execute_agent_run
from projects.ai.project_executor import start_project_execution

def mock_function_call(name, arguments, call_id):
    return SimpleNamespace(
        type="function_call",
        name=name,
        arguments=json.dumps(arguments),
        call_id=call_id,
    )


class AgentExecutionTests(TestCase):

    def test_browser_tool_to_completed_run(self):
        user = get_user_model().objects.create_user(
            username="execution_test_user",
            password="test-password-123",
        )

        project = Project.objects.create(
            owner=user,
            name="Agent Execution Test",
        )

        task = Task.objects.create(
            project=project,
            title="Inspect a webpage",
        )

        run = AgentRun.objects.create(
            project=project,
            task=task,
            user=user,
        )

        first_response = SimpleNamespace(
            id="mock-response-1",
            output=[
                mock_function_call(
                    "browser_open",
                    {"url": "https://example.com"},
                    "call-1",
                )
            ],
        )

        second_response = SimpleNamespace(
            id="mock-response-2",
            output=[
                mock_function_call(
                    "finish_agent_run",
                    {
                        "status": "completed",
                        "summary": "Opened the example webpage.",
                        "blocker_reason": "",
                        "user_action_required": "",
                    },
                    "call-2",
                )
            ],
        )

        mock_client = MagicMock()
        mock_client.responses.create.side_effect = [
            first_response,
            second_response,
        ]

        with (
            patch(
                "projects.ai.services.OpenAI",
                return_value=mock_client,
            ),
            patch(
                "projects.ai.services.execute_agent_tool",
                return_value={
                    "success": True,
                    "url": "https://example.com",
                },
            ) as mock_tool,
        ):
            execute_agent_run(run.pk)

        run.refresh_from_db()

        self.assertEqual(
            run.status,
            AgentRun.Status.COMPLETED,
        )

        self.assertEqual(
            mock_client.responses.create.call_count,
            2,
        )

        mock_tool.assert_called_once()

        tool_kwargs = mock_tool.call_args.kwargs

        self.assertEqual(
            tool_kwargs["tool_name"],
            "browser_open",
        )

        self.assertEqual(
            tool_kwargs["arguments"],
            {"url": "https://example.com"},
        )

        second_request = (
            mock_client.responses.create.call_args_list[1]
        )

        self.assertEqual(
            second_request.kwargs["previous_response_id"],
            "mock-response-1",
        )

        tool_output = second_request.kwargs["input"][0]

        self.assertEqual(
            tool_output["type"],
            "function_call_output",
        )

        self.assertEqual(
            tool_output["call_id"],
            "call-1",
        )

        self.assertTrue(
            json.loads(tool_output["output"])["success"]
        )

        print("PASS: Agent completed mocked browser execution")
        print("PASS: Tool arguments were correct")
        print("PASS: Tool result returned to AI")
        print("PASS: No real API or browser calls")
    def test_swarm_agent_completion_triggers_continuation(self):
        user = get_user_model().objects.create_user(
            username="swarm_execution_test_user",
            password="test-password-123",
        )

        project = Project.objects.create(
            owner=user,
            name="Swarm Execution Test",
        )

        task = Task.objects.create(
            project=project,
            title="Complete a simple task",
        )

        execution = ProjectExecution.objects.create(
            project=project,
            started_by=user,
            status=ProjectExecution.Status.RUNNING,
        )

        run = AgentRun.objects.create(
            project=project,
            task=task,
            user=user,
            project_execution=execution,
        )

        mock_response = SimpleNamespace(
            id="mock-response-complete",
            output=[
                mock_function_call(
                    "finish_agent_run",
                    {
                        "status": "completed",
                        "summary": "Task completed successfully.",
                        "blocker_reason": "",
                        "user_action_required": "",
                    },
                    "call-complete",
                )
            ],
        )

        mock_client = MagicMock()
        mock_client.responses.create.return_value = mock_response

        with (
            patch(
                "projects.ai.services.OpenAI",
                return_value=mock_client,
            ),
            patch(
                "projects.ai.services.execute_agent_tool",
                return_value={"success": True},
            ),
            patch(
                "projects.ai.project_executor.continue_project_execution",
            ) as mock_continue,
        ):
            execute_agent_run(run.pk)

        run.refresh_from_db()

        self.assertEqual(
            run.status,
            AgentRun.Status.COMPLETED,
        )

        mock_continue.assert_called_once_with(
            run.pk,
            dispatch=False,
        )
    def test_completed_agent_automatically_creates_replacement(self):
        user = get_user_model().objects.create_user(
            username="replacement_test_user",
            password="test-password-123",
        )

        project = Project.objects.create(
            owner=user,
            name="Automatic Replacement Test",
        )

        for i in range(5):
            Task.objects.create(
                project=project,
                title=f"Independent task {i + 1}",
            )

        result = start_project_execution(
            project,
            user,
            dispatch=False,
        )

        self.assertEqual(len(result["agent_run_ids"]), 3)

        completed_run_id = result["agent_run_ids"][0]

        mock_response = SimpleNamespace(
            id="mock-replacement-response",
            output=[
                mock_function_call(
                    "finish_agent_run",
                    {
                        "status": "completed",
                        "summary": "Task completed successfully.",
                        "blocker_reason": "",
                        "user_action_required": "",
                    },
                    "call-replacement",
                )
            ],
        )

        mock_client = MagicMock()
        mock_client.responses.create.return_value = mock_response

        with (
            patch(
                "projects.ai.services.OpenAI",
                return_value=mock_client,
            ),
            patch(
                "projects.ai.services.execute_agent_tool",
                return_value={"success": True},
            ),
            self.settings(PROJIVO_EXECUTE_LIVE_DISPATCH=False),
        ):
            execute_agent_run(completed_run_id)

        completed_run = AgentRun.objects.get(
            pk=completed_run_id,
        )

        completed_run.task.refresh_from_db()

        self.assertEqual(
            completed_run.status,
            AgentRun.Status.COMPLETED,
        )

        self.assertEqual(
            completed_run.task.status,
            Task.Status.REVIEW,
        )

        active_runs = AgentRun.objects.filter(
            project=project,
            project_execution__isnull=False,
            status__in=[
                AgentRun.Status.QUEUED,
                AgentRun.Status.RUNNING,
            ],
        )

        self.assertEqual(active_runs.count(), 3)

        self.assertEqual(
            AgentRun.objects.filter(
                project=project,
                project_execution__isnull=False,
            ).count(),
            4,
        )

        print(
            "PASS: Completed agent automatically "
            "created a replacement"
        )
    def test_agent_cannot_execute_twice(self):
        user = get_user_model().objects.create_user(
            username="duplicate_execution_user",
            password="test-password-123",
        )

        project = Project.objects.create(
            owner=user,
            name="Duplicate Execution Test",
        )

        task = Task.objects.create(
            project=project,
            title="Execute only once",
        )

        run = AgentRun.objects.create(
            project=project,
            task=task,
            user=user,
            status=AgentRun.Status.RUNNING,
        )

        with patch(
            "projects.ai.services.OpenAI"
        ) as mock_openai:
            execute_agent_run(run.pk)

        run.refresh_from_db()

        self.assertEqual(
            run.status,
            AgentRun.Status.RUNNING,
        )

        mock_openai.assert_not_called()

        print(
            "PASS: Already-running agent "
            "was not executed twice"
        )
    def test_failed_agent_automatically_creates_replacement(self):
        user = get_user_model().objects.create_user(
            username="failure_recovery_user",
            password="test-password-123",
        )

        project = Project.objects.create(
            owner=user,
            name="Failure Recovery Test",
        )

        for i in range(5):
            Task.objects.create(
                project=project,
                title=f"Independent task {i + 1}",
            )

        result = start_project_execution(
            project,
            user,
            dispatch=False,
        )

        self.assertEqual(len(result["agent_run_ids"]), 3)

        failed_run_id = result["agent_run_ids"][0]

        with (
            patch(
                "projects.ai.services.OpenAI",
                side_effect=RuntimeError(
                    "Simulated OpenAI API failure"
                ),
            ),
            self.settings(PROJIVO_EXECUTE_LIVE_DISPATCH=False),
        ):
            execute_agent_run(failed_run_id)

        failed_run = AgentRun.objects.get(
            pk=failed_run_id,
        )

        failed_run.task.refresh_from_db()

        self.assertEqual(
            failed_run.status,
            AgentRun.Status.FAILED,
        )

        # A failed task must not be marked completed.
        self.assertNotEqual(
            failed_run.task.status,
            Task.Status.REVIEW,
        )

        # Three active agents should remain.
        active_runs = AgentRun.objects.filter(
            project=project,
            project_execution__isnull=False,
            status__in=[
                AgentRun.Status.QUEUED,
                AgentRun.Status.RUNNING,
            ],
        )

        self.assertEqual(active_runs.count(), 3)

        # Three original runs plus one replacement.
        self.assertEqual(
            AgentRun.objects.filter(
                project=project,
                project_execution__isnull=False,
            ).count(),
            4,
        )

        # The failed task must not be retried automatically.
        self.assertEqual(
            AgentRun.objects.filter(
                project=project,
                task=failed_run.task,
            ).count(),
            1,
        )

        print(
            "PASS: Failed agent automatically "
            "created a replacement"
        )
    def test_stale_generation_agent_cannot_start(self):
        user = get_user_model().objects.create_user(
            username="stale_agent_test_user",
            password="test-password-123",
        )

        project = Project.objects.create(
            owner=user,
            name="Stale Agent Test",
        )

        task = Task.objects.create(
            project=project,
            title="Test stale execution",
        )

        # Create a running execution at generation 2.
        execution = ProjectExecution.objects.create(
            project=project,
            started_by=user,
            status=ProjectExecution.Status.RUNNING,
            generation=2,
        )

        # Simulate an old queued agent from generation 1.
        stale_run = AgentRun.objects.create(
            project=project,
            project_execution=execution,
            execution_generation=1,
            task=task,
            user=user,
            status=AgentRun.Status.QUEUED,
        )

        # Mock all external operations.
        with (
            patch("projects.ai.services.OpenAI") as mock_openai,
            patch(
                "projects.ai.services.execute_agent_tool"
            ) as mock_tool,
            patch(
                "projects.ai.services.preserve_workspace_state",
                return_value={
                    "changed_files": [],
                    "patch_bytes": 0,
                },
            ),
        ):
            execute_agent_run(stale_run.pk)

        stale_run.refresh_from_db()

        # The stale agent must never start.
        self.assertEqual(
            stale_run.status,
            AgentRun.Status.QUEUED,
        )

        # No AI requests or tools should execute.
        mock_openai.assert_not_called()
        mock_tool.assert_not_called()