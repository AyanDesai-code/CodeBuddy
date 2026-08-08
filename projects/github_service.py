import time

import jwt
import requests

from django.conf import settings


GITHUB_API_URL = (
    "https://api.github.com"
)


def create_github_app_jwt():
    now = int(
        time.time()
    )

    payload = {
        "iat": now - 60,
        "exp": now + 540,
        "iss": settings.GITHUB_APP_ID,
    }

    return jwt.encode(
        payload,
        settings.GITHUB_APP_PRIVATE_KEY,
        algorithm="RS256",
    )


def get_installation_token(
    installation_id,
):
    app_jwt = (
        create_github_app_jwt()
    )

    response = requests.post(
        (
            f"{GITHUB_API_URL}"
            f"/app/installations/"
            f"{installation_id}"
            "/access_tokens"
        ),
        headers={
            "Authorization": (
                f"Bearer {app_jwt}"
            ),
            "Accept": (
                "application/vnd.github+json"
            ),
            "X-GitHub-Api-Version": (
                "2022-11-28"
            ),
        },
        timeout=20,
    )

    response.raise_for_status()

    return response.json()[
        "token"
    ]

def create_github_issue_for_task(
    *,
    github_repository,
    task,
):
    token = get_installation_token(
        github_repository.installation_id
    )

    body_parts = []

    if task.description:
        body_parts.append(
            task.description
        )

    body_parts.append(
        "\n---\n"
        "Created from Projivo."
    )

    response = requests.post(
        (
            f"{GITHUB_API_URL}"
            f"/repos/"
            f"{github_repository.owner}/"
            f"{github_repository.name}"
            "/issues"
        ),
        headers={
            "Authorization": (
                f"Bearer {token}"
            ),
            "Accept": (
                "application/vnd.github+json"
            ),
            "X-GitHub-Api-Version": (
                "2022-11-28"
            ),
        },
        json={
            "title": task.title,
            "body": "\n".join(
                body_parts
            ),
        },
        timeout=20,
    )

    response.raise_for_status()

    return response.json()
import hashlib
import hmac


def verify_github_webhook(
    *,
    body,
    signature,
):
    secret = (
        settings.GITHUB_WEBHOOK_SECRET
        .encode("utf-8")
    )

    expected = (
        "sha256="
        + hmac.new(
            secret,
            body,
            hashlib.sha256,
        ).hexdigest()
    )

    return hmac.compare_digest(
        expected,
        signature,
    )