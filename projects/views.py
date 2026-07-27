import difflib
import json
import time

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .ai.services import (

    generate_additional_tasks,
    generate_project_schedule,
    generate_reply,
    generate_workspace_content,
    generate_workspace_update_plan,
    regenerate_workspace_section,
    review_project,
)
from .models import (
    Project,
    ProjectChange,
    ProjectConflict,
    ProjectEvent,
    ProjectHealthReviewRecord,
    ProjectMembership,
    ProjectMessage,
    ProjectMilestone,
    ProjectState,
    Task,
    WorkspaceFolder,
    WorkspaceMessage,
)

from .permissions import (
    get_editable_project_for_user,
    get_owned_project_for_user,
    get_project_for_user,
    project_permission_context,
    user_is_project_owner,
)
import traceback

def record_project_event(
    *,
    project,
    event_type,
    title,
    description="",
    metadata=None,
):
    return ProjectEvent.objects.create(
        project=project,
        event_type=event_type,
        title=title,
        description=description,
        metadata=metadata or {},
    )
def mark_schedule_for_refresh(
    *,
    project,
    reason,
):
    project.schedule_needs_refresh = True
    project.schedule_refresh_reason = reason

    project.save(
        update_fields=[
            "schedule_needs_refresh",
            "schedule_refresh_reason",
            "updated_at",
        ]
    )
def build_text_diff(before_text, after_text):
    before_lines = (before_text or "").splitlines()
    after_lines = (after_text or "").splitlines()

    diff_lines = difflib.ndiff(
        before_lines,
        after_lines,
    )

    result = []

    for line in diff_lines:
        prefix = line[:2]
        content = line[2:]

        if prefix == "- ":
            result.append(
                {
                    "change_type": "removed",
                    "content": content,
                }
            )

        elif prefix == "+ ":
            result.append(
                {
                    "change_type": "added",
                    "content": content,
                }
            )

        elif prefix == "  ":
            result.append(
                {
                    "change_type": "unchanged",
                    "content": content,
                }
            )

    return result
def task_snapshot_key(task_data):
    task_id = task_data.get("id")

    if task_id is not None:
        return f"id:{task_id}"

    return (
        "title:"
        + task_data.get("title", "").strip().lower()
    )

def normalize_task_title(title):
    ignored_words = {
        "a",
        "an",
        "and",
        "for",
        "of",
        "the",
        "to",
        "with",
    }

    return {
        word.strip(".,:;()-").lower()
        for word in title.split()
        if word.lower() not in ignored_words
    }


@login_required
def project_list(request):
    show_archived = request.GET.get("archived") == "1"

    projects = (
        Project.objects
        .filter(memberships__user=request.user)
        .select_related("owner")
        .prefetch_related(
            "tasks",
            "conflicts",
            "health_reviews",
            "memberships",
            "memberships__user",
        )
        .distinct()
        .order_by("-updated_at")
    )

    if show_archived:
        projects = projects.filter(
            status=Project.Status.ARCHIVED,
        )
    else:
        projects = projects.exclude(
            status=Project.Status.ARCHIVED,
        )

    project_cards = []

    for project in projects:
        total_tasks = project.tasks.count()
        completed_tasks = project.tasks.filter(
            status=Task.Status.DONE,
        ).count()

        task_progress = 0
        if total_tasks > 0:
            task_progress = round(
                completed_tasks / total_tasks * 100
            )

        latest_review = (
            project.health_reviews
            .order_by("-created_at")
            .first()
        )

        health_score = (
            latest_review.health_score
            if latest_review is not None
            else None
        )

        open_conflict_count = (
            project.conflicts.filter(
                status=ProjectConflict.Status.OPEN,
            ).count()
        )

        permission_context = project_permission_context(
            project=project,
            user=request.user,
        )

        project_cards.append(
            {
                "project": project,
                "total_tasks": total_tasks,
                "completed_tasks": completed_tasks,
                "task_progress": task_progress,
                "health_score": health_score,
                "open_conflict_count": open_conflict_count,
                **permission_context,
            }
        )

    return render(
        request,
        "projects/list.html",
        {
            "project_cards": project_cards,
            "show_archived": show_archived,
        },
    )

@login_required
@require_POST
def rename_project(request, project_pk):
    project = get_owned_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    new_name = request.POST.get("name", "").strip()

    if not new_name:
        messages.error(
            request,
            "Project name cannot be blank.",
        )
        return redirect("project_list")

    old_name = project.name or "Untitled Project"
    project.name = new_name
    project.save(
        update_fields=["name", "updated_at"],
    )

    messages.success(
        request,
        f'"{old_name}" was renamed to "{new_name}".',
    )
    return redirect("project_list")


@login_required
@require_POST
def delete_project(request, project_pk):
    project = get_owned_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    project_name = project.name or "Untitled Project"
    was_archived = (
        project.status == Project.Status.ARCHIVED
    )

    project.delete()

    messages.success(
        request,
        f'"{project_name}" was permanently deleted.',
    )

    if was_archived:
        return redirect(
            f"{reverse('project_list')}?archived=1"
        )

    return redirect("project_list")


@login_required
@require_POST
def archive_project(
    request,
    project_pk,
):
    project = get_owned_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    project_name = (
        project.name
        or "Untitled Project"
    )

    project.status = (
        Project.Status.ARCHIVED
    )

    project.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    messages.success(
        request,
        f'"{project_name}" was archived.',
    )

    return redirect("project_list")
@login_required
@require_POST
def restore_project(
    request,
    project_pk,
):
    project = get_owned_project_for_user(
        project_pk=project_pk,
        user=request.user,
        status=Project.Status.ARCHIVED,
    )

    project_name = (
        project.name
        or "Untitled Project"
    )

    project.status = Project.Status.ACTIVE

    project.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    messages.success(
        request,
        f'"{project_name}" was restored.',
    )

    return redirect(
        f"{reverse('project_list')}?archived=1"
    )

@login_required
def new_project(request):
    project = Project.objects.create(
        owner=request.user,
        status=Project.Status.DRAFT,
    )
    messages.success(
        request,
        "New project created.",
    )
    ProjectMembership.objects.create(
        project=project,
        user=request.user,
        role=ProjectMembership.Role.OWNER,
    )

    ProjectState.objects.create(
        project=project,
        facts={},
    )

    return redirect("project_setup", pk=project.pk)
@login_required
def project_setup(request, pk):
    project = get_owned_project_for_user(
        project_pk=pk,
        user=request.user,
    )
    if project.status == Project.Status.ACTIVE:
        return redirect(
            "workspace",
            project_pk=project.pk,
        )

    if request.method == "POST":
        content = request.POST.get(
            "message",
            "",
        ).strip()

        if not content:
            messages.error(
                request,
                "Enter a project idea first.",
            )

            return redirect(
                "project_setup",
                pk=project.pk,
            )

        # Prevent multiple simultaneous requests for
        # the same project.
        lock_key = (
            f"project-setup-processing-"
            f"{project.pk}"
        )

        lock_acquired = cache.add(
            lock_key,
            True,
            timeout=120,
        )

        if not lock_acquired:
            messages.warning(
                request,
                (
                    "BuilderOS is already processing "
                    "your previous message."
                ),
            )

            return redirect(
                "project_setup",
                pk=project.pk,
            )

        try:
            # Prevent the same prompt from being saved
            # repeatedly within a short period.
            recent_duplicate = (
                ProjectMessage.objects.filter(
                    project=project,
                    role=ProjectMessage.Role.USER,
                    content=content,
                    created_at__gte=(
                        timezone.now()
                        - timedelta(seconds=15)
                    ),
                )
                .exists()
            )

            if recent_duplicate:
                messages.warning(
                    request,
                    (
                        "That message was already "
                        "submitted."
                    ),
                )

                return redirect(
                    "project_setup",
                    pk=project.pk,
                )

            ProjectMessage.objects.create(
                project=project,
                role=ProjectMessage.Role.USER,
                content=content,
            )

            try:
                result = generate_reply(project)

                print(
                    "\n===== BuilderOS Response ====="
                )
                print(
                    result.model_dump_json(
                        indent=4
                    )
                )
                print(
                    "==============================\n"
                )

                ProjectMessage.objects.create(
                    project=project,
                    role=(
                        ProjectMessage.Role.ASSISTANT
                    ),
                    content=result.message,
                )

                if result.ready:
                    project.status = (
                        Project.Status.GENERATING
                    )

                    project.save(
                        update_fields=[
                            "status",
                            "updated_at",
                        ]
                    )

            except Exception as error:
                print(
                    "Project setup AI error:",
                    error,
                )

                ProjectMessage.objects.create(
                    project=project,
                    role=(
                        ProjectMessage.Role.ASSISTANT
                    ),
                    content=(
                        "I ran into a problem. "
                        "Please try again."
                    ),
                )

                messages.error(
                    request,
                    (
                        "BuilderOS could not process "
                        "that message."
                    ),
                )

        finally:
            cache.delete(lock_key)

        return redirect(
            "project_setup",
            pk=project.pk,
        )

    # Do not name this variable `messages`,
    # because that would conflict with
    # django.contrib.messages.
    project_messages = project.messages.all()

    return render(
        request,
        "projects/setup.html",
        {
            "project": project,
            "project_messages": (
                project_messages
            ),
        },
    )


