from projects.models import (
    Project,
    Task,
    AgentRun,
    ProjectExecution,
)

MAX_CONCURRENT_AGENTS = 3


def get_ready_tasks(project, limit=MAX_CONCURRENT_AGENTS):


    if limit < 1:
        return []

    active_agents = AgentRun.objects.filter(
        project=project,
        project_execution__isnull=False,
        status__in=[
            AgentRun.Status.QUEUED,
            AgentRun.Status.RUNNING,
        ],
    ).count()

    available_slots = max(
        0,
        min(limit, MAX_CONCURRENT_AGENTS - active_agents),
    )

    if available_slots == 0:
        return []

    tasks = list(
        Task.objects.filter(
            project=project,
            status=Task.Status.TODO,
        )
        .prefetch_related("dependencies")
        .order_by("-priority", "order", "created_at")
    )

    ready = []

    for task in tasks:
        dependencies = list(task.dependencies.all())

        if any(
            dependency.project_id != project.pk
            for dependency in dependencies
        ):
            continue

        if any(
            dependency.status != Task.Status.DONE
            for dependency in dependencies
        ):
            continue

                # Skip tasks with an active or blocked agent.
        if task.agent_runs.filter(
            status__in=[
                AgentRun.Status.QUEUED,
                AgentRun.Status.RUNNING,
                AgentRun.Status.BLOCKED,
            ],
        ).exists():
            continue

        # Prevent automatic retries of failed tasks.
        # Failed tasks will require manual intervention.
        if task.agent_runs.filter(
            status=AgentRun.Status.FAILED,
        ).exists():
            continue

        ready.append(task)

        if len(ready) >= available_slots:
            break

    return ready


def get_execution_overview(project):


    tasks = Task.objects.filter(project=project)

    total = tasks.count()

    completed = tasks.filter(
        status=Task.Status.DONE
    ).count()

    in_progress = tasks.filter(
        status=Task.Status.IN_PROGRESS
    ).count()

    ready_tasks = get_ready_tasks(project)

    return {
        "total_tasks": total,
        "completed_tasks": completed,
        "in_progress_tasks": in_progress,
        "remaining_tasks": total - completed,
        "ready_task_ids": [
            task.pk for task in ready_tasks
        ],
        "max_concurrent_agents": MAX_CONCURRENT_AGENTS,
    }
def launch_project_swarm(
    project,
    user,
    *,
    model_name="gpt-5-mini",
    dispatch=False,
):
    """
    Reserve available tasks for Projivo Execute.

    dispatch=False: Create queued agents without executing them.
    dispatch=True: Launch agents through Celery.
    """

    from django.db import connection, transaction
    from django.core.exceptions import PermissionDenied

    from projects.models import (
        Project,
        ProjectMembership,
        AgentRunLog,
    )

    from projects.tasks import execute_agent_run_task

    if not user.is_authenticated:
        raise PermissionDenied("Authentication required.")

    is_owner = project.owner_id == user.pk

    is_editor = ProjectMembership.objects.filter(
        project=project,
        user=user,
        role__in=["owner", "editor"],
    ).exists()

    if not (is_owner or is_editor):
        raise PermissionDenied(
            "You cannot execute this project."
        )

    if dispatch and connection.vendor != "postgresql":
        raise RuntimeError(
            "Concurrent swarm dispatch requires PostgreSQL."
        )
    
    with transaction.atomic():

        # Lock project to coordinate swarm launch requests.
        locked_project = (
            Project.objects
            .select_for_update()
            .get(pk=project.pk)
        )
                # Find the active project execution.

        execution = (
            ProjectExecution.objects
            .select_for_update()
            .filter(
                project=locked_project,
                status=ProjectExecution.Status.RUNNING,
            )
            .first()
        )

        # Do not reserve agents for a paused,
        # stopped, or inactive execution.
        if execution is None:
            return []

        # Find tasks that are ready for execution.
        ready_tasks = get_ready_tasks(
            locked_project,
            limit=MAX_CONCURRENT_AGENTS,
        )

        created_runs = []

        for task in ready_tasks:

            # Prevent duplicate active agents.
            existing_run = AgentRun.objects.filter(
                task=task,
                status__in=[
                    AgentRun.Status.QUEUED,
                    AgentRun.Status.RUNNING,
                    AgentRun.Status.BLOCKED,
                ],
            ).exists()

            if existing_run:
                continue

            # Create an agent for this task.
            run = AgentRun.objects.create(
                project=locked_project,
                project_execution=execution,
                execution_generation=execution.generation,
                task=task,
                user=user,
                model_name=model_name,
                status=AgentRun.Status.QUEUED,
                progress=0,
                current_step="Queued by Execute",
            )

            AgentRunLog.objects.create(
                run=run,
                message="Projivo Execute reserved this task.",
            )

            created_runs.append(run)

        # Dispatch agents only when explicitly enabled.
        if dispatch:

            run_ids = [
                run.pk
                for run in created_runs
            ]

            def enqueue_runs():
                for run_id in run_ids:
                    execute_agent_run_task.delay(run_id)

            transaction.on_commit(enqueue_runs)

    return created_runs



