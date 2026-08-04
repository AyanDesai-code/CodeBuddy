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
from django.http import JsonResponse, request
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from openai import project

from projects.analytics import capture_event

from .ai.services import (

    generate_additional_tasks,
    generate_project_schedule,
    generate_reply,
    generate_workspace_content,
    generate_workspace_update_plan,
    regenerate_workspace_section,
    review_project,
    generate_project_budget,
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
    BudgetItem,
    ProjectResource,
    WorkspaceFolder,
    ProjectResource,
)

from .permissions import (
    get_editable_project_for_user,
    get_owned_project_for_user,
    get_project_for_user,
    project_permission_context,
    user_is_project_owner,
)
from .limits import (
    can_create_project,
    get_active_project_limit,
    get_owned_active_project_count,
)
from collections import defaultdict
from decimal import Decimal
import traceback
from django.core.exceptions import PermissionDenied
from concurrent.futures import (
    ThreadPoolExecutor,
)
User = get_user_model()
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

from decimal import Decimal, InvalidOperation

from .models import BudgetItem


def build_budget_items_from_ai(
    *,
    project,
    generated_items,
):
    valid_categories = {
        value
        for value, _
        in BudgetItem.Category.choices
    }

    valid_requirement_levels = {
        value
        for value, _
        in BudgetItem.RequirementLevel.choices
    }

    recurring_categories = {
        BudgetItem.Category.HOSTING,
        BudgetItem.Category.API,
    }

    budget_items = []

    for order, generated_item in enumerate(
        generated_items or [],
        start=1,
    ):
        name = (
            generated_item.name
            or ""
        ).strip()

        if not name:
            continue

        category = (
            generated_item.category
            or ""
        ).strip().lower()

        if category not in valid_categories:
            category = BudgetItem.Category.OTHER

        requirement_level = (
            generated_item.requirement_level
            or ""
        ).strip().lower()

        if (
            requirement_level
            not in valid_requirement_levels
        ):
            requirement_level = (
                BudgetItem
                .RequirementLevel
                .RECOMMENDED
            )

        try:
            quantity = int(
                generated_item.quantity
            )
        except (TypeError, ValueError):
            quantity = 1

        quantity = max(1, quantity)

        try:
            unit_cost = Decimal(
                str(
                    generated_item.unit_cost
                    or "0"
                )
            )
        except (
            InvalidOperation,
            TypeError,
            ValueError,
        ):
            unit_cost = Decimal("0.00")

        unit_cost = max(
            Decimal("0.00"),
            unit_cost,
        )

        is_recurring = bool(
            generated_item.is_recurring
        )

        # Only hosting and API items may be monthly.
        if category not in recurring_categories:
            is_recurring = False

        item_text = (
            f"{name} "
            f"{generated_item.description or ''}"
        ).lower()

        annual_phrases = {
            "annual",
            "annually",
            "yearly",
            "per year",
            "first year",
            "domain name",
            "domain registration",
        }

        looks_annual = any(
            phrase in item_text
            for phrase in annual_phrases
        )

        # Until annual billing is supported,
        # annual expenses are shown as one-time.
        if looks_annual:
            is_recurring = False

        # A recurring line represents one month's
        # charge, not several months multiplied
        # together.
        if is_recurring:
            quantity = 1

        try:
            confidence = int(
                generated_item.confidence
            )
        except (TypeError, ValueError):
            confidence = 3

        confidence = max(
            1,
            min(5, confidence),
        )

        budget_items.append(
            BudgetItem(
                project=project,
                order=order,
                name=name,
                description=(
                    generated_item.description
                    or ""
                ).strip(),
                category=category,
                requirement_level=(
                    requirement_level
                ),
                purchase_status=(
                    BudgetItem
                    .PurchaseStatus
                    .PLANNED
                ),
                quantity=quantity,
                unit_cost=unit_cost,
                is_recurring=is_recurring,
                is_physical_part=bool(
                    generated_item
                    .is_physical_part
                ),
                source_name=(
                    generated_item.source_name
                    or ""
                ).strip(),
                source_url=(
                    generated_item.source_url
                    or ""
                ).strip(),
                alternative_notes=(
                    generated_item
                    .alternative_notes
                    or ""
                ).strip(),
                confidence=confidence,
            )
        )

    return budget_items
