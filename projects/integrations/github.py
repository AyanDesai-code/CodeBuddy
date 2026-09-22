from datetime import timedelta

from django.http import response
import requests

from django.conf import settings
from django.utils import timezone

from projects.models import ConnectedAccount

from .base import (
    BaseIntegration,
    IntegrationError,
)


class GitHubIntegration(BaseIntegration):
    provider = ConnectedAccount.Provider.GITHUB
    base_url = "https://api.github.com"

    def token_is_expiring(self):
        expires_at = (
            self.account.access_token_expires_at
        )

        if not expires_at:
            return False

        return expires_at <= (
            timezone.now()
            + timedelta(minutes=2)
        )

    def refresh_access_token(self):
        if not self.account.refresh_token:
            raise IntegrationError(
                "GitHub access token expired and "
                "no refresh token is available."
            )
            
        response = requests.post(
            (
                "https://github.com/"
                "login/oauth/access_token"
            ),
            data={
                "client_id": (
                    settings.GITHUB_APP_CLIENT_ID
                ),
                "client_secret": (
                    settings.GITHUB_APP_CLIENT_SECRET
                ),
                "grant_type": "refresh_token",
                "refresh_token": (
                    self.account.refresh_token
                ),
            },
            headers={
                "Accept": "application/json",
            },
            timeout=20,
        )

        if not response.ok:
            raise IntegrationError(
                "Unable to refresh GitHub token: "
                f"{response.status_code} "
                f"{response.text[:500]}"
            )

        data = response.json()

        access_token = data.get(
            "access_token"
        )

        if not access_token:
            raise IntegrationError(
                "GitHub refresh response did not "
                "contain an access token."
            )

        self.account.access_token = (
            access_token
        )

        refresh_token = data.get(
            "refresh_token"
        )

        if refresh_token:
            self.account.refresh_token = (
                refresh_token
            )

        expires_in = data.get(
            "expires_in"
        )

        if expires_in:
            self.account.access_token_expires_at = (
                timezone.now()
                + timedelta(
                    seconds=int(expires_in)
                )
            )
        else:
            self.account.access_token_expires_at = (
                None
            )

        refresh_expires_in = data.get(
            "refresh_token_expires_in"
        )

        if refresh_expires_in:
            self.account.refresh_token_expires_at = (
                timezone.now()
                + timedelta(
                    seconds=int(
                        refresh_expires_in
                    )
                )
            )

        self.account.token_type = data.get(
            "token_type",
            self.account.token_type,
        )

        self.account.scope = data.get(
            "scope",
            self.account.scope,
        )

        self.account.save(
            update_fields=[
                "access_token",
                "refresh_token",
                "access_token_expires_at",
                "refresh_token_expires_at",
                "token_type",
                "scope",
                "updated_at",
            ]
        )

        return self.account.access_token

    def get_access_token(self):
        if not self.account.access_token:
            raise IntegrationError(
                "GitHub account has no "
                "access token."
            )

        if self.token_is_expiring():
            return self.refresh_access_token()

        return self.account.access_token

    def request(
        self,
        method,
        path,
        *,
        params=None,
        json=None,
    ):
        if not path.startswith("/"):
            path = "/" + path

        token = self.get_access_token()

        response = requests.request(
            method=method.upper(),
            url=self.base_url + path,
            headers={
                "Accept": (
                    "application/"
                    "vnd.github+json"
                ),
                "Authorization": (
                    f"Bearer {token}"
                ),
                "User-Agent": "Projivo",
            },
            params=params,
            json=json,
            timeout=30,
        )

        if response.status_code == 204:
            return None

        if not response.ok:
            accepted_permissions = (
                response.headers.get(
                    "X-Accepted-GitHub-Permissions",
                    "",
                )
            )

            oauth_scopes = (
                response.headers.get(
                    "X-OAuth-Scopes",
                    "",
                )
            )

            raise IntegrationError(
                "GitHub API request failed: "
                f"{response.status_code} "
                f"{response.text[:1000]} "
                "| accepted_permissions="
                f"{accepted_permissions!r} "
                "| oauth_scopes="
                f"{oauth_scopes!r}"
            )

        try:
            return response.json()

        except ValueError:
            return {
                "text": response.text
            }

    def get_authenticated_user(self):
        return self.request(
            "GET",
            "/user",
        )

    def create_repository(
        self,
        *,
        name,
        description="",
        private=True,
    ):
        return self.request(
            "POST",
            "/user/repos",
            json={
                "name": name,
                "description": description,
                "private": private,
                "has_issues": True,
                "has_projects": False,
                "has_wiki": False,
            },
        )
    