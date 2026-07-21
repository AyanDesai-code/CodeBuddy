from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from .ai.services import generate_reply,generate_workspace_content,regenerate_workspace_section, generate_additional_tasks 
from .models import Project, ProjectMessage, WorkspaceFolder, Task
from django.views.decorators.http import require_POST

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

    return render(
        request,
        "projects/workspace.html",
        {
            "project": project,
            "folders": folders,
        },
    )
@login_required
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
    task.save(update_fields=["completed", "updated_at"])

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

            new_tasks.append(
                Task(
                    project=project,
                    title=title,
                    description=description,
                    priority=priority,
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