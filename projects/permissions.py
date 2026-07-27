from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from .models import Project, ProjectMembership


def get_project_for_user(
    *,
    project_pk,
    user,
):
    return get_object_or_404(
        Project.objects.filter(
            Q(owner=user)
            | Q(memberships__user=user)
        ).distinct(),
        pk=project_pk,
    )
def get_editable_project_for_user(
    *,
    project_pk,
    user,
):
    return get_object_or_404(
        Project.objects.filter(
            Q(owner=user)
            | Q(
                memberships__user=user,
                memberships__role__in=[
                    ProjectMembership.Role.OWNER,
                    ProjectMembership.Role.EDITOR,
                ],
            )
        ).distinct(),
        pk=project_pk,
    )

def get_owned_project_for_user(
    *,
    project_pk,
    user,
    **filters,
):
    return get_object_or_404(
        Project.objects.filter(
            owner=user,
            **filters,
        ),
        pk=project_pk,
    )


def user_can_edit_project(
    *,
    project,
    user,
):
    return project.memberships.filter(
        user=user,
        role__in=[
            ProjectMembership.Role.OWNER,
            ProjectMembership.Role.EDITOR,
        ],
    ).exists()


def user_is_project_owner(
    *,
    project,
    user,
):
    return project.memberships.filter(
        user=user,
        role=ProjectMembership.Role.OWNER,
    ).exists()


def require_project_editor(
    *,
    project,
    user,
):
    if not user_can_edit_project(
        project=project,
        user=user,
    ):
        raise PermissionDenied


def require_project_owner(
    *,
    project,
    user,
):
    if not user_is_project_owner(
        project=project,
        user=user,
    ):
        raise PermissionDenied

def project_permission_context(
    *,
    project,
    user,
):
    membership = (
        project.memberships
        .filter(user=user)
        .first()
    )

    can_edit = (
        membership is not None
        and membership.role
        in [
            ProjectMembership.Role.OWNER,
            ProjectMembership.Role.EDITOR,
        ]
    )

    is_owner = (
        membership is not None
        and membership.role
        == ProjectMembership.Role.OWNER
    )

    return {
        "membership": membership,
        "can_edit": can_edit,
        "is_owner": is_owner,
    }