def handle_agent_completion(run_id):
    """
    Process a completed agent run.

    Completed agent runs move their tasks into REVIEW.
    Tasks are not automatically marked DONE.
    """

    from django.db import transaction

    with transaction.atomic():

        run = (
            AgentRun.objects
            .select_for_update()
            .select_related("task")
            .get(pk=run_id)
        )

        if run.status != AgentRun.Status.COMPLETED:
            return {
                "handled": False,
                "reason": "Agent has not completed.",
            }

        if run.project_execution_id is not None:
            execution = (
                ProjectExecution.objects
                .select_for_update()
                .get(pk=run.project_execution_id)
            )

            if run.execution_generation != execution.generation:
                return {
                    "handled": False,
                    "reason": "Agent belongs to an outdated execution.",
                }

        task = run.task

        if task is None:
            return {
                "handled": False,
                "reason": "Agent has no assigned task.",
            }

        if task.status == Task.Status.DONE:
            return {
                "handled": False,
                "reason": "Task is already complete.",
            }

        task.status = Task.Status.REVIEW

        task.save(
            update_fields=["status"]
        )

        return {
            "handled": True,
            "task_id": task.pk,
            "task_status": task.status,
            "run_id": run.pk,
        }
def refill_project_swarm(project, user, *, dispatch=False):
    """
    Refill available agent slots and detect
    when the entire project is completed.
    """

    from django.db import transaction

    from projects.models import (
        AgentRun,
        Project,
        ProjectExecution,
        Task,
    )

    with transaction.atomic():

        # Lock the project before its execution record.
        locked_project = (
            Project.objects
            .select_for_update()
            .get(pk=project.pk)
        )

        execution = (
            ProjectExecution.objects
            .select_for_update()
            .filter(project=locked_project)
            .first()
        )

        if execution is None:
            return []

        if execution.status != ProjectExecution.Status.RUNNING:
            return []

        # Check whether any agents are still active.
        active_agents = AgentRun.objects.filter(
            project=locked_project,
            project_execution=execution,
            status__in=[
                AgentRun.Status.QUEUED,
                AgentRun.Status.RUNNING,
            ],
        ).exists()

        # Check whether any project tasks remain unfinished.
        unfinished_tasks = Task.objects.filter(
            project=locked_project,
        ).exclude(
            status=Task.Status.DONE,
        ).exists()

        # A project is completed only when:
        # 1. No agents are active.
        # 2. Every task is DONE.
        if not active_agents and not unfinished_tasks:
            execution.status = ProjectExecution.Status.COMPLETED
            execution.save(update_fields=["status"])
            return []

    # If work remains, fill available agent slots.
    return launch_project_swarm(
        project=project,
        user=user,
        dispatch=dispatch,
    )
def sync_project_execution_after_task_change(
    project,
    *,
    dispatch=False,
):
    """
    Synchronize Projivo Execute after a task status changes.

    Called after task changes have been saved.
    """

    from projects.models import ProjectExecution

    execution = (
        ProjectExecution.objects
        .select_related("started_by")
        .filter(project=project)
        .first()
    )

    if execution is None:
        return []

    # Never restart paused, stopped, or completed runs.
    if execution.status != ProjectExecution.Status.RUNNING:
        return []

    if execution.started_by_id is None:
        return []

    return refill_project_swarm(
        project=project,
        user=execution.started_by,
        dispatch=dispatch,
    )
def start_project_execution(
    project,
    user,
    *,
    dispatch=False,
):
    """
    Start Projivo Execute for a project.

    dispatch=False reserves agents without
    sending them to Celery.
    """

    from django.db import transaction
    from django.core.exceptions import PermissionDenied
    from django.utils import timezone

    from projects.models import (
        Project,
        ProjectExecution,
        ProjectMembership,
    )

    if not user.is_authenticated:
        raise PermissionDenied(
            "Authentication required."
        )

    is_owner = project.owner_id == user.pk

    is_editor = ProjectMembership.objects.filter(
        project=project,
        user=user,
        role__in=["owner", "editor"],
    ).exists()

    if not (is_owner or is_editor):
        raise PermissionDenied(
            "You cannot execute this project."
        )

    with transaction.atomic():

        # Always acquire the project lock first.
        locked_project = (
            Project.objects
            .select_for_update()
            .get(pk=project.pk)
        )

        # Acquire the execution lock second.
        execution, created = (
            ProjectExecution.objects
            .select_for_update()
            .get_or_create(
                project=locked_project,
                defaults={
                    "started_by": user,
                    "status": ProjectExecution.Status.IDLE,
                },
            )
        )

        if execution.status == ProjectExecution.Status.RUNNING:
            return {
                "execution_id": execution.pk,
                "status": execution.status,
                "already_running": True,
                "agent_run_ids": [],
            }

                # Each new execution attempt gets a unique generation.
        # This distinguishes new agents from old cancelled agents.
        execution.generation += 1

        execution.status = ProjectExecution.Status.RUNNING
        execution.started_by = user
        execution.started_at = timezone.now()
        execution.completed_at = None

        execution.save(
            update_fields=[
                "generation",
                "status",
                "started_by",
                "started_at",
                "completed_at",
                "updated_at",
            ]
        )

        runs = launch_project_swarm(
            locked_project,
            user,
            dispatch=dispatch,
        )

    return {
        "execution_id": execution.pk,
        "status": execution.status,
        "already_running": False,
        "agent_run_ids": [
            run.pk for run in runs
        ],
    }