@login_required
@require_POST
def generate_workspace(request, pk):
    project = get_owned_project_for_user(
        project_pk=pk,
        user=request.user,
    )

    if project.status != Project.Status.GENERATING:
        return redirect(
            "project_setup",
            pk=project.pk,
        )

    default_folders = [
        {
            "name": "Overview",
            "folder_type": "overview",
        },
        {
            "name": "Requirements",
            "folder_type": "requirements",
        },
        {
            "name": "Roadmap",
            "folder_type": "roadmap",
        },
        {
            "name": "Tasks",
            "folder_type": "tasks",
        },
        {
            "name": "Materials & Stack",
            "folder_type": "resources",
        },
        {
            "name": "Budget",
            "folder_type": "budget",
        },
        {
            "name": "Learning Resources",
            "folder_type": "learning",
        },
        {
            "name": "Documentation",
            "folder_type": "documentation",
        },
        {
            "name": "Testing",
            "folder_type": "testing",
        },
    ]

    try:
        generation_started_at = time.monotonic()

        print("1. Calling workspace generator.")

        generated = generate_workspace_content(
            project
        )

        print("2. Workspace generator returned.")

        if generated is None:
            raise ValueError(
                "Workspace generation returned None."
            )

        project_name = (
            generated.project_name or ""
        ).strip()

        if not project_name:
            raise ValueError(
                "Workspace generation returned "
                "an empty project name."
            )

        required_folder_types = {
            folder["folder_type"]
            for folder in default_folders
        }

        sections_by_type = {}

        for section in generated.sections:
            folder_type = (
                section.folder_type or ""
            ).strip().lower()

            content = (
                section.content or ""
            ).strip()

            if (
                folder_type
                not in required_folder_types
            ):
                continue

            if not content:
                continue

            sections_by_type[
                folder_type
            ] = content

        print(
            "3. Parsed "
            f"{len(sections_by_type)} sections."
        )

        missing_sections = (
            required_folder_types
            - set(sections_by_type.keys())
        )

        if missing_sections:
            raise ValueError(
                "AI omitted required workspace "
                "sections: "
                + ", ".join(
                    sorted(missing_sections)
                )
            )

        if not generated.tasks:
            raise ValueError(
                "Workspace generation returned "
                "no tasks."
            )

        with transaction.atomic():
            print(
                "4. Starting database transaction."
            )

            existing_folders = {
                folder.folder_type: folder
                for folder in project.folders.all()
            }

            folders_to_create = []

            for index, folder_data in enumerate(
                default_folders,
                start=1,
            ):
                folder_type = (
                    folder_data["folder_type"]
                )

                if folder_type in existing_folders:
                    continue

                folders_to_create.append(
                    WorkspaceFolder(
                        project=project,
                        name=folder_data["name"],
                        folder_type=folder_type,
                        order=index,
                    )
                )

            if folders_to_create:
                WorkspaceFolder.objects.bulk_create(
                    folders_to_create
                )

                print(
                    "5. Created "
                    f"{len(folders_to_create)} folders."
                )
            else:
                print(
                    "5. No folders needed creation."
                )

            folders_to_update = list(
                project.folders.all()
            )

            for folder in folders_to_update:
                folder.description = (
                    sections_by_type[
                        folder.folder_type
                    ]
                )

            if folders_to_update:
                WorkspaceFolder.objects.bulk_update(
                    folders_to_update,
                    [
                        "description",
                    ],
                )

            print(
                "6. Updated "
                f"{len(folders_to_update)} folders."
            )

            if not project.tasks.exists():
                valid_statuses = {
                    value
                    for value, _
                    in Task.Status.choices
                }

                generated_tasks = []

                for index, generated_task in enumerate(
                    generated.tasks,
                    start=1,
                ):
                    title = (
                        generated_task.title or ""
                    ).strip()

                    if not title:
                        continue

                    description = (
                        generated_task.description
                        or ""
                    ).strip()

                    status = getattr(
                        generated_task,
                        "status",
                        Task.Status.TODO,
                    )

                    if status not in valid_statuses:
                        status = Task.Status.TODO

                    generated_tasks.append(
                        Task(
                            project=project,
                            title=title,
                            description=description,
                            priority=(
                                normalize_task_priority(
                                    generated_task.priority
                                )
                            ),
                            status=status,
                            completed=(
                                status
                                == Task.Status.DONE
                            ),
                            order=index,
                        )
                    )

                if not generated_tasks:
                    raise ValueError(
                        "Workspace generation returned "
                        "no valid tasks."
                    )

                Task.objects.bulk_create(
                    generated_tasks
                )

                print(
                    "7. Created "
                    f"{len(generated_tasks)} tasks."
                )
            else:
                print(
                    "7. Existing tasks preserved."
                )

            project.name = project_name
            project.status = (
                Project.Status.ACTIVE
            )

            project.save(
                update_fields=[
                    "name",
                    "status",
                    "updated_at",
                ]
            )

            print(
                "8. Project saved as active."
            )

            ProjectMembership.objects.get_or_create(
                project=project,
                user=project.owner,
                defaults={
                    "role": (
                        ProjectMembership.Role.OWNER
                    ),
                },
            )

            print(
                "9. Owner membership confirmed."
            )

            ProjectState.objects.get_or_create(
                project=project,
                defaults={
                    "facts": {},
                },
            )

            print(
                "10. Project state confirmed."
            )

            task_count = project.tasks.count()

            record_project_event(
                project=project,
                event_type=(
                    ProjectEvent.EventType
                    .WORKSPACE_GENERATED
                ),
                title="Workspace generated",
                description=(
                    f"Generated "
                    f"{len(sections_by_type)} "
                    "workspace sections and "
                    f"{task_count} tasks."
                ),
                metadata={
                    "section_count": (
                        len(sections_by_type)
                    ),
                    "task_count": task_count,
                },
            )

            print(
                "11. Workspace event recorded."
            )

        generation_seconds = (
            time.monotonic()
            - generation_started_at
        )

        print(
            "TOTAL WORKSPACE GENERATION TIME: "
            f"{generation_seconds:.2f} seconds"
        )

        messages.success(
            request,
            (
                "Your workspace was generated "
                "successfully."
            ),
        )

        return redirect(
            "workspace",
            pk=project.pk,
        )

    except Exception:
        print("\n" + "=" * 80)
        print("WORKSPACE GENERATION FAILED")
        traceback.print_exc()
        print("=" * 80 + "\n")

        messages.error(
            request,
            (
                "BuilderOS could not generate the "
                "workspace. Please try again."
            ),
        )

        return redirect(
            "project_setup",
            pk=project.pk,
        )
@login_required
def workspace(request, project_pk):
    project = get_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    folders = project.folders.all()

    latest_review = (
        project.health_reviews
        .order_by("-created_at")
        .first()
    )

    health_score = (
        latest_review.health_score
        if latest_review is not None
        else None
    )

    open_conflicts = project.conflicts.filter(
        status=ProjectConflict.Status.OPEN,
    )

    open_conflict_count = open_conflicts.count()

    critical_conflict_count = open_conflicts.filter(
        severity="critical",
    ).count()

    total_tasks = project.tasks.count()

    completed_tasks = project.tasks.filter(
        completed=True,
    ).count()

    task_progress = 0

    if total_tasks > 0:
        task_progress = round(
            completed_tasks / total_tasks * 100
        )

    high_priority_tasks = (
        project.tasks
        .filter(
            completed=False,
            priority=Task.Priority.HIGH,
        )
        .order_by("order")[:5]
    )

    recent_events = (
        project.events
        .order_by("-created_at")[:6]
    )

    recent_changes = (
        project.changes
        .order_by("-created_at")[:5]
    )
    permission_context = project_permission_context(
        project=project,
        user=request.user,
    )
    return render(
    request,
    "projects/workspace.html",
    {
        "project": project,
        "folders": folders,
        "health_score": health_score,
        "open_conflict_count": (
            open_conflict_count
        ),
        "critical_conflict_count": (
            critical_conflict_count
        ),
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
        "task_progress": task_progress,
        "high_priority_tasks": high_priority_tasks,
        "recent_events": recent_events,
        "recent_changes": recent_changes,
        **permission_context,
    },
)
@login_required
def workspace_folder(request, project_pk, folder_pk):
    project = get_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    folder = get_object_or_404(
        WorkspaceFolder,
        pk=folder_pk,
        project=project,
    )

    tasks = None
    total_tasks = 0
    completed_tasks = 0
    progress = 0

    if folder.folder_type == "tasks":
        tasks = project.tasks.order_by(
            "completed",
            "order",
        )
        total_tasks = tasks.count()
        completed_tasks = tasks.filter(completed=True).count()

        if total_tasks > 0:
            progress = round(
                completed_tasks / total_tasks * 100
            )
        permission_context = project_permission_context(
            project=project,
            user=request.user,
        )

    return render(
        request,
        "projects/workspace_folder.html",
        {
            "project": project,
            "folder": folder,
            "tasks": tasks,
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "progress": progress,
            **permission_context,
        },
    )
@login_required
def edit_workspace_folder(
    request,
    project_pk,
    folder_pk,
    **permission_context,
):
    project = get_editable_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    folder = get_object_or_404(
        WorkspaceFolder,
        pk=folder_pk,
        project=project,
    )

    if request.method == "POST":
        new_description = request.POST.get(
            "description",
            "",
        )
        old_description = folder.description

        if old_description != new_description:
            folder.description = new_description
            folder.save(
                update_fields=[
                    "description",
                    "updated_at",
                ]
            )

            schedule_relevant_sections = {
                "requirements",
                "roadmap",
                "tasks",
                "resources",
                "budget",
                "testing",
            }

            if folder.folder_type in schedule_relevant_sections:
                mark_schedule_for_refresh(
                    project=project,
                    reason=(
                        "Workspace section edited: "
                        f"{folder.name}."
                    ),
                )

            record_project_event(
                project=project,
                event_type=(
                    ProjectEvent.EventType.WORKSPACE_UPDATED
                ),
                title="Workspace section edited",
                description=folder.name,
                metadata={
                    "folder_id": folder.pk,
                    "folder_type": folder.folder_type,
                },
            )

            messages.success(
                request,
                f'"{folder.name}" was updated.',
            )
        else:
            messages.info(
                request,
                "No workspace changes were made.",
            )

        return redirect(
            "workspace_folder",
            project_pk=project.pk,
            folder_pk=folder.pk,
        )

    permission_context = project_permission_context(
        project=project,
        user=request.user,
    )

    return render(
        request,
        "projects/workspace_folder_edit.html",
        {
            "project": project,
            "folder": folder,
            **permission_context,
        },
    )


@login_required
@require_POST
def regenerate_workspace_folder(
    request,
    project_pk,
    folder_pk,
):
    project = get_editable_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    folder = get_object_or_404(
        WorkspaceFolder,
        pk=folder_pk,
        project=project,
    )

    try:
        previous_description = folder.description

        result = regenerate_workspace_section(
            project=project,
            folder=folder,
        )

        if result.content != previous_description:
            folder.description = result.content

            folder.save(
                update_fields=[
                    "description",
                    "updated_at",
                ]
            )

            schedule_relevant_sections = {
                "requirements",
                "roadmap",
                "tasks",
                "resources",
                "budget",
                "testing",
            }

            if (
                folder.folder_type
                in schedule_relevant_sections
            ):
                mark_schedule_for_refresh(
                    project=project,
                    reason=(
                        "Workspace section "
                        f"regenerated: {folder.name}."
                    ),
                )

            record_project_event(
                project=project,
                event_type=(
                    ProjectEvent.EventType
                    .WORKSPACE_UPDATED
                ),
                title="Workspace section regenerated",
                description=folder.name,
                metadata={
                    "folder_id": folder.pk,
                    "folder_type": folder.folder_type,
                },
            )

            messages.success(
                request,
                f'"{folder.name}" was regenerated successfully.',
            )

        else:
            messages.info(
                request,
                f'"{folder.name}" did not need any changes.',
            )

    except Exception as error:
        print(
            f"Failed to regenerate {folder.name}:",
            error,
        )

        messages.error(
            request,
            f'BuilderOS could not regenerate "{folder.name}".',
        )

    return redirect(
        "workspace_folder",
        project_pk=project.pk,
        folder_pk=folder.pk,
    )
