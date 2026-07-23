from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
import difflib
from .ai.services import (
    analyze_workspace_change,
    apply_canonical_updates,
    generate_additional_tasks,
    generate_reply,
    generate_task_synchronization,
    generate_workspace_content,
    regenerate_affected_workspace_sections_combined,
    regenerate_workspace_section,
    review_project,
)
from .models import (
    Project,
    ProjectChange,
    ProjectConflict,
    ProjectEvent,
    ProjectHealthReviewRecord,
    ProjectMessage,
    ProjectState,
    Task,
    WorkspaceFolder,
    WorkspaceMessage,
)
from django.views.decorators.http import require_POST
from django.db import transaction
import time
from django.utils import timezone
import json
from django.http import JsonResponse

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
    return render(request, "projects/list.html")


@login_required
def new_project(request):
    project = Project.objects.create(
        owner=request.user,
        status=Project.Status.DRAFT,
    )

    ProjectState.objects.create(
        project=project,
        facts={},
    )

    return redirect("project_setup", pk=project.pk)
@login_required
def project_setup(request, pk):
    project = get_object_or_404(
        Project,
        pk=pk,
        owner=request.user,
    )

    if request.method == "POST":
        content = request.POST.get("message", "").strip()

        if content:
            ProjectMessage.objects.create(
                project=project,
                role=ProjectMessage.Role.USER,
                content=content,
            )

            try:
                result = generate_reply(project)
                print("\n===== BuilderOS Response =====")
                print(result.model_dump_json(indent=4))
                print("==============================\n")
                ProjectMessage.objects.create(
                    project=project,
                    role=ProjectMessage.Role.ASSISTANT,
                    content=result.message,
                )

                if result.ready:
                    project.status = Project.Status.GENERATING
                    project.save(update_fields=["status"])

            except Exception as error:
                print(error)

                ProjectMessage.objects.create(
                    project=project,
                    role=ProjectMessage.Role.ASSISTANT,
                    content="I ran into a problem. Please try again.",
                )

        return redirect("project_setup", pk=project.pk)

    messages = project.messages.all()

    return render(
        request,
        "projects/setup.html",
        {
            "project": project,
            "messages": messages,
        },
    )

@login_required
@require_POST
def generate_workspace(request, pk):
    project = get_object_or_404(
        Project,
        pk=pk,
        owner=request.user,
    )

    if project.status != Project.Status.GENERATING:
        return redirect("project_setup", pk=project.pk)

    default_folders = [
        {"name": "Overview", "folder_type": "overview"},
        {"name": "Requirements", "folder_type": "requirements"},
        {"name": "Roadmap", "folder_type": "roadmap"},
        {"name": "Tasks", "folder_type": "tasks"},
        {"name": "Materials & Stack", "folder_type": "resources"},
        {"name": "Budget", "folder_type": "budget"},
        {"name": "Learning Resources", "folder_type": "learning"},
        {"name": "Documentation", "folder_type": "documentation"},
        {"name": "Testing", "folder_type": "testing"},
    ]

    if not project.folders.exists():
        WorkspaceFolder.objects.bulk_create(
            [
                WorkspaceFolder(
                    project=project,
                    name=folder["name"],
                    folder_type=folder["folder_type"],
                    order=index,
                )
                for index, folder in enumerate(
                    default_folders,
                    start=1,
                )
            ]
        )

    try:
        generated = generate_workspace_content(project)

        print("\n===== Generated Workspace =====")
        print(generated.model_dump_json(indent=4))
        print("===============================\n")

        project.name = generated.project_name

        sections_by_type = {
            section.folder_type: section.content
            for section in generated.sections
        }

        for folder in project.folders.all():
            folder.description = sections_by_type.get(
                folder.folder_type,
                "No content was generated for this section.",
            )

            folder.save(
                update_fields=[
                    "description",
                    "updated_at",
                ]
            )

        if not project.tasks.exists():
            Task.objects.bulk_create(
                [
                    Task(
                        project=project,
                        title=generated_task.title,
                        description=generated_task.description,
                        priority=generated_task.priority,
                        order=index,
                    )
                    for index, generated_task in enumerate(
                        generated.tasks,
                        start=1,
                    )
                ]
            )

    except Exception as error:
        print("Workspace generation failed:", error)
        return redirect("project_setup", pk=project.pk)

    project.status = Project.Status.ACTIVE
    project.save(update_fields=["name", "status"])

    return redirect("workspace", pk=project.pk)
