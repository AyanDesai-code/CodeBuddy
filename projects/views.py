from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from .ai.services import generate_reply,generate_workspace_content
from .models import Project, ProjectMessage, WorkspaceFolder
from django.views.decorators.http import require_POST

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
                for index, folder in enumerate(default_folders, start=1)
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
            folder.save(update_fields=["description"])

    except Exception as error:
        print("Workspace generation failed:", error)
        return redirect("project_setup", pk=project.pk)

    project.status = Project.Status.ACTIVE
    project.save(update_fields=["name", "status"])

    return redirect("workspace", pk=project.pk)
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

    return render(
        request,
        "projects/workspace_folder.html",
        {
            "project": project,
            "folder": folder,
        },
    )