def pause_project_execution(project, user):
    """
    Pause scheduling new agents.

    Already-running agents are not interrupted.
    """

    from django.core.exceptions import PermissionDenied
    from django.db import transaction

    from projects.models import (
        Project,
        ProjectExecution,
    )

    if project.owner_id != user.pk:
        raise PermissionDenied(
            "Only the project owner can pause execution."
        )

    with transaction.atomic():

        # Acquire the same project lock used by
        # launch_project_swarm().
        locked_project = (
            Project.objects
            .select_for_update()
            .get(pk=project.pk)
        )

        execution = (
            ProjectExecution.objects
            .select_for_update()
            .get(project=locked_project)
        )

        if execution.status == ProjectExecution.Status.RUNNING:
            execution.status = ProjectExecution.Status.PAUSED

            execution.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )
                        # Cancel agents that have not started.
            # Running agents are handled separately.
            AgentRun.objects.filter(
                project_execution=execution,
                status=AgentRun.Status.QUEUED,
            ).update(
                status=AgentRun.Status.CANCELLED,
            )

    return execution


def resume_project_execution(
    project,
    user,
    *,
    dispatch=False,
):
    """
    Resume scheduling agents for a paused project.
    """

    from django.core.exceptions import PermissionDenied
    from django.db import transaction

    from projects.models import (
        AgentRun,
        Project,
        ProjectExecution,
    )

    if project.owner_id != user.pk:
        raise PermissionDenied(
            "Only the project owner can resume execution."
        )

    with transaction.atomic():

        # Lock the project first, matching the scheduler.
        locked_project = (
            Project.objects
            .select_for_update()
            .get(pk=project.pk)
        )

        # Then lock the execution record.
        execution = (
            ProjectExecution.objects
            .select_for_update()
            .get(project=locked_project)
        )

        if execution.status != ProjectExecution.Status.PAUSED:
            return {
                "status": execution.status,
                "resumed": False,
                "agent_run_ids": [],
            }

        execution.status = ProjectExecution.Status.RUNNING

        execution.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

        runs = launch_project_swarm(
            locked_project,
            user,
            dispatch=dispatch,
        )

    return {
        "status": execution.status,
        "resumed": True,
        "agent_run_ids": [
            run.pk for run in runs
        ],
    }
def stop_project_execution(project, user):
    """
    Stop project execution and cancel queued agents.

    Already-running agents are not cancelled.
    """

    from django.core.exceptions import PermissionDenied
    from django.db import transaction

    from projects.models import (
        AgentRun,
        Project,
        ProjectExecution,
    )

    if project.owner_id != user.pk:
        raise PermissionDenied(
            "Only the project owner can stop execution."
        )

    with transaction.atomic():

        locked_project = (
            Project.objects
            .select_for_update()
            .get(pk=project.pk)
        )

        execution = (
            ProjectExecution.objects
            .select_for_update()
            .get(project=locked_project)
        )

        if execution.status in [
            ProjectExecution.Status.RUNNING,
            ProjectExecution.Status.PAUSED,
        ]:

            execution.status = ProjectExecution.Status.STOPPED

            execution.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

            # Cancel all agents that haven't started.
                        # Cancel queued agents and request
            # cooperative cancellation of running agents.
            AgentRun.objects.filter(
                project_execution=execution,
                status__in=[
                    AgentRun.Status.QUEUED,
                    AgentRun.Status.RUNNING,
                ],
            ).update(
                status=AgentRun.Status.CANCELLED,
                current_step="Cancelled by project owner",
            )

    return execution
def continue_project_execution(run_id, *, dispatch=False):
    """
    Continue a project execution after an agent finishes.

    Only agents belonging to Projivo Execute can
    trigger automatic scheduling.
    """

    from projects.models import (
        AgentRun,
        ProjectExecution,
    )

    run = (
        AgentRun.objects
        .select_related(
            "project",
            "project_execution",
        )
        .get(pk=run_id)
    )

    # Ignore manually deployed agents.
    if run.project_execution_id is None:
        return []

    # Only continue after the agent reaches
    # a terminal state.
    terminal_statuses = [
        AgentRun.Status.COMPLETED,
        AgentRun.Status.FAILED,
        AgentRun.Status.CANCELLED,
    ]

    if run.status not in terminal_statuses:
        return []

    execution = run.project_execution

    # Respect Pause and Stop.
    if execution.status != ProjectExecution.Status.RUNNING:
        return []
     # Prevent agents from previous executions
    # from triggering new agents.
    if run.execution_generation != execution.generation:
        return []

    # The agent that started Execute determines
    # which user owns the continuation.
    user = execution.started_by

    if user is None:
        return []

    # Find ready tasks and reserve available slots.
    return refill_project_swarm(
        project=run.project,
        user=user,
        dispatch=dispatch,
    )
