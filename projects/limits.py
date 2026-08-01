CORE_ACTIVE_PROJECT_LIMIT = 3


def get_active_project_limit(user):
    # Later:
    # if user.account.has_agentic_access:
    #     return 50

    return CORE_ACTIVE_PROJECT_LIMIT


def get_owned_active_project_count(user):
    return (
        user.projects
        .exclude(
            status="archived",
        )
        .count()
    )


def can_create_project(user):
    return (
        get_owned_active_project_count(user)
        < get_active_project_limit(user)
    )