@login_required
@require_POST
def toggle_task(
    request,
    project_pk,
    task_pk,
):
    project = get_editable_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    task = get_object_or_404(
        Task,
        pk=task_pk,
        project=project,
    )

    task.completed = not task.completed

    if task.completed:
        task.status = Task.Status.DONE
        event_type = (
            ProjectEvent.EventType.TASK_COMPLETED
        )
        event_title = "Task completed"
    else:
        task.status = Task.Status.TODO
        event_type = (
            ProjectEvent.EventType.TASK_REOPENED
        )
        event_title = "Task reopened"

    task.save(
        update_fields=[
            "completed",
            "status",
            "updated_at",
        ]
    )

    mark_schedule_for_refresh(
        project=project,
        reason=(
            f"Completion state changed for "
            f"{task.title}."
        ),
    )

    record_project_event(
        project=project,
        event_type=event_type,
        title=event_title,
        description=task.title,
        metadata={
            "task_id": task.pk,
            "task_title": task.title,
            "status": task.status,
            "completed": task.completed,
        },
    )

    tasks_folder = get_object_or_404(
        WorkspaceFolder,
        project=project,
        folder_type="tasks",
    )

    return redirect(
        "workspace_folder",
        project_pk=project.pk,
        folder_pk=tasks_folder.pk,
    )
def normalize_task_priority(
    raw_priority,
    default=Task.Priority.MEDIUM,
):
    try:
        priority = int(raw_priority)
    except (TypeError, ValueError):
        return default

    valid_priorities = {
        value
        for value, _ in Task.Priority.choices
    }

    if priority not in valid_priorities:
        return default

    return priority
@login_required
def new_task(
    request,
    project_pk,
):
    project = get_editable_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    tasks_folder = get_object_or_404(
        WorkspaceFolder,
        project=project,
        folder_type="tasks",
    )

    if request.method == "POST":
        title = request.POST.get(
            "title",
            "",
        ).strip()

        description = request.POST.get(
            "description",
            "",
        ).strip()

        priority = normalize_task_priority(
            request.POST.get(
                "priority",
                Task.Priority.MEDIUM,
            )
        )

        if not title:
            messages.error(
                request,
                "Task title cannot be blank.",
            )
        else:
            last_task = (
                project.tasks
                .order_by("-order")
                .first()
            )

            next_order = (
                last_task.order + 1
                if last_task is not None
                else 1
            )

            task = Task.objects.create(
                project=project,
                title=title,
                description=description,
                priority=priority,
                status=Task.Status.TODO,
                completed=False,
                order=next_order,
            )

            mark_schedule_for_refresh(
                project=project,
                reason=(
                    f"Task added: {task.title}."
                ),
            )

            messages.success(
                request,
                f'Task "{task.title}" was created.',
            )

            return redirect(
                "workspace_folder",
                project_pk=project.pk,
                folder_pk=tasks_folder.pk,
            )

    permission_context = project_permission_context(
        project=project,
        user=request.user,
    )

    return render(
        request,
        "projects/task_form.html",
        {
            "project": project,
            "tasks_folder": tasks_folder,
            "priorities": Task.Priority.choices,
            **permission_context,
        },
    )
@login_required
def edit_task(
    request,
    project_pk,
    task_pk,
):
    project = get_editable_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    task = get_object_or_404(
        Task,
        pk=task_pk,
        project=project,
    )

    tasks_folder = get_object_or_404(
        WorkspaceFolder,
        project=project,
        folder_type="tasks",
    )

    if request.method == "POST":
        new_title = request.POST.get(
            "title",
            "",
        ).strip()

        new_description = request.POST.get(
            "description",
            "",
        ).strip()

        new_priority = normalize_task_priority(
            request.POST.get(
                "priority",
                task.priority,
            ),
            default=task.priority,
        )

        if not new_title:
            new_title = task.title

        changed = any(
            [
                task.title != new_title,
                (
                    task.description
                    != new_description
                ),
                task.priority != new_priority,
            ]
        )

        if changed:
            task.title = new_title
            task.description = new_description
            task.priority = new_priority

            task.save(
                update_fields=[
                    "title",
                    "description",
                    "priority",
                    "updated_at",
                ]
            )

            mark_schedule_for_refresh(
                project=project,
                reason=(
                    f"Task updated: {task.title}."
                ),
            )

            messages.success(
                request,
                f'Task "{task.title}" was updated.',
            )
        else:
            messages.info(
                request,
                "No task changes were made.",
            )

        return redirect(
            "workspace_folder",
            project_pk=project.pk,
            folder_pk=tasks_folder.pk,
        )

    permission_context = project_permission_context(
        project=project,
        user=request.user,
    )

    return render(
        request,
        "projects/edit_task.html",
        {
            "project": project,
            "task": task,
            "priorities": Task.Priority.choices,
            **permission_context,
        },
    )
@login_required
@require_POST
def delete_task(
    request,
    project_pk,
    task_pk,
):
    project = get_editable_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    task = get_object_or_404(
        Task,
        pk=task_pk,
        project=project,
    )

    tasks_folder = get_object_or_404(
        WorkspaceFolder,
        project=project,
        folder_type="tasks",
    )

    deleted_task_title = task.title

    task.delete()

    mark_schedule_for_refresh(
        project=project,
        reason=(
            f"Task deleted: "
            f"{deleted_task_title}"
        ),
    )

    messages.success(
        request,
        (
            f'Task "{deleted_task_title}" '
            "was deleted."
        ),
    )

    return redirect(
        "workspace_folder",
        project_pk=project.pk,
        folder_pk=tasks_folder.pk,
    )
def apply_task_synchronization(
    project,
    synchronization,
):
    added_count = 0
    updated_count = 0
    removed_count = 0

    valid_statuses = {
        value
        for value, _ in Task.Status.choices
    }

    existing_tasks = list(
        project.tasks.all()
    )

    tasks_by_id = {
        task.pk: task
        for task in existing_tasks
    }

    # Update existing tasks.
    for task_update in synchronization.tasks_to_update:
        task = tasks_by_id.get(
            task_update.task_id
        )

        if task is None:
            continue

        new_title = (
            task_update.new_title or ""
        ).strip()

        if not new_title:
            new_title = task.title

        new_description = (
            task_update.description or ""
        ).strip()

        new_priority = normalize_task_priority(
            task_update.priority,
            default=task.priority,
        )

        new_status = task_update.status

        if new_status not in valid_statuses:
            new_status = task.status

        new_completed = (
            new_status == Task.Status.DONE
        )

        changed = any(
            [
                task.title != new_title,
                task.description != new_description,
                task.priority != new_priority,
                task.status != new_status,
                task.completed != new_completed,
            ]
        )

        if not changed:
            continue

        task.title = new_title
        task.description = new_description
        task.priority = new_priority
        task.status = new_status
        task.completed = new_completed

        task.save(
            update_fields=[
                "title",
                "description",
                "priority",
                "status",
                "completed",
                "updated_at",
            ]
        )

        updated_count += 1

    # Remove only valid unfinished tasks.
    removal_ids = {
        task_id
        for task_id
        in synchronization.task_ids_to_remove
        if task_id in tasks_by_id
    }

    tasks_to_remove = (
        project.tasks.filter(
            completed=False,
            pk__in=removal_ids,
        )
    )

    removed_count = tasks_to_remove.count()

    if removed_count:
        tasks_to_remove.delete()

    # Reload tasks after updates and removals.
    remaining_tasks = list(
        project.tasks.all()
    )

    existing_titles = {
        task.title.strip().lower()
        for task in remaining_tasks
    }

    existing_task_words = [
        normalize_task_title(
            task.title
        )
        for task in remaining_tasks
    ]

    last_task = (
        project.tasks
        .order_by("-order")
        .first()
    )

    next_order = (
        last_task.order + 1
        if last_task is not None
        else 1
    )

    tasks_to_create = []

    # Add new non-duplicate tasks.
    for generated_task in synchronization.tasks_to_add:
        title = (
            generated_task.title or ""
        ).strip()

        if not title:
            continue

        normalized_title = title.lower()

        if normalized_title in existing_titles:
            continue

        new_title_words = (
            normalize_task_title(
                title
            )
        )

        is_similar = any(
            (
                len(
                    new_title_words
                    & existing_words
                )
                / max(
                    len(new_title_words),
                    1,
                )
            )
            >= 0.6
            for existing_words
            in existing_task_words
        )

        if is_similar:
            continue

        priority = normalize_task_priority(
            generated_task.priority
        )

        new_status = generated_task.status

        if new_status not in valid_statuses:
            new_status = Task.Status.TODO

        description = (
            generated_task.description or ""
        ).strip()

        tasks_to_create.append(
            Task(
                project=project,
                title=title,
                description=description,
                priority=priority,
                status=new_status,
                completed=(
                    new_status == Task.Status.DONE
                ),
                order=next_order,
            )
        )

        existing_titles.add(
            normalized_title
        )

        existing_task_words.append(
            new_title_words
        )

        next_order += 1

    if tasks_to_create:
        Task.objects.bulk_create(
            tasks_to_create
        )

        added_count = len(
            tasks_to_create
        )

    return {
        "added": added_count,
        "updated": updated_count,
        "removed": removed_count,
    }
