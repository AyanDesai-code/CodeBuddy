from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .models import Project, ProjectMessage


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

            lower = content.lower()

            if "robot" in lower:
                reply = (
                    "That sounds like an awesome robotics project! "
                    "Will it be autonomous or remotely controlled?"
                )

            elif "website" in lower:
                reply = "Great! Who will be using this website?"

            elif "app" in lower:
                reply = (
                    "Nice! Will this be a web app, mobile app, or desktop app?"
                )

            else:
                reply = (
                    "That sounds interesting! "
                    "Tell me a little more about your idea."
                )

            ProjectMessage.objects.create(
                project=project,
                role=ProjectMessage.Role.ASSISTANT,
                content=reply,
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