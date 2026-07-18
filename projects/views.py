from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from .models import Project
from .models import Project


def project_list(request):
    return HttpResponse("Project List")


@login_required
def new_project(request):
    project = Project.objects.create(
        owner=request.user,
        status=Project.Status.DRAFT,
    )

    return redirect("project_setup", pk=project.pk)


@login_required
from django.shortcuts import render

@login_required
def project_setup(request, pk):

    project = Project.objects.get(pk=pk)

    return render(
        request,
        "projects/setup.html",
        {
            "project": project,
        },
    )