def apply_workspace_change(
    *,
    project,
    content,
):
    update_started_at = time.monotonic()

    project_state, _ = (
        ProjectState.objects.get_or_create(
            project=project,
            defaults={
                "facts": {},
            },
        )
    )

    WorkspaceMessage.objects.create(
        project=project,
        role=WorkspaceMessage.Role.USER,
        content=content,
    )

    # One AI call handles:
    # - change analysis
    # - canonical fact updates
    # - section regeneration
    # - task synchronization
    plan = generate_workspace_update_plan(
        project
    )

    print(
        "\n===== Fast Workspace Update Plan ====="
    )
    print(
        plan.model_dump_json(
            indent=4
        )
    )
    print(
        "======================================\n"
    )

    facts_before = (
        project_state.facts.copy()
    )

    sections_before = {
        folder.folder_type:
            folder.description
        for folder
        in project.folders.all()
    }

    tasks_before = [
        {
            "id": task.pk,
            "title": task.title,
            "description": task.description,
            "priority": task.priority,
            "completed": task.completed,
            "order": task.order,
            "status": task.status,
        }
        for task
        in project.tasks.order_by("order")
    ]

    updated_facts = (
        project_state.facts.copy()
    )

    for fact_update in plan.canonical_updates:
        updated_facts[
            fact_update.key
        ] = fact_update.new_value

    regenerated_sections = {
        section.folder_type.strip().lower():
            section.content.strip()
        for section in plan.sections
        if section.content.strip()
    }

    tasks_affected = (
        "tasks"
        in plan.affected_sections
    )

    facts_changed = [
        fact_update.key
        for fact_update
        in plan.canonical_updates
    ]

    task_changes = {
        "added": 0,
        "updated": 0,
        "removed": 0,
    }

    updated_section_names = []
    section_summary = (
        "No text sections required changes"
    )

    with transaction.atomic():
        project_state.facts = (
            updated_facts
        )

        project_state.save(
            update_fields=[
                "facts",
                "updated_at",
            ]
        )

        folders_by_type = {
            folder.folder_type: folder
            for folder
            in project.folders.all()
        }

        folders_to_update = []

        for (
            section_type,
            new_content,
        ) in regenerated_sections.items():
            folder = folders_by_type.get(
                section_type
            )

            if folder is None:
                continue

            if (
                folder.description
                == new_content
            ):
                continue

            folder.description = (
                new_content
            )

            folders_to_update.append(
                folder
            )

            updated_section_names.append(
                folder.name
            )

        if folders_to_update:
            WorkspaceFolder.objects.bulk_update(
                folders_to_update,
                [
                    "description",
                ],
            )

        if updated_section_names:
            section_summary = ", ".join(
                updated_section_names
            )

        # WorkspaceUpdatePlan already has the same
        # task fields apply_task_synchronization()
        # expects:
        #
        # tasks_to_add
        # tasks_to_update
        # task_ids_to_remove
        if tasks_affected:
            task_changes = (
                apply_task_synchronization(
                    project=project,
                    synchronization=plan,
                )
            )

        task_note = ""

        if tasks_affected:
            task_note = (
                "\n\nTask synchronization:\n"
                f"- Added: "
                f"{task_changes['added']}\n"
                f"- Updated: "
                f"{task_changes['updated']}\n"
                f"- Removed: "
                f"{task_changes['removed']}"
            )

            if plan.task_summary.strip():
                task_note += (
                    "\n\n"
                    + plan.task_summary.strip()
                )

        sections_after = {
            folder.folder_type:
                folder.description
            for folder
            in project.folders.all()
        }

        tasks_after = [
            {
                "id": task.pk,
                "title": task.title,
                "description": (
                    task.description
                ),
                "priority": task.priority,
                "completed": (
                    task.completed
                ),
                "order": task.order,
                "status": task.status,
            }
            for task
            in project.tasks.order_by(
                "order"
            )
        ]

        change = (
            ProjectChange.objects.create(
                project=project,
                user_message=content,
                summary=plan.summary,
                facts_before=facts_before,
                facts_after=updated_facts,
                sections_before=(
                    sections_before
                ),
                sections_after=(
                    sections_after
                ),
                tasks_before=tasks_before,
                tasks_after=tasks_after,
            )
        )

        assistant_content = (
            plan.assistant_message.strip()
        )

        if plan.impact_explanation.strip():
            assistant_content += (
                "\n\nWhy this matters:\n"
                + (
                    plan
                    .impact_explanation
                    .strip()
                )
            )

        assistant_content += (
            "\n\nUpdated workspace sections: "
            f"{section_summary}."
            f"{task_note}"
        )

        WorkspaceMessage.objects.create(
            project=project,
            role=(
                WorkspaceMessage.Role
                .ASSISTANT
            ),
            content=assistant_content,
        )

        record_project_event(
            project=project,
            event_type=(
                ProjectEvent.EventType
                .WORKSPACE_UPDATED
            ),
            title="Workspace updated",
            description=(
                f"Updated sections: "
                f"{section_summary}. "
                f"Tasks added: "
                f"{task_changes['added']}; "
                f"updated: "
                f"{task_changes['updated']}; "
                f"removed: "
                f"{task_changes['removed']}."
            ),
            metadata={
                "change_id": change.pk,
                "sections": (
                    updated_section_names
                ),
                "facts_changed": (
                    facts_changed
                ),
                "task_changes": (
                    task_changes
                ),
            },
        )

    schedule_relevant_sections = {
        "requirements",
        "roadmap",
        "tasks",
        "resources",
        "budget",
        "testing",
    }

    affected_schedule_sections = (
        schedule_relevant_sections
        & set(plan.affected_sections)
    )

    tasks_changed = any(
        task_changes[key] > 0
        for key in [
            "added",
            "updated",
            "removed",
        ]
    )

    if (
        affected_schedule_sections
        or tasks_changed
    ):
        refresh_reasons = []

        if affected_schedule_sections:
            refresh_reasons.append(
                "Updated sections: "
                + ", ".join(
                    sorted(
                        affected_schedule_sections
                    )
                )
                + "."
            )

        if tasks_changed:
            refresh_reasons.append(
                "The task list changed."
            )

        mark_schedule_for_refresh(
            project=project,
            reason=" ".join(
                refresh_reasons
            ),
        )

    total_seconds = (
        time.monotonic()
        - update_started_at
    )

    print(
        "\n===== Fast Update Complete ====="
    )
    print(
        "Updated facts:",
        updated_facts,
    )
    print(
        "Updated sections:",
        updated_section_names,
    )
    print(
        "Task changes:",
        task_changes,
    )
    print(
        "TOTAL WORKSPACE ASSISTANT "
        f"UPDATE TIME: {total_seconds:.2f} "
        "seconds"
    )
    print(
        "================================\n"
    )

    return {
        "analysis": plan,
        "change": change,
        "updated_facts": (
            updated_facts
        ),
        "sections": (
            updated_section_names
        ),
        "task_changes": task_changes,
        "facts_changed": (
            facts_changed
        ),
    }
@login_required
def workspace_assistant(
    request,
    project_pk,
):
    if request.method == "POST":
        project = get_editable_project_for_user(
            project_pk=project_pk,
            user=request.user,
        )
    else:
        project = get_project_for_user(
            project_pk=project_pk,
            user=request.user,
        )

    ProjectState.objects.get_or_create(
        project=project,
        defaults={
            "facts": {},
        },
    )

    if request.method == "POST":
        content = request.POST.get(
            "message",
            "",
        ).strip()

        if not content:
            messages.error(
                request,
                "Enter a project update first.",
            )

            return redirect(
                "workspace_assistant",
                project_pk=project.pk,
            )

        try:
            previous_review = (
                project.health_reviews
                .order_by("-created_at")
                .first()
            )

            previous_health_score = (
                previous_review.health_score
                if previous_review is not None
                else None
            )

            previous_open_conflicts = (
                project.conflicts.filter(
                    status=ProjectConflict.Status.OPEN,
                ).count()
            )

            result = apply_workspace_change(
                project=project,
                content=content,
            )

            messages.success(
                request,
                (
                    "Your project was updated "
                    "successfully."
                ),
            )

            # Do not automatically run a full AI review.
            # The user can run one manually from the
            # Review page.
            latest_health_score = (
                previous_health_score
            )

            latest_open_conflicts = (
                previous_open_conflicts
            )

            health_score_change = None
            conflict_count_change = 0

            request.session[
                "workspace_update_summary"
            ] = {
                "sections": result["sections"],
                "task_changes": (
                    result["task_changes"]
                ),
                "facts_changed": (
                    result["facts_changed"]
                ),
                "previous_health_score": (
                    previous_health_score
                ),
                "health_score": (
                    latest_health_score
                ),
                "health_score_change": (
                    health_score_change
                ),
                "previous_open_conflicts": (
                    previous_open_conflicts
                ),
                "open_conflicts": (
                    latest_open_conflicts
                ),
                "conflict_count_change": (
                    conflict_count_change
                ),
                "review_completed": False,
            }

        except Exception:
            print("\n" + "=" * 80)
            print(
                "WORKSPACE ASSISTANT UPDATE FAILED"
            )
            traceback.print_exc()
            print("=" * 80 + "\n")

            WorkspaceMessage.objects.create(
                project=project,
                role=(
                    WorkspaceMessage.Role.ASSISTANT
                ),
                content=(
                    "I couldn't apply that project "
                    "change. No workspace sections "
                    "were updated. Please try again."
                ),
            )

            messages.error(
                request,
                (
                    "BuilderOS could not apply "
                    "that project update."
                ),
            )

        return redirect(
            "workspace_assistant",
            project_pk=project.pk,
        )

    workspace_messages = (
        project.workspace_messages.all()
    )

    update_summary = request.session.pop(
        "workspace_update_summary",
        None,
    )

    permission_context = (
        project_permission_context(
            project=project,
            user=request.user,
        )
    )

    return render(
        request,
        "projects/workspace_assistant.html",
        {
            "project": project,
            "messages": workspace_messages,
            "update_summary": update_summary,
            **permission_context,
        },
    )
@login_required
def project_change_history(
    request,
    project_pk,
):
    project = get_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    changes = project.changes.order_by(
        "-created_at"
    )

    permission_context = project_permission_context(
        project=project,
        user=request.user,
    )

    return render(
        request,
        "projects/project_change_history.html",
        {
            "project": project,
            "changes": changes,
            **permission_context,
        },
    )