@login_required
def workspace(request, pk):
    project = get_object_or_404(
        Project,
        pk=pk,
        owner=request.user,
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
        },
    )
@login_required
def workspace_folder(request, project_pk, folder_pk):
    project = get_object_or_404(
        Project,
        pk=project_pk,
        owner=request.user,
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
        },
    )
@login_required
def edit_workspace_folder(request, project_pk, folder_pk):
    project = get_object_or_404(
        Project,
        pk=project_pk,
        owner=request.user,
    )

    folder = get_object_or_404(
        WorkspaceFolder,
        pk=folder_pk,
        project=project,
    )

    if request.method == "POST":
        folder.description = request.POST.get("description", "")
        folder.save(update_fields=["description", "updated_at"])
        record_project_event(
            project=project,
            event_type=ProjectEvent.EventType.WORKSPACE_UPDATED,
            title="Workspace section edited",
            description=folder.name,
            metadata={
                "folder_id": folder.pk,
                "folder_type": folder.folder_type,
            },
        )
        return redirect(
            "workspace_folder",
            project_pk=project.pk,
            folder_pk=folder.pk,
        )

    return render(
        request,
        "projects/workspace_folder_edit.html",
        {
            "project": project,
            "folder": folder,
        },
    )

@login_required
@require_POST
def regenerate_workspace_folder(request, project_pk, folder_pk):
    project = get_object_or_404(
        Project,
        pk=project_pk,
        owner=request.user,
    )

    folder = get_object_or_404(
        WorkspaceFolder,
        pk=folder_pk,
        project=project,
    )

    try:
        result = regenerate_workspace_section(
            project=project,
            folder=folder,
        )

        folder.description = result.content
        folder.save(update_fields=["description", "updated_at"])

        print(f"Regenerated section: {folder.name}")

    except Exception as error:
        print(
            f"Failed to regenerate {folder.name}:",
            error,
        )

    return redirect(
        "workspace_folder",
        project_pk=project.pk,
        folder_pk=folder.pk,
    )
