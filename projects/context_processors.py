from django.conf import settings
from django.core.serializers import python


def analytics(request):
    return {
        "POSTHOG_KEY": settings.POSTHOG_KEY,
        "POSTHOG_HOST": settings.POSTHOG_HOST,
    }

from .models import ProjectMembership


def current_project_membership(request):
    if not request.user.is_authenticated:
        return {
            "current_project_membership": None,
        }

    project = getattr(request, "project", None)

    if project is None:
        return {
            "current_project_membership": None,
        }

    membership = (
        ProjectMembership.objects
        .filter(
            project=project,
            user=request.user,
        )
        .select_related("project_role")
        .first()
    )

    return {
        "current_project_membership": membership,
    }