def normalize_resource_type(raw_resource_type):
    valid_types = {
        value
        for value, _
        in ProjectResource.ResourceType.choices
    }

    normalized = (
        raw_resource_type
        or ProjectResource.ResourceType.DOCUMENTATION
    ).strip().lower()

    if normalized not in valid_types:
        return (
            ProjectResource
            .ResourceType
            .DOCUMENTATION
        )

    return normalized
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
    show_archived = (
        request.GET.get("archived")
        == "1"
    )

    projects = (
        Project.objects
        .filter(
            memberships__user=request.user
        )
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
        total_tasks = (
            project.tasks.count()
        )

        completed_tasks = (
            project.tasks
            .filter(
                status=Task.Status.DONE,
            )
            .count()
        )

        task_progress = 0

        if total_tasks > 0:
            task_progress = round(
                completed_tasks
                / total_tasks
                * 100
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
            project.conflicts
            .filter(
                status=(
                    ProjectConflict.Status.OPEN
                ),
            )
            .count()
        )

        permission_context = (
            project_permission_context(
                project=project,
                user=request.user,
            )
        )

        project_cards.append(
            {
                "project": project,
                "total_tasks": total_tasks,
                "completed_tasks": (
                    completed_tasks
                ),
                "task_progress": (
                    task_progress
                ),
                "health_score": (
                    health_score
                ),
                "open_conflict_count": (
                    open_conflict_count
                ),
                **permission_context,
            }
        )

    # These belong OUTSIDE the loop.
    owned_active_project_count = (
        get_owned_active_project_count(
            request.user
        )
    )

    project_limit = (
        get_active_project_limit(
            request.user
        )
    )

    user_can_create_project = (
        can_create_project(
            request.user
        )
    )

    return render(
        request,
        "projects/list.html",
        {
            "project_cards": project_cards,
            "show_archived": show_archived,

            # Names must match the template.
            "can_create_project": (
                user_can_create_project
            ),
            "active_project_count": (
                owned_active_project_count
            ),
            "project_limit": (
                project_limit
            ),
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

    project_id = project.pk
    project_name = (
        project.name
        or "Untitled Project"
    )

    was_archived = (
        project.status
        == Project.Status.ARCHIVED
    )

    capture_event(
        distinct_id=(
            f"user_{request.user.pk}"
        ),
        event="project_deleted",
        properties={
            "project_id": project_id,
            "project_name": project_name,
            "was_archived": was_archived,
        },
    )

    project.delete()

    messages.success(
        request,
        (
            f'"{project_name}" was '
            "permanently deleted."
        ),
    )

    if was_archived:
        return redirect(
            f"{reverse('project_list')}"
            "?archived=1"
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
    capture_event(
        distinct_id=f"user_{request.user.pk}",
        event="project_archived",
        properties={
            "project_id": project.pk,
        },
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

    if not can_create_project(
        request.user
    ):
        project_limit = (
            get_active_project_limit(
                request.user
            )
        )

        messages.error(
            request,
            (
                "Core accounts can have up to "
                f"{project_limit} active projects. "
                "Archive or delete an active "
                "project before restoring this one."
            ),
        )

        return redirect(
            f"{reverse('project_list')}"
            "?archived=1"
        )

    project_name = (
        project.name
        or "Untitled Project"
    )

    project.status = (
        Project.Status.ACTIVE
    )

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
    capture_event(
        distinct_id=f"user_{request.user.pk}",
        event="project_restored",
        properties={
            "project_id": project.pk,
        },
    )

    return redirect(
        f"{reverse('project_list')}"
        "?archived=1"
    )
@login_required
def new_project(request):
    if not can_create_project(request.user):
        messages.warning(
            request,
            (
                f"Core accounts can have up to "
                f"{get_active_project_limit(request.user)} active projects. "
                "Archive or delete a project to create another."
            ),
        )
        return redirect("project_list")

    project = Project.objects.create(
        owner=request.user,
        name="Untitled Project",
        status=Project.Status.DRAFT,
    )
    capture_event(
        distinct_id=f"user_{request.user.pk}",
        event="project_created",
        properties={
            "project_id": project.pk,
        },
    )

    return redirect(
        "project_setup",
        pk=project.pk,
    )
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
def generate_workspace(
    request,
    pk,
):
    print(
        "GENERATE WORKSPACE REQUEST:",
        request.method,
        request.path,
    )

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

        ai_started_at = time.monotonic()

        with ThreadPoolExecutor(
            max_workers=2
        ) as executor:
            workspace_future = executor.submit(
                generate_workspace_content,
                project,
            )

            budget_future = executor.submit(
                generate_project_budget,
                project,
            )

            generated_workspace = (
                workspace_future.result()
            )

            generated_budget = (
                budget_future.result()
            )

        print(
            "2. Workspace and budget generators "
            "returned in "
            f"{time.monotonic() - ai_started_at:.2f} "
            "seconds."
)

        if generated_workspace is None:
            raise ValueError(
                "Workspace generation returned None."
            )

        project_name = (
            generated_workspace.project_name
            or ""
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

        for section in (
            generated_workspace.sections
        ):
            folder_type = (
                section.folder_type
                or ""
            ).strip().lower()

            content = (
                section.content
                or ""
            ).strip()

            if folder_type not in required_folder_types:
                continue

            if not content:
                continue

            sections_by_type[
                folder_type
            ] = content

        print(
            "3. Parsed "
            f"{len(sections_by_type)} "
            "workspace sections."
        )

        if not generated_workspace.tasks:
            raise ValueError(
                "Workspace generation returned "
                "no tasks."
            )

        # Build detailed documentation from the
        # structured documentation output.
        documentation_parts = []

        for documentation_section in (
            generated_workspace
            .documentation_sections
        ):
            title = (
                documentation_section.title
                or ""
            ).strip()

            content = (
                documentation_section.content
                or ""
            ).strip()

            if not title or not content:
                continue

            section_parts = [
                title,
                content,
            ]

            related_topics = [
                str(topic).strip()
                for topic in (
                    documentation_section
                    .related_topics
                    or []
                )
                if str(topic).strip()
            ]

            if related_topics:
                section_parts.append(
                    "Related topics:\n"
                    + "\n".join(
                        f"- {topic}"
                        for topic
                        in related_topics
                    )
                )

            reference_urls = [
                str(url).strip()
                for url in (
                    documentation_section
                    .reference_urls
                    or []
                )
                if str(url).strip()
            ]

            if reference_urls:
                section_parts.append(
                    "References:\n"
                    + "\n".join(
                        f"- {url}"
                        for url
                        in reference_urls
                    )
                )

            documentation_parts.append(
                "\n\n".join(
                    section_parts
                )
            )

        if documentation_parts:
            sections_by_type[
                "documentation"
            ] = (
                "\n\n"
                + "=" * 60
                + "\n\n"
            ).join(
                documentation_parts
            )

        # The structured documentation replaces the
        # ordinary documentation section. Therefore,
        # documentation does not need to be present in
        # generated_workspace.sections.
        required_text_sections = (
            required_folder_types
            - {
                "documentation",
                "learning",
                "budget",
            }
        )

        missing_sections = (
            required_text_sections
            - set(sections_by_type)
        )

        if missing_sections:
            raise ValueError(
                "AI omitted required workspace "
                "sections: "
                + ", ".join(
                    sorted(
                        missing_sections
                    )
                )
            )

        if not documentation_parts:
            raise ValueError(
                "Workspace generation returned "
                "no documentation sections."
            )

        learning_resource_output = (
            generated_workspace
            .learning_resources
            or []
        )

        if not learning_resource_output:
            raise ValueError(
                "Workspace generation returned "
                "no learning resources."
            )

    
        if generated_budget is None:
            raise ValueError(
                "Budget generation returned None."
            )

        budget_items = (
            build_budget_items_from_ai(
                project=project,
                generated_items=(
                    generated_budget
                    .budget_items
                ),
            )
        )

        if not budget_items:
            raise ValueError(
                "Budget generation returned "
                "no usable budget items."
            )

        budget_summary = (
            generated_budget.summary
            or ""
        ).strip()

        if budget_summary:
            sections_by_type[
                "budget"
            ] = budget_summary

        with transaction.atomic():
            print(
                "6. Starting database transaction."
            )

            existing_folders = {
                folder.folder_type: folder
                for folder
                in project.folders.all()
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
                        name=folder_data[
                            "name"
                        ],
                        folder_type=(
                            folder_type
                        ),
                        order=index,
                    )
                )

            if folders_to_create:
                WorkspaceFolder.objects.bulk_create(
                    folders_to_create
                )

                print(
                    "7. Created "
                    f"{len(folders_to_create)} "
                    "folders."
                )
            else:
                print(
                    "7. No folders needed creation."
                )

            # Reload folders so newly created folders
            # are available with primary keys.
            folders_to_update = list(
                project.folders.all()
            )

            folders_by_type = {
                folder.folder_type: folder
                for folder
                in folders_to_update
            }

            for folder in folders_to_update:
                section_content = (
                    sections_by_type.get(
                        folder.folder_type
                    )
                )

                if section_content is None:
                    continue

                folder.description = (
                    section_content
                )

            if folders_to_update:
                WorkspaceFolder.objects.bulk_update(
                    folders_to_update,
                    ["description"],
                )

            print(
                "8. Updated "
                f"{len(folders_to_update)} "
                "folders."
            )

            learning_folder = (
                folders_by_type.get(
                    "learning"
                )
            )

            if learning_folder is None:
                raise ValueError(
                    "Learning Resources folder "
                    "was not created."
                )

            valid_resource_types = {
                value
                for value, _
                in (
                    ProjectResource
                    .ResourceType
                    .choices
                )
            }

            learning_resources = []

            for order, resource in enumerate(
                learning_resource_output,
                start=1,
            ):
                title = (
                    resource.title
                    or ""
                ).strip()

                if not title:
                    continue

                resource_type = (
                    getattr(
                        resource,
                        "resource_type",
                        (
                            ProjectResource
                            .ResourceType
                            .DOCUMENTATION
                        ),
                    )
                    or (
                        ProjectResource
                        .ResourceType
                        .DOCUMENTATION
                    )
                )

                resource_type = (
                    str(resource_type)
                    .strip()
                    .lower()
                )

                if (
                    resource_type
                    not in valid_resource_types
                ):
                    resource_type = (
                        ProjectResource
                        .ResourceType
                        .DOCUMENTATION
                    )

                learning_resources.append(
                    ProjectResource(
                        project=project,
                        folder=learning_folder,
                        title=title,
                        url=(
                            resource.url
                            or ""
                        ).strip(),
                        description=(
                            resource.description
                            or ""
                        ).strip(),
                        topic=(
                            resource.topic
                            or ""
                        ).strip(),
                        reason_needed=(
                            resource.reason_needed
                            or ""
                        ).strip(),
                        related_task=(
                            resource.related_task
                            or ""
                        ).strip(),
                        difficulty=(
                            resource.difficulty
                            or ""
                        ).strip(),
                        resource_type=(
                            resource_type
                        ),
                        is_official=bool(
                            getattr(
                                resource,
                                "is_official",
                                False,
                            )
                        ),
                        order=order,
                    )
                )

            if not learning_resources:
                raise ValueError(
                    "Workspace generation returned "
                    "no usable learning resources."
                )

            learning_folder.resources.all().delete()

            ProjectResource.objects.bulk_create(
                learning_resources
            )

            print(
                "9. Created "
                f"{len(learning_resources)} "
                "learning resources."
            )

            dependency_count = 0

            if not project.tasks.exists():
                valid_statuses = {
                    value
                    for value, _
                    in Task.Status.choices
                }

                generated_tasks = []
                dependency_indexes_by_order = {}

                for index, generated_task in enumerate(
                    generated_workspace.tasks,
                    start=1,
                ):
                    title = (
                        generated_task.title
                        or ""
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
                                    generated_task
                                    .priority
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

                    raw_dependency_indexes = (
                        getattr(
                            generated_task,
                            (
                                "dependency_"
                                "indexes"
                            ),
                            [],
                        )
                        or []
                    )

                    valid_dependency_indexes = []

                    for dependency_index in (
                        raw_dependency_indexes
                    ):
                        if not isinstance(
                            dependency_index,
                            int,
                        ):
                            continue

                        if dependency_index < 1:
                            continue

                        if dependency_index >= index:
                            continue

                        if (
                            dependency_index
                            in valid_dependency_indexes
                        ):
                            continue

                        valid_dependency_indexes.append(
                            dependency_index
                        )

                    dependency_indexes_by_order[
                        index
                    ] = valid_dependency_indexes

                if not generated_tasks:
                    raise ValueError(
                        "Workspace generation "
                        "returned no valid tasks."
                    )

                Task.objects.bulk_create(
                    generated_tasks
                )

                created_tasks = list(
                    project.tasks.order_by(
                        "order",
                        "pk",
                    )
                )

                tasks_by_order = {
                    task.order: task
                    for task in created_tasks
                }

                for (
                    task_order,
                    dependency_indexes,
                ) in (
                    dependency_indexes_by_order
                    .items()
                ):
                    task = tasks_by_order.get(
                        task_order
                    )

                    if task is None:
                        continue

                    dependencies = [
                        tasks_by_order[
                            dependency_index
                        ]
                        for dependency_index
                        in dependency_indexes
                        if dependency_index
                        in tasks_by_order
                    ]

                    if not dependencies:
                        continue

                    task.dependencies.add(
                        *dependencies
                    )

                    dependency_count += len(
                        dependencies
                    )

                print(
                    "10. Created "
                    f"{len(generated_tasks)} "
                    "tasks with "
                    f"{dependency_count} "
                    "dependencies."
                )

            else:
                dependency_count = (
                    Task.dependencies.through
                    .objects
                    .filter(
                        from_task__project=(
                            project
                        ),
                        to_task__project=(
                            project
                        ),
                    )
                    .count()
                )

                print(
                    "10. Existing tasks "
                    "preserved."
                )

            project.budget_items.all().delete()

            BudgetItem.objects.bulk_create(
                budget_items
            )

            print(
                "11. Created "
                f"{len(budget_items)} "
                "budget and parts-list items."
            )

            project.name = project_name
            project.status = Project.Status.ACTIVE

            project.save(
                update_fields=[
                    "name",
                    "status",
                    "updated_at",
                ]
            )

            print(
                "12. Project saved as active."
            )

            ProjectMembership.objects.get_or_create(
                project=project,
                user=project.owner,
                defaults={
                    "role": (
                        ProjectMembership
                        .Role
                        .OWNER
                    ),
                },
            )

            print(
                "13. Owner membership confirmed."
            )

            ProjectState.objects.get_or_create(
                project=project,
                defaults={
                    "facts": {},
                },
            )

            print(
                "14. Project state confirmed."
            )

            task_count = project.tasks.count()

            dependency_count = (
                Task.dependencies.through
                .objects
                .filter(
                    from_task__project=project,
                    to_task__project=project,
                )
                .count()
            )

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
                    "workspace sections, "
                    f"{task_count} tasks, "
                    f"{dependency_count} task "
                    "dependencies, "
                    f"{len(learning_resources)} "
                    "learning resources, and "
                    f"{len(budget_items)} "
                    "budget items."
                ),
                metadata={
                    "section_count": (
                        len(sections_by_type)
                    ),
                    "task_count": task_count,
                    "dependency_count": (
                        dependency_count
                    ),
                    "learning_resource_count": (
                        len(
                            learning_resources
                        )
                    ),
                    "budget_item_count": (
                        len(budget_items)
                    ),
                },
            )

            print(
                "15. Workspace event recorded."
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

    except Exception as error:
        print("\n" + "=" * 80)
        print("WORKSPACE GENERATION FAILED")
        traceback.print_exc()
        print("=" * 80 + "\n")

        messages.error(
            request,
            (
                "BuilderOS could not generate "
                "the workspace. Please try again."
            ),
        )
        project.status = Project.Status.DRAFT
        project.save(update_fields=["status"])
        capture_event(
            distinct_id=f"user_{request.user.pk}",
            event="workspace_generation_failed",
            properties={
                "project_id": project.pk,
                "project_name": project.name,
            },
        )

        return redirect(
            "project_setup",
            pk=project.pk,
        )
    capture_event(
        distinct_id=f"user_{request.user.pk}",
        event="workspace_generated",
        properties={
            "project_id": project.pk,
            "project_name": project.name,
        },
    )
    return redirect(
        "workspace",
        project_pk=project.pk,
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
def workspace_folder(
    request,
    project_pk,
    folder_pk,
):
    try:
        print("=" * 70)
        print("WORKSPACE FOLDER 1: Loading project")

        project = get_project_for_user(
            project_pk=project_pk,
            user=request.user,
        )

        print("WORKSPACE FOLDER 2: Loading folder")

        folder = get_object_or_404(
            WorkspaceFolder,
            pk=folder_pk,
            project=project,
        )

        print(
            "WORKSPACE FOLDER 3:",
            folder.name,
            folder.folder_type,
        )

        permission_context = (
            project_permission_context(
                project=project,
                user=request.user,
            )
        )

        # Default values for every folder type.
        tasks = None
        resources = None
        budget_items = None
        physical_parts = None
        recurring_items = None

        total_tasks = 0
        completed_tasks = 0
        progress = 0

        estimated_one_time_total = Decimal(
            "0.00"
        )

        estimated_monthly_total = Decimal(
            "0.00"
        )
        labor_total=Decimal("0.00")

        required_total = Decimal("0.00")
        recommended_total = Decimal("0.00")
        optional_total = Decimal("0.00")

        physical_parts_total = Decimal(
            "0.00"
        )

        actual_spent_total = Decimal(
            "0.00"
        )

        budget_variance = Decimal("0.00")

        category_totals = {}
        budget_chart_data = []

        if folder.folder_type == "tasks":
            print(
                "WORKSPACE FOLDER 4: "
                "Loading tasks"
            )

            tasks = (
                project.tasks
                .select_related("milestone")
                .prefetch_related(
                    "dependencies",
                )
                .order_by(
                    "completed",
                    "order",
                    "pk",
                )
            )

            total_tasks = tasks.count()

            completed_tasks = tasks.filter(
                status=Task.Status.DONE,
            ).count()

            if total_tasks:
                progress = round(
                    completed_tasks
                    / total_tasks
                    * 100
                )

        elif folder.folder_type in {
            "learning",
            "resources",
        }:
            print(
                "WORKSPACE FOLDER 4: "
                "Loading resources"
            )

            resources = (
                folder.resources
                .all()
                .order_by(
                    "order",
                    "pk",
                )
            )
        
        elif folder.folder_type == "budget":
            print(
                "WORKSPACE FOLDER 4: "
                "Loading budget"
            )

            budget_items = (
                project.budget_items
                .all()
                .order_by(
                    "order",
                    "pk",
                )
            )

            physical_parts = (
                budget_items.filter(
                    is_physical_part=True,
                )
            )

            recurring_items = (
                budget_items.filter(
                    is_recurring=True,
                )
            )

            for item in budget_items:
                # Uses the upgraded property:
                # quantity * unit_cost
                item_total = (
                    item.estimated_total
                )

                category_name = (
                    item.get_category_display()
                )

                category_totals[
                    category_name
                ] = (
                    category_totals.get(
                        category_name,
                        Decimal("0.00"),
                    )
                    + item_total
                )

                if (
                    item.category
                    == BudgetItem.Category.LABOR
                ):
                    labor_total += item_total

                elif item.is_recurring:
                    estimated_monthly_total += (
                        item_total
                    )

                else:
                    estimated_one_time_total += (
                        item_total
                    )

                if (
                    item.requirement_level
                    == BudgetItem
                    .RequirementLevel
                    .REQUIRED
                ):
                    required_total += item_total

                elif (
                    item.requirement_level
                    == BudgetItem
                    .RequirementLevel
                    .RECOMMENDED
                ):
                    recommended_total += (
                        item_total
                    )

                elif (
                    item.requirement_level
                    == BudgetItem
                    .RequirementLevel
                    .OPTIONAL
                ):
                    optional_total += item_total

                if item.is_physical_part:
                    physical_parts_total += (
                        item_total
                    )

                if item.actual_total is not None:
                    actual_spent_total += (
                        item.actual_total
                    )

            # Compare actual purchases against
            # estimated one-time costs.
            budget_variance = (
                actual_spent_total
                - estimated_one_time_total
            )

            budget_chart_data = [
                {
                    "category": category,
                    "amount": float(amount),
                }
                for category, amount
                in sorted(
                    category_totals.items(),
                    key=lambda pair: pair[1],
                    reverse=True,
                )
            ]

        print(
            "WORKSPACE FOLDER 5: "
            "Rendering template"
        )

        return render(
            request,
            "projects/workspace_folder.html",
            {
                "project": project,
                "folder": folder,

                # Tasks
                "tasks": tasks,
                "total_tasks": total_tasks,
                "completed_tasks": (
                    completed_tasks
                ),
                "progress": progress,

                # Resources
                "resources": resources,

                # Budget records
                "budget_items": budget_items,
                "physical_parts": physical_parts,
                "recurring_items": (
                    recurring_items
                ),

                # Budget totals
                "one_time_total": (
                    estimated_one_time_total
                ),
                "monthly_total": (
                    estimated_monthly_total
                ),
                "required_total": required_total,
                "recommended_total": (
                    recommended_total
                ),
                "optional_total": optional_total,
                "physical_parts_total": (
                    physical_parts_total
                ),
                "actual_spent_total": (
                    actual_spent_total
                ),
                "budget_variance": (
                    budget_variance
                ),
                "labor_total": (
                    labor_total
                ),

                # Chart
                "budget_chart_data": (
                    budget_chart_data
                ),

                **permission_context,
            },
        )

    except Exception:
        print("\n" + "=" * 80)
        print("WORKSPACE FOLDER PAGE FAILED")
        traceback.print_exc()
        print("=" * 80 + "\n")
        raise
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

    changes = (
        project.changes
        .all()
        .order_by("-created_at")
    )

    permission_context = (
        project_permission_context(
            project=project,
            user=request.user,
        )
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
def project_change_detail(
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

    facts_before = change.facts_before or {}
    facts_after = change.facts_after or {}

    fact_keys = sorted(
        set(facts_before.keys())
        | set(facts_after.keys())
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
        set(sections_before.keys())
        | set(sections_after.keys())
    )

    section_changes = []

    for section_type in section_keys:
        before_content = sections_before.get(
            section_type,
            "",
        )

        after_content = sections_after.get(
            section_type,
            "",
        )

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
        before_task = before_tasks_by_title.get(
            task_key
        )

        after_task = after_tasks_by_title.get(
            task_key
        )

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

    permission_context = (
        project_permission_context(
            project=project,
            user=request.user,
        )
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
def escape_mermaid_text(value):
    return (
        str(value)
        .replace('"', "'")
        .replace("\n", " ")
        .replace("[", "(")
        .replace("]", ")")
        .strip()
    )


def build_task_flowchart(project):
    tasks = list(
        project.tasks
        .prefetch_related("dependencies")
        .order_by("order", "pk")
    )

    if not tasks:
        return ""

    lines = [
        "flowchart TD",
    ]

    status_classes = {
        Task.Status.TODO: "todo",
        Task.Status.IN_PROGRESS: "inProgress",
        Task.Status.REVIEW: "review",
        Task.Status.DONE: "done",
    }

    task_ids = {
        task.pk
        for task in tasks
    }

    for task in tasks:
        safe_title = escape_mermaid_text(
            task.title
        )

        lines.append(
            f'T{task.pk}["{safe_title}"]'
        )

        class_name = status_classes.get(
            task.status,
            "todo",
        )

        lines.append(
            f"class T{task.pk} {class_name}"
        )

    connection_count = 0

    for task in tasks:
        for dependency in task.dependencies.all():
            if dependency.pk not in task_ids:
                continue

            lines.append(
                f"T{dependency.pk} --> T{task.pk}"
            )

            connection_count += 1

    # If no dependencies exist yet, show tasks
    # sequentially using their current order.
    if connection_count == 0:
        for previous_task, next_task in zip(
            tasks,
            tasks[1:],
        ):
            lines.append(
                f"T{previous_task.pk} --> "
                f"T{next_task.pk}"
            )

    lines.extend(
        [
            (
                "classDef todo "
                "fill:#f8fafc,"
                "stroke:#64748b,"
                "color:#0f172a"
            ),
            (
                "classDef inProgress "
                "fill:#dbeafe,"
                "stroke:#2563eb,"
                "color:#1e3a8a"
            ),
            (
                "classDef review "
                "fill:#fef3c7,"
                "stroke:#d97706,"
                "color:#78350f"
            ),
            (
                "classDef done "
                "fill:#dcfce7,"
                "stroke:#16a34a,"
                "color:#14532d"
            ),
        ]
    )

    return "\n".join(lines)
@login_required
def project_timeline(
    request,
    project_pk,
):
    try:
        print("TIMELINE 1: Loading project")

        project = get_project_for_user(
            project_pk=project_pk,
            user=request.user,
        )

        print("TIMELINE 2: Loading milestones")

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

        print("TIMELINE 3: Loading unscheduled tasks")

        unscheduled_tasks = (
            project.tasks
            .filter(milestone__isnull=True)
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

        print("TIMELINE 4: Loading all tasks")

        all_tasks = list(
            project.tasks
            .prefetch_related(
                "dependencies",
                "dependents",
            )
            .order_by("order", "pk")
        )

        print("TIMELINE 5: Checking blocked tasks")

        blocked_tasks = [
            task
            for task in all_tasks
            if task.is_blocked
        ]

        print("TIMELINE 6: Checking overdue tasks")

        overdue_tasks = [
            task
            for task in all_tasks
            if task.is_overdue
        ]

        print("TIMELINE 7: Building flowchart")

        task_flowchart = build_task_flowchart(
            project
        )

        print(
            "TIMELINE 8: Flowchart built:",
            len(task_flowchart),
            "characters",
        )

        schedule_message = request.session.pop(
            "schedule_message",
            None,
        )

        schedule_message_type = request.session.pop(
            "schedule_message_type",
            None,
        )

        permission_context = (
            project_permission_context(
                project=project,
                user=request.user,
            )
        )

        print("TIMELINE 9: Rendering template")

        return render(
            request,
            "projects/project_timeline.html",
            {
                "project": project,
                "milestones": milestones,
                "unscheduled_tasks": (
                    unscheduled_tasks
                ),
                "blocked_tasks": blocked_tasks,
                "overdue_tasks": overdue_tasks,
                "schedule_message": (
                    schedule_message
                ),
                "schedule_message_type": (
                    schedule_message_type
                ),
                "task_flowchart": task_flowchart,
                **permission_context,
            },
        )

    except Exception:
        print("\n" + "=" * 80)
        print("TIMELINE PAGE FAILED")
        traceback.print_exc()
        print("=" * 80 + "\n")
        raise
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

    username = request.POST.get(
        "username",
        "",
    ).strip()

    role = request.POST.get(
        "role",
        ProjectMembership.Role.VIEWER,
    )

    if not username:
        messages.error(
            request,
            "Enter a username.",
        )

        return redirect(
            "project_members",
            project_pk=project.pk,
        )

    allowed_roles = {
        ProjectMembership.Role.EDITOR,
        ProjectMembership.Role.VIEWER,
    }

    if role not in allowed_roles:
        role = ProjectMembership.Role.VIEWER

    invited_user = (
        User.objects
        .filter(
            username__iexact=username,
        )
        .first()
    )

    if invited_user is None:
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
            (
                f"{invited_user.username} "
                "was added to the project."
            ),
        )

        record_project_event(
            project=project,
            event_type=(
                ProjectEvent.EventType
                .MEMBER_ADDED
            ),
            title="Project member added",
            description=(
                f"{invited_user.username} "
                f"was added as {membership.get_role_display()}."
            ),
            metadata={
                "membership_id": membership.pk,
                "user_id": invited_user.pk,
                "username": invited_user.username,
                "role": membership.role,
            },
        )

    else:
        messages.success(
            request,
            (
                f"{invited_user.username}'s "
                "role was updated."
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
def escape_mermaid_text(value):
    return (
        str(value)
        .replace('"', "'")
        .replace("\n", " ")
        .replace("[", "(")
        .replace("]", ")")
        .strip()
    )


def build_task_flowchart(project):
    tasks = list(
        project.tasks
        .prefetch_related("dependencies")
        .order_by("order", "pk")
    )

    if not tasks:
        return ""

    lines = [
        "flowchart TD",
    ]

    status_classes = {
        Task.Status.TODO: "todo",
        Task.Status.IN_PROGRESS: "inProgress",
        Task.Status.REVIEW: "review",
        Task.Status.DONE: "done",
    }

    task_ids = {
        task.pk
        for task in tasks
    }

    for task in tasks:
        safe_title = escape_mermaid_text(
            task.title
        )

        lines.append(
            f'T{task.pk}["{safe_title}"]'
        )

        class_name = status_classes.get(
            task.status,
            "todo",
        )

        lines.append(
            f"class T{task.pk} {class_name}"
        )

    connection_count = 0

    for task in tasks:
        for dependency in task.dependencies.all():
            if dependency.pk not in task_ids:
                continue

            lines.append(
                f"T{dependency.pk} --> T{task.pk}"
            )

            connection_count += 1

    # If no dependencies exist yet, show tasks
    # sequentially using their current order.
    if connection_count == 0:
        for previous_task, next_task in zip(
            tasks,
            tasks[1:],
        ):
            lines.append(
                f"T{previous_task.pk} --> "
                f"T{next_task.pk}"
            )

    lines.extend(
        [
            (
                "classDef todo "
                "fill:#f8fafc,"
                "stroke:#64748b,"
                "color:#0f172a"
            ),
            (
                "classDef inProgress "
                "fill:#dbeafe,"
                "stroke:#2563eb,"
                "color:#1e3a8a"
            ),
            (
                "classDef review "
                "fill:#fef3c7,"
                "stroke:#d97706,"
                "color:#78350f"
            ),
            (
                "classDef done "
                "fill:#dcfce7,"
                "stroke:#16a34a,"
                "color:#14532d"
            ),
        ]
    )

    return "\n".join(lines)
def build_task_flowchart(project):
    tasks = list(
        project.tasks
        .prefetch_related(
            "dependencies",
        )
        .order_by(
            "order",
            "pk",
        )
    )

    if not tasks:
        return ""

    lines = [
        "flowchart LR",
    ]

    task_ids = {
        task.pk
        for task in tasks
    }

    for task in tasks:
        safe_title = escape_mermaid_text(
            task.title
        )

        status_label = (
            task.get_status_display()
        )

        priority_label = (
            task.get_priority_display()
        )

        node_label = (
            f"{safe_title}<br/>"
            f"{status_label} · "
            f"{priority_label}"
        )

        lines.append(
            f'T{task.pk}["{node_label}"]'
        )

        task_url = reverse(
            "edit_task",
            kwargs={
                "project_pk": project.pk,
                "task_pk": task.pk,
            },
        )

        lines.append(
            f'click T{task.pk} "{task_url}" '
            f'"Open {safe_title}"'
        )

    connection_count = 0

    for task in tasks:
        for dependency in (
            task.dependencies.all()
        ):
            if dependency.pk not in task_ids:
                continue

            lines.append(
                f"T{dependency.pk} --> "
                f"T{task.pk}"
            )

            connection_count += 1

    if connection_count == 0:
        lines.append(
            'NO_DEPS["No dependencies '
            'have been defined yet"]'
        )

        lines.append(
            "class NO_DEPS empty"
        )

    for task in tasks:
        if task.status == Task.Status.DONE:
            classes = ["done"]

        elif task.status == (
            Task.Status.IN_PROGRESS
        ):
            classes = ["inProgress"]

        elif task.status == Task.Status.REVIEW:
            classes = ["review"]

        else:
            classes = ["todo"]

        if task.is_blocked:
            classes.append("blocked")

        lines.append(
            f"class T{task.pk} "
            + ",".join(classes)
        )

    lines.extend(
        [
            (
                "classDef todo "
                "fill:#334155,"
                "stroke:#64748b,"
                "stroke-width:2px,"
                "color:#f8fafc"
            ),
            (
                "classDef inProgress "
                "fill:#1d4ed8,"
                "stroke:#60a5fa,"
                "stroke-width:2px,"
                "color:#ffffff"
            ),
            (
                "classDef review "
                "fill:#92400e,"
                "stroke:#f59e0b,"
                "stroke-width:2px,"
                "color:#ffffff"
            ),
            (
                "classDef done "
                "fill:#166534,"
                "stroke:#4ade80,"
                "stroke-width:2px,"
                "color:#ffffff"
            ),
            (
                "classDef blocked "
                "stroke:#ef4444,"
                "stroke-width:4px,"
                "stroke-dasharray:6 3"
            ),
            (
                "classDef empty "
                "fill:#1e293b,"
                "stroke:#64748b,"
                "color:#cbd5e1"
            ),
        ]
    )

    return "\n".join(lines)

@login_required
@require_POST
def regenerate_project_budget(
    request,
    project_pk,
):
    project = get_editable_project_for_user(
        project_pk=project_pk,
        user=request.user,
    )

    budget_folder = get_object_or_404(
        WorkspaceFolder,
        project=project,
        folder_type="budget",
    )

    try:
        generated_budget = generate_project_budget(
            project
        )

        budget_items = build_budget_items_from_ai(
            project=project,
            generated_items=(
                generated_budget.budget_items
            ),
        )

        if not budget_items:
            raise ValueError(
                "Budget generation returned "
                "no usable budget items."
            )

        with transaction.atomic():
            project.budget_items.all().delete()

            BudgetItem.objects.bulk_create(
                budget_items
            )

            budget_folder.description = (
                generated_budget.summary or ""
            ).strip()

            budget_folder.save(
                update_fields=[
                    "description",
                    "updated_at",
                ]
            )

            record_project_event(
                project=project,
                event_type=(
                    ProjectEvent.EventType
                    .WORKSPACE_UPDATED
                ),
                title=(
                    "Budget and parts list "
                    "regenerated"
                ),
                description=(
                    f"Generated "
                    f"{len(budget_items)} "
                    "budget items."
                ),
                metadata={
                    "folder_id": budget_folder.pk,
                    "folder_type": (
                        budget_folder.folder_type
                    ),
                    "item_count": len(
                        budget_items
                    ),
                },
            )

        mark_schedule_for_refresh(
            project=project,
            reason=(
                "The budget and parts list "
                "were regenerated."
            ),
        )

        messages.success(
            request,
            (
                "Budget and parts list "
                "were regenerated successfully."
            ),
        )

    except Exception:
        print("\n" + "=" * 80)
        print(
            "BUDGET AND PARTS LIST "
            "REGENERATION FAILED"
        )
        traceback.print_exc()
        print("=" * 80 + "\n")

        messages.error(
            request,
            (
                "Projivo could not regenerate "
                "the budget and parts list. "
                "Please try again."
            ),
        )

    return redirect(
        "workspace_folder",
        project_pk=project.pk,
        folder_pk=budget_folder.pk,
    )
def home(request):
    if request.user.is_authenticated:
        return render(
            request,
            "projects/home.html",
        )

    return render(
        request,
        "projects/home.html",
    )