@login_required
@require_POST
def toggle_task(request, project_pk, task_pk):
    project = get_object_or_404(
        Project,
        pk=project_pk,
        owner=request.user,
    )

    task = get_object_or_404(
        Task,
        pk=task_pk,
        project=project,
    )

    task.completed = not task.completed

    if task.completed:
        task.status = Task.Status.DONE
    else:
        task.status = Task.Status.TODO

    task.save(
        update_fields=[
            "completed",
            "status",
            "updated_at",
        ]
    )
    if task.completed:
        event_type = (
            ProjectEvent.EventType.TASK_COMPLETED
        )
        event_title = "Task completed"
    else:
        event_type = (
            ProjectEvent.EventType.TASK_REOPENED
        )
        event_title = "Task reopened"

    record_project_event(
        project=project,
        event_type=event_type,
        title=event_title,
        description=task.title,
        metadata={
            "task_id": task.pk,
            "task_title": task.title,
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
@login_required
def new_task(request, project_pk):
    project = get_object_or_404(
        Project,
        pk=project_pk,
        owner=request.user,
    )

    tasks_folder = get_object_or_404(
        WorkspaceFolder,
        project=project,
        folder_type="tasks",
    )

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        priority = request.POST.get(
            "priority",
            str(Task.Priority.MEDIUM),
        )

        if title:
            last_task = project.tasks.order_by("-order").first()
            next_order = last_task.order + 1 if last_task else 1

            Task.objects.create(
                project=project,
                title=title,
                description=description,
                priority=int(priority),
                order=next_order,
            )

            return redirect(
                "workspace_folder",
                project_pk=project.pk,
                folder_pk=tasks_folder.pk,
            )

    return render(
        request,
        "projects/task_form.html",
        {
            "project": project,
            "tasks_folder": tasks_folder,
            "priorities": Task.Priority.choices,
        },
    )
@login_required
def edit_task(request, project_pk, task_pk):
    project = get_object_or_404(
        Project,
        pk=project_pk,
        owner=request.user,
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

        task.title = request.POST.get("title", "").strip()
        task.description = request.POST.get(
            "description",
            "",
        ).strip()

        task.priority = int(
            request.POST.get(
                "priority",
                task.priority,
            )
        )

        task.save()

        return redirect(
            "workspace_folder",
            project_pk=project.pk,
            folder_pk=tasks_folder.pk,
        )

    return render(
        request,
        "projects/edit_task.html",
        {
            "project": project,
            "task": task,
            "priorities": Task.Priority.choices,
        },
    )
@login_required
@require_POST
def delete_task(request, project_pk, task_pk):

    project = get_object_or_404(
        Project,
        pk=project_pk,
        owner=request.user,
    )

    task = get_object_or_404(
        Task,
        pk=task_pk,
        project=project,
    )

    task.delete()

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
@login_required
@require_POST
def generate_more_tasks(request, project_pk):
    project = get_object_or_404(
        Project,
        pk=project_pk,
        owner=request.user,
    )

    tasks_folder = get_object_or_404(
        WorkspaceFolder,
        project=project,
        folder_type="tasks",
    )

    try:
        result = generate_additional_tasks(project)

        existing_tasks = list(project.tasks.all())

        existing_titles = {
            task.title.strip().lower()
            for task in existing_tasks
        }

        existing_task_words = [
            normalize_task_title(task.title)
            for task in existing_tasks
        ]

        last_task = project.tasks.order_by("-order").first()
        next_order = last_task.order + 1 if last_task else 1

        new_tasks = []

        for generated_task in result.tasks[:5]:
            title = generated_task.title.strip()
            description = generated_task.description.strip()

            if not title:
                continue

            normalized_title = title.lower()

            # Skip exact duplicate titles.
            if normalized_title in existing_titles:
                continue

            new_title_words = normalize_task_title(title)

            # Skip titles that are too similar to existing tasks.
            is_similar = any(
                len(new_title_words & existing_words)
                / max(len(new_title_words), 1)
                >= 0.6
                for existing_words in existing_task_words
            )

            if is_similar:
                continue

            priority = max(
                Task.Priority.LOW,
                min(
                    Task.Priority.HIGH,
                    generated_task.priority,
                ),
            )

            valid_statuses = {
                value
                for value, _ in Task.Status.choices
            }

            new_status = generated_task.status

            if new_status not in valid_statuses:
                new_status = Task.Status.TODO

            new_tasks.append(
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
            # Prevent duplicates among tasks accepted in this same request.
            existing_titles.add(normalized_title)
            existing_task_words.append(new_title_words)
            next_order += 1

        if new_tasks:
            Task.objects.bulk_create(new_tasks)

        print(f"Generated {len(new_tasks)} additional tasks.")

    except Exception as error:
        print("Additional task generation failed:", error)

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

    existing_tasks = list(project.tasks.all())

    tasks_by_id = {
        task.pk: task
        for task in existing_tasks
    }

    # Update existing tasks by database ID.
    for task_update in synchronization.tasks_to_update:
        task = tasks_by_id.get(task_update.task_id)

        if task is None:
            continue

        new_title = task_update.new_title.strip()

        if not new_title:
            continue

        task.title = new_title
        task.description = task_update.description.strip()
        task.priority = max(
            Task.Priority.LOW,
            min(
                Task.Priority.HIGH,
                task_update.priority,
            ),
        )
        valid_statuses = {
            value
            for value, _ in Task.Status.choices
        }

        new_status = task_update.status

        if (
            new_status is not None
            and new_status in valid_statuses
        ):
            task.status = new_status
            task.completed = (
                new_status == Task.Status.DONE
            )

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

    # Remove only unfinished obsolete tasks by database ID.
    removal_ids = set(
        synchronization.task_ids_to_remove
    )

    tasks_to_remove = project.tasks.filter(
        completed=False,
        pk__in=removal_ids,
    )

    removed_count = tasks_to_remove.count()
    tasks_to_remove.delete()

    # Refresh comparisons after updates and removals.
    remaining_tasks = list(project.tasks.all())

    existing_titles = {
        task.title.strip().lower()
        for task in remaining_tasks
    }

    existing_task_words = [
        normalize_task_title(task.title)
        for task in remaining_tasks
    ]

    last_task = project.tasks.order_by("-order").first()
    next_order = last_task.order + 1 if last_task else 1

    tasks_to_create = []

    for generated_task in synchronization.tasks_to_add:
        title = generated_task.title.strip()

        if not title:
            continue

        normalized_title = title.lower()

        if normalized_title in existing_titles:
            continue

        new_title_words = normalize_task_title(title)

        is_similar = any(
            len(new_title_words & existing_words)
            / max(len(new_title_words), 1)
            >= 0.6
            for existing_words in existing_task_words
        )

        if is_similar:
            continue

        priority = max(
            Task.Priority.LOW,
            min(
                Task.Priority.HIGH,
                generated_task.priority,
            ),
        )

        new_status = generated_task.status

        if new_status not in valid_statuses:
            new_status = Task.Status.TODO

        tasks_to_create.append(
            Task(
                project=project,
                title=title,
                description=(
                    generated_task.description.strip()
                ),
                priority=priority,
                status=new_status,
                completed=(
                    new_status == Task.Status.DONE
                ),
                order=next_order,
            )
        )

        existing_titles.add(normalized_title)
        existing_task_words.append(new_title_words)

        next_order += 1
        added_count += 1

    if tasks_to_create:
        Task.objects.bulk_create(tasks_to_create)

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
    project_state, _ = ProjectState.objects.get_or_create(
        project=project,
        defaults={"facts": {}},
    )

    WorkspaceMessage.objects.create(
        project=project,
        role=WorkspaceMessage.Role.USER,
        content=content,
    )
    

    analysis = analyze_workspace_change(project)

    print("\n===== Workspace Change Analysis =====")
    print(analysis.model_dump_json(indent=4))
    print("=====================================\n")

    facts_before = project_state.facts.copy()

    sections_before = {
        folder.folder_type: folder.description
        for folder in project.folders.all()
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
        for task in project.tasks.order_by("order")
    ]

    updated_facts = apply_canonical_updates(
        current_facts=project_state.facts,
        analysis=analysis,
    )

    cascade_started_at = time.monotonic()

    regenerated_sections = (
        regenerate_affected_workspace_sections_combined(
            project=project,
            analysis=analysis,
            updated_facts=updated_facts,
        )
    )

    cascade_seconds = (
        time.monotonic()
        - cascade_started_at
    )

    print(
        "Combined workspace regeneration took "
        f"{cascade_seconds:.2f} seconds."
    )

    tasks_affected = (
        "tasks" in analysis.affected_sections
    )

    synchronization = None

    if tasks_affected:
        synchronization = generate_task_synchronization(
            project=project,
            analysis=analysis,
            updated_facts=updated_facts,
            regenerated_sections=regenerated_sections,
        )
        print(regenerated_sections.keys())

        print("\n===== Task Synchronization Plan =====")
        print(synchronization.model_dump_json(indent=4))
        print("=====================================\n")
    facts_changed = [
        update.key
        for update in analysis.canonical_updates
    ]
    with transaction.atomic():
        project_state.facts = updated_facts
        project_state.save(
            update_fields=[
                "facts",
                "updated_at",
            ]
        )

        updated_section_names = []

        for section_type, new_content in regenerated_sections.items():
            folder = project.folders.filter(
                folder_type=section_type,
            ).first()

            if folder is None:
                continue

            folder.description = new_content
            folder.save(
                update_fields=[
                    "description",
                    "updated_at",
                ]
            )

            updated_section_names.append(folder.name)

        if updated_section_names:
            section_summary = ", ".join(
                updated_section_names
            )
        else:
            section_summary = (
                "No text sections required changes"
            )

        task_changes = {
            "added": 0,
            "updated": 0,
            "removed": 0,
        }

        task_sync_summary = ""

        if tasks_affected and synchronization is not None:
            task_changes = apply_task_synchronization(
                project=project,
                synchronization=synchronization,
            )

            task_sync_summary = synchronization.summary

        task_note = ""

        if tasks_affected:
            task_note = (
                "\n\nTask synchronization:\n"
                f"- Added: {task_changes['added']}\n"
                f"- Updated: {task_changes['updated']}\n"
                f"- Removed: {task_changes['removed']}"
            )

            if task_sync_summary:
                task_note += (
                    f"\n\n{task_sync_summary}"
                )

        sections_after = {
            folder.folder_type: folder.description
            for folder in project.folders.all()
        }

        tasks_after = [
            {
                "id": task.pk,
                "title": task.title,
                "description": task.description,
                "priority": task.priority,
                "completed": task.completed,
                "order": task.order,
                "status": task.status,
            }
            for task in project.tasks.order_by("order")
        ]

        change = ProjectChange.objects.create(
            project=project,
            user_message=content,
            summary=analysis.summary,
            facts_before=facts_before,
            facts_after=updated_facts,
            sections_before=sections_before,
            sections_after=sections_after,
            tasks_before=tasks_before,
            tasks_after=tasks_after,
        )

        WorkspaceMessage.objects.create(
            project=project,
            role=WorkspaceMessage.Role.ASSISTANT,
            content=(
                f"{analysis.assistant_message}\n\n"
                f"Why this matters:\n"
                f"{analysis.impact_explanation}\n\n"
                f"Updated workspace sections: "
                f"{section_summary}."
                f"{task_note}"
            ),
        )
        record_project_event(
                project=project,
                event_type=(
                    ProjectEvent.EventType.WORKSPACE_UPDATED
                ),
            title="Workspace updated",
            description=(
                f"Updated sections: {section_summary}. "
                f"Tasks added: {task_changes['added']}; "
                f"updated: {task_changes['updated']}; "
                f"removed: {task_changes['removed']}."
            ),
            metadata={
                "change_id": change.pk,
                "sections": updated_section_names,
                "facts_changed": facts_changed,
                "task_changes": task_changes,
            },
        )

    

    print("\n===== Cascade Update Complete =====")
    print("Updated facts:", updated_facts)
    print("Updated sections:", updated_section_names)
    print("Task changes:", task_changes)
    print("Change history record created.")
    print("===================================\n")

    return {
        "analysis": analysis,
        "change": change,
        "updated_facts": updated_facts,
        "sections": updated_section_names,
        "task_changes": task_changes,
        "facts_changed": facts_changed,
    }
@login_required
def workspace_assistant(request, project_pk):
    project = get_object_or_404(
        Project,
        pk=project_pk,
        owner=request.user,
    )

    ProjectState.objects.get_or_create(
        project=project,
        defaults={"facts": {}},
    )

    if request.method == "POST":
        content = request.POST.get(
            "message",
            "",
        ).strip()

        if content:
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

                try:
                    review_result = run_project_review(
                        project
                    )

                    latest_health_score = (
                        review_result[
                            "review"
                        ].health_score
                    )

                    latest_open_conflicts = (
                        project.conflicts.filter(
                            status=(
                                ProjectConflict.Status.OPEN
                            ),
                        ).count()
                    )

                    review_completed = True

                except Exception as review_error:
                    print(
                        "Automatic project review failed:",
                        review_error,
                    )

                    latest_health_score = None
                    latest_open_conflicts = (
                        previous_open_conflicts
                    )
                    review_completed = False

                health_score_change = None

                if (
                    previous_health_score is not None
                    and latest_health_score is not None
                ):
                    health_score_change = (
                        latest_health_score
                        - previous_health_score
                    )

                conflict_count_change = (
                    latest_open_conflicts
                    - previous_open_conflicts
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
                    "review_completed": (
                        review_completed
                    ),
                }

            except Exception as error:
                print(
                    "Workspace cascade update failed:",
                    error,
                )

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

        return redirect(
            "workspace_assistant",
            project_pk=project.pk,
        )

    messages = project.workspace_messages.all()

    update_summary = request.session.pop(
        "workspace_update_summary",
        None,
    )

    return render(
        request,
        "projects/workspace_assistant.html",
        {
            "project": project,
            "messages": messages,
            "update_summary": update_summary,
        },
    )
@login_required
def project_change_history(request, project_pk):
    project = get_object_or_404(
        Project,
        pk=project_pk,
        owner=request.user,
    )

    changes = project.changes.order_by("-created_at")

    return render(
        request,
        "projects/project_change_history.html",
        {
            "project": project,
            "changes": changes,
        },
    )

@login_required
def project_change_detail(request, project_pk, change_pk):
    project = get_object_or_404(
        Project,
        pk=project_pk,
        owner=request.user,
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

    return render(
        request,
        "projects/project_change_detail.html",
        {
            "project": project,
            "change": change,
            "fact_changes": fact_changes,
            "section_changes": section_changes,
            "task_changes": task_changes,
        },
    )

@login_required
@require_POST
def undo_project_change(request, project_pk, change_pk):
    project = get_object_or_404(
        Project,
        pk=project_pk,
        owner=request.user,
    )

    change = get_object_or_404(
        ProjectChange,
        pk=change_pk,
        project=project,
    )

    try:
        with transaction.atomic():
            project_state, _ = ProjectState.objects.get_or_create(
                project=project,
                defaults={"facts": {}},
            )

            # Restore canonical facts.
            project_state.facts = change.facts_before or {}
            project_state.save(
                update_fields=[
                    "facts",
                    "updated_at",
                ]
            )

            # Restore workspace sections.
            sections_before = change.sections_before or {}

            for folder in project.folders.all():
                if folder.folder_type not in sections_before:
                    continue

                folder.description = sections_before[folder.folder_type]
                folder.save(
                    update_fields=[
                        "description",
                        "updated_at",
                    ]
                )

            # Restore tasks from the snapshot.
            project.tasks.all().delete()

            restored_tasks = []

            for task_data in change.tasks_before or []:
                title = task_data.get("title", "").strip()

                if not title:
                    continue

                priority = task_data.get(
                    "priority",
                    Task.Priority.MEDIUM,
                )

                priority = max(
                    Task.Priority.LOW,
                    min(
                        Task.Priority.HIGH,
                        priority,
                    ),
                )
                saved_status = task_data.get(
                    "status",
                    Task.Status.TODO,
                )

                valid_statuses = {
                    value
                    for value, _ in Task.Status.choices
                }

                if saved_status not in valid_statuses:
                    saved_status = (
                        Task.Status.DONE
                        if task_data.get("completed", False)
                        else Task.Status.TODO
                    )

                restored_tasks.append(
                    Task(
                        project=project,
                        title=title,
                        description=task_data.get(
                            "description",
                            "",
                        ),
                        priority=priority,
                        status=saved_status,
                        completed=(
                            saved_status == Task.Status.DONE
                        ),
                        order=task_data.get(
                            "order",
                            0,
                        ),
                    )
                )

            if restored_tasks:
                Task.objects.bulk_create(restored_tasks)

            WorkspaceMessage.objects.create(
                project=project,
                role=WorkspaceMessage.Role.ASSISTANT,
                content=(
                    f"Undid change #{change.pk}: "
                    f"{change.summary or change.user_message}"
                ),
            )
            record_project_event(
                project=project,
                event_type=(
                    ProjectEvent.EventType.CHANGE_UNDONE
                ),
                title="Project change undone",
                description=(
                    change.summary
                    or change.user_message
                ),
                metadata={
                    "change_id": change.pk,
                },
            )

        print(f"Undid ProjectChange #{change.pk}")

    except Exception as error:
        print(
            f"Failed to undo ProjectChange #{change.pk}:",
            error,
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
def project_review(request, project_pk):
    project = get_object_or_404(
        Project,
        pk=project_pk,
        owner=request.user,
    )

    review = None
    current_critical_issues = []
    current_warnings = []
    error_message = ""

    if request.method == "POST":
        try:
            result = run_project_review(project)

            review = result["review"]
            current_critical_issues = result[
                "critical_issues"
            ]
            current_warnings = result["warnings"]

        except Exception as error:
            print(
                "Project health review failed:",
                error,
            )

            error_message = (
                "BuilderOS could not review this project. "
                "Please try again."
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

    open_conflicts = project.conflicts.filter(
        status=ProjectConflict.Status.OPEN,
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
            "current_warnings": current_warnings,
            "error_message": error_message,
            "previous_reviews": previous_reviews,
            "open_conflicts": open_conflicts,

            "health_history": health_history,
            "latest_saved_score": latest_saved_score,
            "previous_saved_score": previous_saved_score,
            "health_change": health_change,
            "health_trend": health_trend,

            "review_delta": review_delta,
        },
    )
@login_required
@require_POST
def resolve_project_conflict(
    request,
    project_pk,
    conflict_pk,
):
    project = get_object_or_404(
        Project,
        pk=project_pk,
        owner=request.user,
    )

    conflict = get_object_or_404(
        ProjectConflict,
        pk=conflict_pk,
        project=project,
    )

    conflict.status = ProjectConflict.Status.RESOLVED
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
            ProjectEvent.EventType.CONFLICT_RESOLVED
        ),
        title="Conflict marked resolved",
        description=conflict.title,
        metadata={
            "conflict_id": conflict.pk,
            "conflict_key": conflict.key,
        },
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
    project = get_object_or_404(
        Project,
        pk=project_pk,
        owner=request.user,
    )

    conflict = get_object_or_404(
        ProjectConflict,
        pk=conflict_pk,
        project=project,
    )

    conflict.status = ProjectConflict.Status.IGNORED
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
            ProjectEvent.EventType.CONFLICT_IGNORED
        ),
        title="Conflict ignored",
        description=conflict.title,
        metadata={
            "conflict_id": conflict.pk,
            "conflict_key": conflict.key,
        },
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
    project = get_object_or_404(
        Project,
        pk=project_pk,
        owner=request.user,
    )

    conflict = get_object_or_404(
        ProjectConflict,
        pk=conflict_pk,
        project=project,
        status=ProjectConflict.Status.OPEN,
    )

    fix_request = (
        "Apply the following project-health conflict fix.\n\n"
        f"Conflict key: {conflict.key}\n"
        f"Conflict title: {conflict.title}\n"
        f"Problem: {conflict.description}\n"
        f"Source type: {conflict.source_type}\n"
        f"Source reference: {conflict.source_reference}\n\n"
        f"Requested fix:\n{conflict.suggested_fix}\n\n"
        "Update only the project facts, workspace sections, and tasks "
        "that are meaningfully affected. Preserve unrelated content."
    )

    try:
        result = apply_workspace_change(
            project=project,
            content=fix_request,
        )

        try:
            review_result = run_project_review(project)

            latest_health_score = (
                review_result["review"].health_score
            )

        except Exception as review_error:
            print(
                "Automatic review after AI fix failed:",
                review_error,
            )

            latest_health_score = None

        remaining_conflict = (
            ProjectConflict.objects.filter(
                project=project,
                key=conflict.key,
                status=ProjectConflict.Status.OPEN,
            )
            .exclude(pk=conflict.pk)
            .exists()
        )

        if not remaining_conflict:
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
                    ProjectEvent.EventType.CONFLICT_FIXED
                ),
                title="AI conflict fix applied",
                description=conflict.title,
                metadata={
                    "conflict_id": conflict.pk,
                    "conflict_key": conflict.key,
                    "health_score": latest_health_score,
                    "sections": result["sections"],
                    "task_changes": (
                        result["task_changes"]
                    ),
                },
            )

        request.session[
            "workspace_update_summary"
        ] = {
            "sections": result["sections"],
            "task_changes": result["task_changes"],
            "facts_changed": result["facts_changed"],
            "health_score": latest_health_score,
        }

        return redirect(
            "workspace_assistant",
            project_pk=project.pk,
        )

    except Exception as error:
        print(
            f"Failed to apply conflict #{conflict.pk}:",
            error,
        )

        return redirect(
            "project_review",
            project_pk=project.pk,
        )
@login_required
def project_activity(request, project_pk):
    project = get_object_or_404(
        Project,
        pk=project_pk,
        owner=request.user,
    )

    events = project.events.all()

    return render(
        request,
        "projects/project_activity.html",
        {
            "project": project,
            "events": events,
        },
    )
@login_required
def project_board(request, project_pk):
    project = get_object_or_404(
        Project,
        pk=project_pk,
        owner=request.user,
    )

    todo_tasks = project.tasks.filter(
        status=Task.Status.TODO,
    ).order_by("order", "-priority")

    in_progress_tasks = project.tasks.filter(
        status=Task.Status.IN_PROGRESS,
    ).order_by("order", "-priority")

    review_tasks = project.tasks.filter(
        status=Task.Status.REVIEW,
    ).order_by("order", "-priority")

    done_tasks = project.tasks.filter(
        status=Task.Status.DONE,
    ).order_by("order", "-priority")

    return render(
        request,
        "projects/project_board.html",
        {
            "project": project,
            "todo_tasks": todo_tasks,
            "in_progress_tasks": in_progress_tasks,
            "review_tasks": review_tasks,
            "done_tasks": done_tasks,
            "status_choices": Task.Status.choices,
        },
    )
@login_required
@require_POST
def update_task_status(
    request,
    project_pk,
    task_pk,
):
    project = get_object_or_404(
        Project,
        pk=project_pk,
        owner=request.user,
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
        choice[0]
        for choice in Task.Status.choices
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

    record_project_event(
        project=project,
        event_type=(
            ProjectEvent.EventType.TASK_STATUS_CHANGED
        ),
        title="Task status changed",
        description=(
            f"{task.title}: "
            f"{dict(Task.Status.choices)[previous_status]} "
            f"→ "
            f"{dict(Task.Status.choices)[new_status]}"
        ),
        metadata={
            "task_id": task.pk,
            "task_title": task.title,
            "previous_status": previous_status,
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
    project = get_object_or_404(
        Project,
        pk=project_pk,
        owner=request.user,
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
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {
                "success": False,
                "error": "Invalid JSON request.",
            },
            status=400,
        )

    new_status = str(
        payload.get("status", "")
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
                "error": "Invalid task status.",
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
                "error": "Invalid task ordering.",
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

        # Only reorder tasks that belong to this project
        # and are now in the destination column.
        destination_tasks = {
            existing_task.pk: existing_task
            for existing_task in project.tasks.filter(
                status=new_status,
                pk__in=ordered_task_ids,
            )
        }

        tasks_to_update = []

        for order, ordered_task_id in enumerate(
            ordered_task_ids,
            start=1,
        ):
            ordered_task = destination_tasks.get(
                ordered_task_id
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
                    f"→ {status_labels[new_status]}"
                ),
                metadata={
                    "task_id": task.pk,
                    "task_title": task.title,
                    "previous_status": previous_status,
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