@login_required
def project_change_detail(request, project_pk, change_pk):
    project = get_editable_project_for_user(
        project_pk=project_pk,
        user=request.user,
)

    change = get_object_or_404(
        ProjectChange,
        pk=change_pk,
        project=project,
    )

    facts_before = change.facts_before or {}
    facts_after = change.facts_after or {}

    fact_keys = sorted(
        set(facts_before.keys()) | set(facts_after.keys())
    )

    fact_changes = []

    for key in fact_keys:
        before_value = facts_before.get(key)
        after_value = facts_after.get(key)

        if before_value == after_value:
            continue

        if key not in facts_before:
            change_type = "added"
        elif key not in facts_after:
            change_type = "removed"
        else:
            change_type = "updated"

        fact_changes.append(
            {
                "key": key,
                "before": before_value,
                "after": after_value,
                "change_type": change_type,
            }
        )

    sections_before = change.sections_before or {}
    sections_after = change.sections_after or {}

    section_keys = sorted(
        set(sections_before.keys()) | set(sections_after.keys())
    )

    section_changes = []

    for section_type in section_keys:
        before_content = sections_before.get(section_type, "")
        after_content = sections_after.get(section_type, "")

        if before_content == after_content:
            continue

        if section_type not in sections_before:
            change_type = "added"
        elif section_type not in sections_after:
            change_type = "removed"
        else:
            change_type = "updated"

        section_changes.append(
            {
                "section_type": section_type,
                "before": before_content,
                "after": after_content,
                "change_type": change_type,
                "diff_lines": build_text_diff(
                    before_content,
                    after_content,
                ),
            }
        )
    tasks_before = change.tasks_before or []
    tasks_after = change.tasks_after or []

    before_tasks_by_title = {
        task_snapshot_key(task): task
        for task in tasks_before
    }

    after_tasks_by_title = {
        task_snapshot_key(task): task
        for task in tasks_after
    }

    task_keys = sorted(
        set(before_tasks_by_title.keys())
        | set(after_tasks_by_title.keys())
    )

    task_changes = []

    for task_key in task_keys:
        before_task = before_tasks_by_title.get(task_key)
        after_task = after_tasks_by_title.get(task_key)

        if before_task == after_task:
            continue

        if before_task is None:
            change_type = "added"
        elif after_task is None:
            change_type = "removed"
        else:
            change_type = "updated"

        task_changes.append(
            {
                "title": (
                    after_task.get("title")
                    if after_task
                    else before_task.get("title")
                ),
                "before": before_task,
                "after": after_task,
                "change_type": change_type,
            }
        )
        permission_context = project_permission_context(
            project=project,
            user=request.user,
        )

    return render(
        request,
        "projects/project_change_detail.html",
        {
            "project": project,
            "change": change,
            "fact_changes": fact_changes,
            "section_changes": section_changes,
            "task_changes": task_changes,
            **permission_context,
        },
    )

@login_required
@require_POST
def undo_project_change(
    request,
    project_pk,
    change_pk,
):
    project = get_editable_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    change = get_object_or_404(
        ProjectChange,
        pk=change_pk,
        project=project,
    )

    try:
        with transaction.atomic():
            project_state, _ = (
                ProjectState.objects
                .get_or_create(
                    project=project,
                    defaults={
                        "facts": {},
                    },
                )
            )

            project_state.facts = (
                change.facts_before or {}
            )

            project_state.save(
                update_fields=[
                    "facts",
                    "updated_at",
                ]
            )

            sections_before = (
                change.sections_before or {}
            )

            for folder in project.folders.all():
                if (
                    folder.folder_type
                    not in sections_before
                ):
                    continue

                folder.description = (
                    sections_before[
                        folder.folder_type
                    ]
                )

                folder.save(
                    update_fields=[
                        "description",
                        "updated_at",
                    ]
                )

            project.tasks.all().delete()

            restored_tasks = []

            valid_statuses = {
                value
                for value, _
                in Task.Status.choices
            }

            for task_data in (
                change.tasks_before or []
            ):
                title = (
                    task_data
                    .get("title", "")
                    .strip()
                )

                if not title:
                    continue

                priority = normalize_task_priority(
                    task_data.get(
                        "priority",
                        Task.Priority.MEDIUM,
                    )
                )

                saved_status = task_data.get(
                    "status",
                    Task.Status.TODO,
                )

                if (
                    saved_status
                    not in valid_statuses
                ):
                    saved_status = (
                        Task.Status.DONE
                        if task_data.get(
                            "completed",
                            False,
                        )
                        else Task.Status.TODO
                    )

                restored_tasks.append(
                    Task(
                        project=project,
                        title=title,
                        description=(
                            task_data.get(
                                "description",
                                "",
                            )
                        ),
                        priority=priority,
                        status=saved_status,
                        completed=(
                            saved_status
                            == Task.Status.DONE
                        ),
                        order=task_data.get(
                            "order",
                            0,
                        ),
                    )
                )

            if restored_tasks:
                Task.objects.bulk_create(
                    restored_tasks
                )

            WorkspaceMessage.objects.create(
                project=project,
                role=(
                    WorkspaceMessage.Role
                    .ASSISTANT
                ),
                content=(
                    f"Undid change "
                    f"#{change.pk}: "
                    f"{change.summary or change.user_message}"
                ),
            )

            record_project_event(
                project=project,
                event_type=(
                    ProjectEvent.EventType
                    .CHANGE_UNDONE
                ),
                title=(
                    "Project change undone"
                ),
                description=(
                    change.summary
                    or change.user_message
                ),
                metadata={
                    "change_id": change.pk,
                },
            )

        mark_schedule_for_refresh(
            project=project,
            reason=(
                f"Project change "
                f"#{change.pk} was undone."
            ),
        )
        messages.success(
            request,
            f"Change #{change.pk} was undone.",
        )

        print(
            f"Undid ProjectChange "
            f"#{change.pk}"
        )

    except Exception as error:
        print(
            f"Failed to undo "
            f"ProjectChange #{change.pk}:",
            error,
        )
        messages.error(
            request,
            f"Change #{change.pk} could not be undone.",
        )

    return redirect(
        "project_change_history",
        project_pk=project.pk,
    )
def build_review_delta(
    latest_review,
    previous_review,
):
    if latest_review is None:
        return None

    latest_critical = set(
        latest_review.critical_issues or []
    )

    latest_warnings = set(
        latest_review.warnings or []
    )

    if previous_review is None:
        return {
            "has_previous_review": False,
            "health_change": None,
            "new_critical_issues": sorted(
                latest_critical
            ),
            "resolved_critical_issues": [],
            "new_warnings": sorted(
                latest_warnings
            ),
            "resolved_warnings": [],
        }

    previous_critical = set(
        previous_review.critical_issues or []
    )

    previous_warnings = set(
        previous_review.warnings or []
    )

    return {
        "has_previous_review": True,

        "health_change": (
            latest_review.health_score
            - previous_review.health_score
        ),

        "new_critical_issues": sorted(
            latest_critical
            - previous_critical
        ),

        "resolved_critical_issues": sorted(
            previous_critical
            - latest_critical
        ),

        "new_warnings": sorted(
            latest_warnings
            - previous_warnings
        ),

        "resolved_warnings": sorted(
            previous_warnings
            - latest_warnings
        ),
    }
def canonicalize_conflict_key(finding):
    raw_key = (finding.key or "").strip().lower()

    combined_text = " ".join(
        [
            raw_key,
            finding.title or "",
            finding.description or "",
            finding.source_type or "",
            finding.source_reference or "",
        ]
    ).lower()

    canonical_rules = [
        (
            "g0_portability_unresolved",
            [
                "g0 portability",
                "portability g0",
                "portability definition",
                "portability mode",
                "portability scope",
                "portability_scope.md",
                "mains-portable vs battery",
                "battery-operated vs mains-portable",
            ],
        ),
        (
            "missing_task_owner_confirmations",
            [
                "ownerconfirmed",
                "owner confirmation",
                "owner confirmations",
                "provisional owners",
                "missing task owners",
                "lack confirmed owners",
                "lack assigned owners",
                "tasks lack named owners",
                "tasks lack confirmed owners",
                "no assigned owners",
            ],
        ),
        (
            "heater_scope_conflict",
            [
                "heater scope",
                "heater artifact",
                "heater artifacts",
                "heated-plate",
                "heated plate",
                "heating plate",
                "heater-related",
                "cold-only sandwich",
                "cold assembly only",
            ],
        ),
        (
            "dfm_workshop_incomplete",
            [
                "dfm workshop",
                "task 149",
                "dfm cost-reduction",
                "target-bom roadmap",
                "dfm outputs",
                "dfm deliverables",
            ],
        ),
        (
            "retail_price_infeasible",
            [
                "<$100 retail",
                "under $100 retail",
                "$100 retail",
                "retail target",
                "retail viability",
                "budget_retail_viability",
                "retail price target",
            ],
        ),
        (
            "thermal_feasibility_unvalidated",
            [
                "thermal feasibility",
                "10 minute cycle",
                "≤10 minute",
                "3 l hard",
                "3.0 l of hard",
                "heat-extraction",
                "transient thermal",
                "portable power limits",
            ],
        ),
        (
            "compliance_outputs_incomplete",
            [
                "compliance scoping",
                "compliance_actions.md",
                "compliance call",
                "test plan items",
                "certification impact",
            ],
        ),
        (
            "task_tracker_qa_incomplete",
            [
                "pre-publication qa",
                "peer-review signoff",
                "peer review signoff",
                "task tracker gating",
                "task_tracker_kanban",
                "clean-scan",
                "clean scan",
            ],
        ),
        (
            "invalid_task_content",
            [
                "eat children",
                "offensive task",
                "inappropriate task",
                "invalid checklist",
                "malicious task",
                "objectionable",
            ],
        ),
        (
            "sandwich_scope_unvalidated",
            [
                "sandwich feature",
                "sandwich-making",
                "sandwich fixture",
                "scope creep",
                "original user needs",
                "original discovery",
            ],
        ),
        (
            "task_id_conflict",
            [
                "task id conflict",
                "conflicting assignment/use of task id",
                "conflicting task id",
                "mismatch of task id usage",
                "same task id",
            ],
        ),
    ]

    for canonical_key, phrases in canonical_rules:
        if any(
            phrase in combined_text
            for phrase in phrases
        ):
            return canonical_key

    normalized_key = (
        raw_key
        .replace("-", "_")
        .replace(" ", "_")
    )

    while "__" in normalized_key:
        normalized_key = normalized_key.replace(
            "__",
            "_",
        )

    normalized_key = normalized_key.strip("_")

    if not normalized_key:
        raise ValueError(
            "Project health finding returned no usable key."
        )

    return normalized_key
