from projects.models import ConnectedAccount

from .base import IntegrationError
from .github import GitHubIntegration


INTEGRATIONS = {
    ConnectedAccount.Provider.GITHUB: (
        GitHubIntegration
    ),
}


def get_integration(account):
    integration_class = INTEGRATIONS.get(
        account.provider
    )

    if not integration_class:
        raise IntegrationError(
            "No integration registered for "
            f"provider '{account.provider}'."
        )

    return integration_class(account)


def get_user_integration(
    *,
    user,
    provider,
):
    account = (
        ConnectedAccount.objects
        .filter(
            user=user,
            provider=provider,
        )
        .order_by("-updated_at")
        .first()
    )

    if not account:
        raise IntegrationError(
            f"{provider} is not connected."
        )

    return get_integration(account)