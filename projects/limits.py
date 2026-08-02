from .models import Project

CORE_ACTIVE_PROJECT_LIMIT = 3


def get_active_project_limit(user):
    return CORE_ACTIVE_PROJECT_LIMIT


def get_owned_active_project_count(user):
    return (
        Project.objects
        .filter(
            owner=user,
            status=Project.Status.ACTIVE,
        )
        .count()
    )


def can_create_project(user):
    return (
        get_owned_active_project_count(user)
        < get_active_project_limit(user)
    )