def run_project_review(project):
    review = review_project(project)

    current_critical_issues = [
        finding
        for finding in review.findings
        if finding.severity == "critical"
    ]

    current_warnings = [
        finding
        for finding in review.findings
        if finding.severity == "warning"
    ]

    with transaction.atomic():
        saved_review = ProjectHealthReviewRecord.objects.create(
            project=project,
            health_score=review.health_score,
            critical_issues=[
                finding.description
                for finding in current_critical_issues
            ],
            warnings=[
                finding.description
                for finding in current_warnings
            ],
            strengths=review.strengths,
            summary=review.summary,
        )

        processed_keys = set()

        for finding in review.findings:
            conflict_key = canonicalize_conflict_key(
                finding
            )

            if conflict_key in processed_keys:
                print(
                    "Skipped duplicate review finding:",
                    conflict_key,
                )
                continue

            processed_keys.add(conflict_key)

            existing_conflict = (
                ProjectConflict.objects.filter(
                    project=project,
                    key=conflict_key,
                    status=ProjectConflict.Status.OPEN,
                )
                .order_by("-created_at")
                .first()
            )

            if existing_conflict:
                existing_conflict.review = saved_review
                existing_conflict.title = finding.title
                existing_conflict.description = (
                    finding.description
                )
                existing_conflict.severity = (
                    finding.severity
                )
                existing_conflict.source_type = (
                    finding.source_type
                )
                existing_conflict.source_reference = (
                    finding.source_reference
                )
                existing_conflict.suggested_fix = (
                    finding.suggested_fix
                )

                existing_conflict.save(
                    update_fields=[
                        "review",
                        "title",
                        "description",
                        "severity",
                        "source_type",
                        "source_reference",
                        "suggested_fix",
                    ]
                )

            else:
                ProjectConflict.objects.create(
                    project=project,
                    review=saved_review,
                    key=conflict_key,
                    title=finding.title,
                    description=finding.description,
                    severity=finding.severity,
                    source_type=finding.source_type,
                    source_reference=(
                        finding.source_reference
                    ),
                    suggested_fix=finding.suggested_fix,
                )

    open_conflict_count = project.conflicts.filter(
        status=ProjectConflict.Status.OPEN,
    ).count()

    record_project_event(
        project=project,
        event_type=(
            ProjectEvent.EventType.PROJECT_REVIEWED
        ),
        title="Project reviewed",
        description=(
            f"Project health scored "
            f"{review.health_score}% with "
            f"{open_conflict_count} open conflicts."
        ),
        metadata={
            "review_id": saved_review.pk,
            "health_score": review.health_score,
            "critical_issue_count": len(
                current_critical_issues
            ),
            "warning_count": len(
                current_warnings
            ),
            "open_conflict_count": (
                open_conflict_count
            ),
        },
    )

    print("\n===== Project Health Review =====")
    print(review.model_dump_json(indent=4))
    print("=================================\n")

    return {
        "review": review,
        "saved_review": saved_review,
        "critical_issues": current_critical_issues,
        "warnings": current_warnings,
    }
@login_required
def project_review(
    request,
    project_pk,
):
    if request.method == "POST":
        project = get_editable_project_for_user(
            project_pk=project_pk,
            user=request.user,
        )
    else:
        project = get_project_for_user(
            project_pk=project_pk,
            user=request.user,
        )

    review = None
    current_critical_issues = []
    current_warnings = []
    error_message = ""

    if request.method == "POST":
        try:
            result = run_project_review(
                project
            )

            review = result["review"]
            current_critical_issues = (
                result["critical_issues"]
            )
            current_warnings = (
                result["warnings"]
            )

            messages.success(
                request,
                (
                    "Project review completed. "
                    f"Health score: "
                    f"{review.health_score}%."
                ),
            )

        except Exception as error:
            print(
                "Project health review failed:",
                error,
            )

            messages.error(
                request,
                (
                    "BuilderOS could not complete "
                    "the project review."
                ),
            )

    previous_reviews = (
        project.health_reviews
        .order_by("-created_at")
    )

    health_history = list(
        project.health_reviews
        .order_by("created_at")
    )

    latest_saved_review = (
        health_history[-1]
        if health_history
        else None
    )

    previous_saved_review = (
        health_history[-2]
        if len(health_history) >= 2
        else None
    )

    review_delta = build_review_delta(
        latest_review=latest_saved_review,
        previous_review=previous_saved_review,
    )

    latest_saved_score = (
        latest_saved_review.health_score
        if latest_saved_review is not None
        else None
    )

    previous_saved_score = (
        previous_saved_review.health_score
        if previous_saved_review is not None
        else None
    )

    health_change = None

    if (
        latest_saved_score is not None
        and previous_saved_score is not None
    ):
        health_change = (
            latest_saved_score
            - previous_saved_score
        )

    if health_change is None:
        health_trend = "unknown"
    elif health_change > 0:
        health_trend = "improving"
    elif health_change < 0:
        health_trend = "declining"
    else:
        health_trend = "unchanged"

    open_conflicts = (
        project.conflicts.filter(
            status=ProjectConflict.Status.OPEN,
        )
    )

    permission_context = project_permission_context(
        project=project,
        user=request.user,
    )

    return render(
        request,
        "projects/project_review.html",
        {
            "project": project,
            "review": review,
            "current_critical_issues": (
                current_critical_issues
            ),
            "current_warnings": (
                current_warnings
            ),
            "error_message": error_message,
            "previous_reviews": previous_reviews,
            "open_conflicts": open_conflicts,
            "health_history": health_history,
            "latest_saved_score": (
                latest_saved_score
            ),
            "previous_saved_score": (
                previous_saved_score
            ),
            "health_change": health_change,
            "health_trend": health_trend,
            "review_delta": review_delta,
            **permission_context,
        },
    )
@login_required
@require_POST
def resolve_project_conflict(
    request,
    project_pk,
    conflict_pk,
):
    project = get_editable_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    conflict = get_object_or_404(
        ProjectConflict,
        pk=conflict_pk,
        project=project,
    )

    conflict.status = (
        ProjectConflict.Status.RESOLVED
    )
    conflict.resolved_at = timezone.now()

    conflict.save(
        update_fields=[
            "status",
            "resolved_at",
        ]
    )

    record_project_event(
        project=project,
        event_type=(
            ProjectEvent.EventType
            .CONFLICT_RESOLVED
        ),
        title="Conflict resolved",
        description=conflict.title,
        metadata={
            "conflict_id": conflict.pk,
        },
    )

    messages.success(
        request,
        (
            f'Conflict "{conflict.title}" '
            "was marked resolved."
        ),
    )

    return redirect(
        "project_review",
        project_pk=project.pk,
    )
@login_required
@require_POST
def ignore_project_conflict(
    request,
    project_pk,
    conflict_pk,
):
    project = get_editable_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    conflict = get_object_or_404(
        ProjectConflict,
        pk=conflict_pk,
        project=project,
    )

    conflict.status = (
        ProjectConflict.Status.IGNORED
    )
    conflict.resolved_at = timezone.now()

    conflict.save(
        update_fields=[
            "status",
            "resolved_at",
        ]
    )

    record_project_event(
        project=project,
        event_type=(
            ProjectEvent.EventType
            .CONFLICT_IGNORED
        ),
        title="Conflict ignored",
        description=conflict.title,
        metadata={
            "conflict_id": conflict.pk,
        },
    )

    messages.warning(
        request,
        (
            f'Conflict "{conflict.title}" '
            "was ignored."
        ),
    )

    return redirect(
        "project_review",
        project_pk=project.pk,
    )
@login_required
@require_POST
def apply_project_conflict_fix(
    request,
    project_pk,
    conflict_pk,
):
    project = get_editable_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    conflict = get_object_or_404(
        ProjectConflict,
        pk=conflict_pk,
        project=project,
        status=ProjectConflict.Status.OPEN,
    )

    fix_request = (
        "Apply the following project-health "
        "conflict fix.\n\n"
        f"Conflict key: {conflict.key}\n"
        f"Conflict title: {conflict.title}\n"
        f"Problem: {conflict.description}\n"
        f"Source type: {conflict.source_type}\n"
        f"Source reference: "
        f"{conflict.source_reference}\n\n"
        f"Requested fix:\n"
        f"{conflict.suggested_fix}\n\n"
        "Update only the project facts, workspace "
        "sections, and tasks that are meaningfully "
        "affected. Preserve unrelated content."
    )

    try:
        result = apply_workspace_change(
            project=project,
            content=fix_request,
        )
        latest_review = (
            project.health_reviews
            .order_by("-created_at")
            .first()
        )

        latest_health_score = (
            latest_review.health_score
            if latest_review is not None
            else None
        )

        remaining_conflict = (
            ProjectConflict.objects.filter(
                project=project,
                key=conflict.key,
                status=(
                    ProjectConflict.Status.OPEN
                ),
            )
            .exclude(pk=conflict.pk)
            .exists()
        )

        if not remaining_conflict:
            conflict.status = (
                ProjectConflict.Status.RESOLVED
            )
            conflict.resolved_at = (
                timezone.now()
            )

            conflict.save(
                update_fields=[
                    "status",
                    "resolved_at",
                ]
            )

            record_project_event(
                project=project,
                event_type=(
                    ProjectEvent.EventType
                    .CONFLICT_FIXED
                ),
                title="AI conflict fix applied",
                description=conflict.title,
                metadata={
                    "conflict_id": conflict.pk,
                    "conflict_key": conflict.key,
                    "health_score": (
                        latest_health_score
                    ),
                    "sections": (
                        result["sections"]
                    ),
                    "task_changes": (
                        result["task_changes"]
                    ),
                },
            )

            messages.success(
                request,
                (
                    f'AI fix applied for '
                    f'"{conflict.title}".'
                ),
            )
        else:
            messages.warning(
                request,
                (
                    "The AI update was applied, "
                    "but the conflict is still "
                    "present."
                ),
            )

        request.session[
            "workspace_update_summary"
        ] = {
            "sections": result["sections"],
            "task_changes": (
                result["task_changes"]
            ),
            "facts_changed": (
                result["facts_changed"]
            ),
            "health_score": (
                latest_health_score
            ),
        }

        return redirect(
            "workspace_assistant",
            project_pk=project.pk,
        )

    except Exception as error:
        print(
            (
                f"Failed to apply conflict "
                f"#{conflict.pk}:"
            ),
            error,
        )

        messages.error(
            request,
            (
                "BuilderOS could not apply the "
                "AI conflict fix."
            ),
        )

        return redirect(
            "project_review",
            project_pk=project.pk,
        )
@login_required
def project_activity(
    request,
    project_pk,
):
    project = get_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    events = project.events.all()

    permission_context = project_permission_context(
        project=project,
        user=request.user,
    )

    return render(
        request,
        "projects/project_activity.html",
        {
            "project": project,
            "events": events,
            **permission_context,
        },
    )
@login_required
def project_board(
    request,
    project_pk,
):
    project = get_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    todo_tasks = project.tasks.filter(
        status=Task.Status.TODO,
    ).order_by(
        "order",
        "-priority",
    )

    in_progress_tasks = project.tasks.filter(
        status=Task.Status.IN_PROGRESS,
    ).order_by(
        "order",
        "-priority",
    )

    review_tasks = project.tasks.filter(
        status=Task.Status.REVIEW,
    ).order_by(
        "order",
        "-priority",
    )

    done_tasks = project.tasks.filter(
        status=Task.Status.DONE,
    ).order_by(
        "order",
        "-priority",
    )

    permission_context = project_permission_context(
        project=project,
        user=request.user,
    )

    return render(
        request,
        "projects/project_board.html",
        {
            "project": project,
            "todo_tasks": todo_tasks,
            "in_progress_tasks": (
                in_progress_tasks
            ),
            "review_tasks": review_tasks,
            "done_tasks": done_tasks,
            "status_choices": Task.Status.choices,
            **permission_context,
        },
    )
@login_required
@require_POST
def update_task_status(
    request,
    project_pk,
    task_pk,
):
    project = get_editable_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    task = get_object_or_404(
        Task,
        pk=task_pk,
        project=project,
    )

    new_status = request.POST.get(
        "status",
        "",
    ).strip()

    valid_statuses = {
        value
        for value, _ in Task.Status.choices
    }

    if new_status not in valid_statuses:
        return redirect(
            "project_board",
            project_pk=project.pk,
        )

    previous_status = task.status

    if previous_status == new_status:
        return redirect(
            "project_board",
            project_pk=project.pk,
        )

    task.status = new_status
    task.completed = (
        new_status == Task.Status.DONE
    )

    task.save(
        update_fields=[
            "status",
            "completed",
            "updated_at",
        ]
    )

    if (
        previous_status == Task.Status.DONE
        or new_status == Task.Status.DONE
    ):
        mark_schedule_for_refresh(
            project=project,
            reason=(
                f"Completion state changed for "
                f"{task.title}."
            ),
        )

    status_labels = dict(
        Task.Status.choices
    )

    record_project_event(
        project=project,
        event_type=(
            ProjectEvent.EventType
            .TASK_STATUS_CHANGED
        ),
        title="Task status changed",
        description=(
            f"{task.title}: "
            f"{status_labels[previous_status]} "
            f"→ {status_labels[new_status]}"
        ),
        metadata={
            "task_id": task.pk,
            "task_title": task.title,
            "previous_status": (
                previous_status
            ),
            "new_status": new_status,
        },
    )

    return redirect(
        "project_board",
        project_pk=project.pk,
    )
@login_required
@require_POST
def move_task_on_board(
    request,
    project_pk,
    task_pk,
):
    project = get_editable_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    task = get_object_or_404(
        Task,
        pk=task_pk,
        project=project,
    )

    try:
        payload = json.loads(
            request.body.decode("utf-8")
        )

    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):
        return JsonResponse(
            {
                "success": False,
                "error": (
                    "Invalid JSON request."
                ),
            },
            status=400,
        )

    new_status = str(
        payload.get(
            "status",
            "",
        )
    ).strip()

    ordered_task_ids = payload.get(
        "ordered_task_ids",
        [],
    )

    valid_statuses = {
        value
        for value, _ in Task.Status.choices
    }

    if new_status not in valid_statuses:
        return JsonResponse(
            {
                "success": False,
                "error": (
                    "Invalid task status."
                ),
            },
            status=400,
        )

    try:
        ordered_task_ids = [
            int(task_id)
            for task_id in ordered_task_ids
        ]

    except (TypeError, ValueError):
        return JsonResponse(
            {
                "success": False,
                "error": (
                    "Invalid task ordering."
                ),
            },
            status=400,
        )

    previous_status = task.status

    with transaction.atomic():
        task.status = new_status
        task.completed = (
            new_status == Task.Status.DONE
        )

        task.save(
            update_fields=[
                "status",
                "completed",
                "updated_at",
            ]
        )

        destination_tasks = {
            existing_task.pk: existing_task
            for existing_task
            in project.tasks.filter(
                status=new_status,
                pk__in=ordered_task_ids,
            )
        }

        tasks_to_update = []

        for order, ordered_task_id in enumerate(
            ordered_task_ids,
            start=1,
        ):
            ordered_task = (
                destination_tasks.get(
                    ordered_task_id
                )
            )

            if ordered_task is None:
                continue

            if ordered_task.order != order:
                ordered_task.order = order
                tasks_to_update.append(
                    ordered_task
                )

        if tasks_to_update:
            Task.objects.bulk_update(
                tasks_to_update,
                ["order"],
            )

        if (
            previous_status == Task.Status.DONE
            or new_status == Task.Status.DONE
        ):
            mark_schedule_for_refresh(
                project=project,
                reason=(
                    f"Completion state changed "
                    f"for {task.title}."
                ),
            )

        if previous_status != new_status:
            status_labels = dict(
                Task.Status.choices
            )

            record_project_event(
                project=project,
                event_type=(
                    ProjectEvent.EventType
                    .TASK_STATUS_CHANGED
                ),
                title="Task status changed",
                description=(
                    f"{task.title}: "
                    f"{status_labels[previous_status]} "
                    f"→ "
                    f"{status_labels[new_status]}"
                ),
                metadata={
                    "task_id": task.pk,
                    "task_title": task.title,
                    "previous_status": (
                        previous_status
                    ),
                    "new_status": new_status,
                },
            )

    return JsonResponse(
        {
            "success": True,
            "task_id": task.pk,
            "status": task.status,
            "completed": task.completed,
        }
    )
@login_required
def project_timeline(
    request,
    project_pk,
):
    project = get_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    milestones = (
        project.milestones
        .prefetch_related(
            "tasks",
            "tasks__dependencies",
            "tasks__dependents",
        )
        .order_by(
            "order",
            "target_date",
            "created_at",
        )
    )

    unscheduled_tasks = (
        project.tasks
        .filter(
            milestone__isnull=True
        )
        .prefetch_related(
            "dependencies",
            "dependents",
        )
        .order_by(
            "start_date",
            "due_date",
            "order",
        )
    )

    all_tasks = list(
        project.tasks
        .prefetch_related(
            "dependencies",
            "dependents",
        )
    )

    blocked_tasks = [
        task
        for task in all_tasks
        if task.is_blocked
    ]

    overdue_tasks = [
        task
        for task in all_tasks
        if task.is_overdue
    ]

    schedule_message = (
        request.session.pop(
            "schedule_message",
            None,
        )
    )

    schedule_message_type = (
        request.session.pop(
            "schedule_message_type",
            None,
        )
    )
    permission_context = project_permission_context(
        project=project,
        user=request.user,
    )

    return render(
        request,
        "projects/project_timeline.html",
        {
            "project": project,
            "milestones": milestones,
            "unscheduled_tasks": unscheduled_tasks,
            "blocked_tasks": blocked_tasks,
            "overdue_tasks": overdue_tasks,
            "schedule_message": schedule_message,
            "schedule_message_type": (
                schedule_message_type
            ),
            **permission_context,
        },
    )
def task_depends_on(
    *,
    task,
    possible_dependency,
    visited=None,
):
    if visited is None:
        visited = set()

    if task.pk in visited:
        return False

    visited.add(task.pk)

    direct_dependencies = task.dependencies.all()

    for dependency in direct_dependencies:
        if dependency.pk == possible_dependency.pk:
            return True

        if task_depends_on(
            task=dependency,
            possible_dependency=possible_dependency,
            visited=visited,
        ):
            return True

    return False
@login_required
def edit_task_dependencies(
    request,
    project_pk,
    task_pk,
):
    project = get_editable_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    task = get_object_or_404(
        Task,
        pk=task_pk,
        project=project,
    )

    available_tasks = (
        project.tasks
        .exclude(pk=task.pk)
        .order_by("order", "title")
    )

    error_message = ""

    if request.method == "POST":
        dependency_ids = (
            request.POST.getlist(
                "dependencies"
            )
        )

        selected_dependencies = list(
            project.tasks
            .filter(pk__in=dependency_ids)
            .exclude(pk=task.pk)
        )

        invalid_dependencies = []

        for dependency in selected_dependencies:
            if task_depends_on(
                task=dependency,
                possible_dependency=task,
            ):
                invalid_dependencies.append(
                    dependency.title
                )

        if invalid_dependencies:
            error_message = (
                "These dependencies would create "
                "a circular dependency: "
                + ", ".join(
                    invalid_dependencies
                )
            )
        else:
            previous_dependency_ids = set(
                task.dependencies.values_list(
                    "pk",
                    flat=True,
                )
            )

            new_dependency_ids = {
                dependency.pk
                for dependency
                in selected_dependencies
            }

            if (
                previous_dependency_ids
                != new_dependency_ids
            ):
                task.dependencies.set(
                    selected_dependencies
                )

                mark_schedule_for_refresh(
                    project=project,
                    reason=(
                        f"Dependencies changed "
                        f"for {task.title}."
                    ),
                )

                record_project_event(
                    project=project,
                    event_type=(
                        ProjectEvent.EventType
                        .TASK_DEPENDENCIES_CHANGED
                    ),
                    title=(
                        "Task dependencies changed"
                    ),
                    description=task.title,
                    metadata={
                        "task_id": task.pk,
                        (
                            "previous_"
                            "dependency_ids"
                        ): sorted(
                            previous_dependency_ids
                        ),
                        (
                            "new_dependency_ids"
                        ): sorted(
                            new_dependency_ids
                        ),
                    },
                )

                messages.success(
                    request,
                    (
                        f'Dependencies for '
                        f'"{task.title}" '
                        "were updated."
                    ),
                )
            else:
                messages.info(
                    request,
                    (
                        "No dependency changes "
                        "were made."
                    ),
                )

            return redirect(
                "project_timeline",
                project_pk=project.pk,
            )

    selected_dependency_ids = set(
        task.dependencies.values_list(
            "pk",
            flat=True,
        )
    )

    permission_context = project_permission_context(
        project=project,
        user=request.user,
    )

    return render(
        request,
        "projects/edit_task_dependencies.html",
        {
            "project": project,
            "task": task,
            "available_tasks": (
                available_tasks
            ),
            "selected_dependency_ids": (
                selected_dependency_ids
            ),
            "error_message": error_message,
            **permission_context,
        },
    )
def apply_project_schedule(
    *,
    project,
    schedule,
):
    existing_tasks = {
        task.pk: task
        for task in project.tasks
        .select_related("milestone")
        .prefetch_related("dependencies")
    }

    valid_task_ids = set(
        existing_tasks.keys()
    )

    milestone_map = {}

    with transaction.atomic():
        returned_milestone_names = set()

        for milestone_data in schedule.milestones:
            milestone_name = (
                milestone_data.name.strip()
            )

            if not milestone_name:
                continue

            normalized_name = (
                milestone_name.lower()
            )

            returned_milestone_names.add(
                normalized_name
            )

            existing_milestone = (
                project.milestones
                .filter(
                    name__iexact=milestone_name,
                )
                .first()
            )

            if existing_milestone is None:
                existing_milestone = (
                    ProjectMilestone.objects.create(
                        project=project,
                        name=milestone_name,
                        description=(
                            milestone_data.description.strip()
                        ),
                        target_date=(
                            milestone_data.target_date
                        ),
                        order=max(
                            milestone_data.order,
                            0,
                        ),
                    )
                )

            else:
                existing_milestone.name = (
                    milestone_name
                )
                existing_milestone.description = (
                    milestone_data.description.strip()
                )
                existing_milestone.target_date = (
                    milestone_data.target_date
                )
                existing_milestone.order = max(
                    milestone_data.order,
                    0,
                )

                existing_milestone.save(
                    update_fields=[
                        "name",
                        "description",
                        "target_date",
                        "order",
                        "updated_at",
                    ]
                )

            milestone_map[
                normalized_name
            ] = existing_milestone

        scheduled_task_ids = set()
        pending_dependencies = {}

        for scheduled_task in schedule.tasks:
            task = existing_tasks.get(
                scheduled_task.task_id
            )

            if task is None:
                continue

            if task.pk in scheduled_task_ids:
                continue

            scheduled_task_ids.add(task.pk)

            start_date = (
                scheduled_task.start_date
            )

            due_date = (
                scheduled_task.due_date
            )

            if (
                start_date is not None
                and due_date is not None
                and start_date > due_date
            ):
                raise ValueError(
                    f"Task #{task.pk} has a start "
                    "date after its due date."
                )

            task.start_date = start_date
            task.due_date = due_date

            if (
                scheduled_task.estimated_hours
                is None
            ):
                task.estimated_hours = None
            else:
                try:
                    estimated_hours = Decimal(
                        str(
                            scheduled_task.estimated_hours
                        )
                    )
                except InvalidOperation as error:
                    raise ValueError(
                        f"Task #{task.pk} has an "
                        "invalid hour estimate."
                    ) from error

                if estimated_hours < 0:
                    raise ValueError(
                        f"Task #{task.pk} has a "
                        "negative hour estimate."
                    )

                task.estimated_hours = (
                    estimated_hours
                )

            milestone_name = (
                scheduled_task.milestone_name
            )

            if milestone_name:
                task.milestone = (
                    milestone_map.get(
                        milestone_name
                        .strip()
                        .lower()
                    )
                )
            else:
                task.milestone = None

            task.save(
                update_fields=[
                    "start_date",
                    "due_date",
                    "estimated_hours",
                    "milestone",
                    "updated_at",
                ]
            )

            dependency_ids = []

            for dependency_id in (
                scheduled_task.dependency_ids
            ):
                if dependency_id not in valid_task_ids:
                    continue

                if dependency_id == task.pk:
                    continue

                if dependency_id in dependency_ids:
                    continue

                dependency_ids.append(
                    dependency_id
                )

            pending_dependencies[
                task.pk
            ] = dependency_ids

        for task_id, dependency_ids in (
            pending_dependencies.items()
        ):
            task = existing_tasks[task_id]

            dependencies = [
                existing_tasks[dependency_id]
                for dependency_id in dependency_ids
            ]

            for dependency in dependencies:
                if task_depends_on(
                    task=dependency,
                    possible_dependency=task,
                ):
                    raise ValueError(
                        "AI schedule would create a "
                        "circular dependency involving "
                        f"'{task.title}' and "
                        f"'{dependency.title}'."
                    )

            task.dependencies.set(
                dependencies
            )

    return {
        "milestones_created_or_updated": (
            len(milestone_map)
        ),
        "tasks_scheduled": len(
            scheduled_task_ids
        ),
        "summary": schedule.summary,
    }
@login_required
@require_POST
def generate_more_tasks(
    request,
    project_pk,
):
    project = get_editable_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    tasks_folder = get_object_or_404(
        WorkspaceFolder,
        project=project,
        folder_type="tasks",
    )

    new_tasks = []

    try:
        result = generate_additional_tasks(
            project
        )

        existing_tasks = list(
            project.tasks.all()
        )

        existing_titles = {
            task.title.strip().lower()
            for task in existing_tasks
        }

        existing_task_words = [
            normalize_task_title(
                task.title
            )
            for task in existing_tasks
        ]

        last_task = (
            project.tasks
            .order_by("-order")
            .first()
        )

        next_order = (
            last_task.order + 1
            if last_task
            else 1
        )

        valid_statuses = {
            value
            for value, _
            in Task.Status.choices
        }

        for generated_task in (
            result.tasks[:5]
        ):
            title = (
                generated_task.title.strip()
            )

            if not title:
                continue

            normalized_title = title.lower()

            if normalized_title in existing_titles:
                continue

            new_title_words = (
                normalize_task_title(
                    title
                )
            )

            is_similar = any(
                (
                    len(
                        new_title_words
                        & existing_words
                    )
                    / max(
                        len(new_title_words),
                        1,
                    )
                )
                >= 0.6
                for existing_words
                in existing_task_words
            )

            if is_similar:
                continue

            priority = (
                normalize_task_priority(
                    generated_task.priority
                )
            )

            new_status = (
                generated_task.status
            )

            if new_status not in valid_statuses:
                new_status = Task.Status.TODO

            new_tasks.append(
                Task(
                    project=project,
                    title=title,
                    description=(
                        generated_task
                        .description
                        .strip()
                    ),
                    priority=priority,
                    status=new_status,
                    completed=(
                        new_status
                        == Task.Status.DONE
                    ),
                    order=next_order,
                )
            )

            existing_titles.add(
                normalized_title
            )

            existing_task_words.append(
                new_title_words
            )

            next_order += 1

        if new_tasks:
            Task.objects.bulk_create(
                new_tasks
            )

            mark_schedule_for_refresh(
                project=project,
                reason=(
                    f"{len(new_tasks)} new "
                    "tasks were generated."
                ),
            )

            messages.success(
                request,
                (
                    f"{len(new_tasks)} new tasks "
                    "were generated."
                ),
            )
        else:
            messages.info(
                request,
                (
                    "No new non-duplicate tasks "
                    "were generated."
                ),
            )

    except Exception as error:
        print(
            (
                "Additional task generation "
                "failed:"
            ),
            error,
        )

        messages.error(
            request,
            (
                "BuilderOS could not generate "
                "more tasks."
            ),
        )

    return redirect(
        "workspace_folder",
        project_pk=project.pk,
        folder_pk=tasks_folder.pk,
    )
@login_required
@require_POST
def generate_project_schedule_view(
    request,
    project_pk,
):
    project = get_editable_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    try:
        schedule = generate_project_schedule(
            project
        )

        result = apply_project_schedule(
            project=project,
            schedule=schedule,
        )

        project.schedule_needs_refresh = False
        project.schedule_refresh_reason = ""
        project.schedule_last_generated_at = (
            timezone.now()
        )

        project.save(
            update_fields=[
                "schedule_needs_refresh",
                "schedule_refresh_reason",
                (
                    "schedule_last_"
                    "generated_at"
                ),
                "updated_at",
            ]
        )

        record_project_event(
            project=project,
            event_type=(
                ProjectEvent.EventType
                .SCHEDULE_GENERATED
            ),
            title="AI schedule generated",
            description=result["summary"],
            metadata={
                (
                    "milestones_created_"
                    "or_updated"
                ): result[
                    (
                        "milestones_created_"
                        "or_updated"
                    )
                ],
                "tasks_scheduled": (
                    result["tasks_scheduled"]
                ),
            },
        )

        request.session[
            "schedule_message"
        ] = (
            "AI schedule generated "
            "successfully. "
            f"{result['tasks_scheduled']} "
            "tasks were scheduled."
        )

        request.session[
            "schedule_message_type"
        ] = "success"

    except Exception as error:
        print(
            (
                "AI schedule generation "
                "failed:"
            ),
            error,
        )

        request.session[
            "schedule_message"
        ] = (
            "BuilderOS could not generate "
            "the schedule. Please try again."
        )

        request.session[
            "schedule_message_type"
        ] = "error"

    return redirect(
        "project_timeline",
        project_pk=project.pk,
    )


@login_required
def project_members(
    request,
    project_pk,
):
    project = get_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    memberships = (
        project.memberships
        .select_related("user")
        .order_by(
            "role",
            "user__username",
        )
    )

    permission_context = project_permission_context(
        project=project,
        user=request.user,
    )

    return render(
        request,
        "projects/project_members.html",
        {
            "project": project,
            "memberships": memberships,
            **permission_context,
        },
    )
@login_required
@require_POST
def invite_project_member(
    request,
    project_pk,
):
    project = get_owned_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    if not user_is_project_owner(
        project=project,
        user=request.user,
    ):
        raise PermissionDenied

    username = request.POST.get(
        "username",
        "",
    ).strip()

    role = request.POST.get(
        "role",
        ProjectMembership.Role.VIEWER,
    )

    allowed_roles = {
        ProjectMembership.Role.EDITOR,
        ProjectMembership.Role.VIEWER,
    }

    if role not in allowed_roles:
        role = ProjectMembership.Role.VIEWER

    invited_user = User.objects.filter(
        username__iexact=username,
    ).first()

    if not invited_user:
        messages.error(
            request,
            "No account exists with that username.",
        )

        return redirect(
            "project_members",
            project_pk=project.pk,
        )

    if invited_user == request.user:
        messages.info(
            request,
            "You already own this project.",
        )

        return redirect(
            "project_members",
            project_pk=project.pk,
        )

    membership, created = (
        ProjectMembership.objects.update_or_create(
            project=project,
            user=invited_user,
            defaults={
                "role": role,
            },
        )
    )

    if created:
        messages.success(
            request,
            f"{invited_user.username} was added.",
        )
    else:
        messages.success(
            request,
            (
                f"{invited_user.username}'s role "
                "was updated."
            ),
        )

    return redirect(
        "project_members",
        project_pk=project.pk,
    )
@login_required
@require_POST
def remove_project_member(
    request,
    project_pk,
    membership_pk,
):
    project = get_owned_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )  

    if not user_is_project_owner(
        project=project,
        user=request.user,
    ):
        raise PermissionDenied

    membership = get_object_or_404(
        ProjectMembership,
        pk=membership_pk,
        project=project,
    )

    if membership.role == ProjectMembership.Role.OWNER:
        messages.error(
            request,
            "The project owner cannot be removed.",
        )

        return redirect(
            "project_members",
            project_pk=project.pk,
        )

    username = membership.user.username
    membership.delete()

    messages.success(
        request,
        f"{username} was removed from the project.",
    )

    return redirect(
        "project_members",
        project_pk=project.pk,
    )