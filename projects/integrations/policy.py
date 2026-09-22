import re


class ConnectedAppPermissionError(Exception):
    pass


GITHUB_ALLOWED_PATTERNS = [
    # Account information
    (
        "GET",
        re.compile(r"^/user$"),
    ),

    # User repositories
    (
        "GET",
        re.compile(r"^/user/repos$"),
    ),
    (
        "POST",
        re.compile(r"^/user/repos$"),
    ),

    # Repository information/settings
    (
        "GET",
        re.compile(
            r"^/repos/[^/]+/[^/]+$"
        ),
    ),
    (
        "PATCH",
        re.compile(
            r"^/repos/[^/]+/[^/]+$"
        ),
    ),

    # Issues
    (
        "GET",
        re.compile(
            r"^/repos/[^/]+/[^/]+/issues$"
        ),
    ),
    (
        "POST",
        re.compile(
            r"^/repos/[^/]+/[^/]+/issues$"
        ),
    ),
    (
        "GET",
        re.compile(
            r"^/repos/[^/]+/[^/]+/issues/\d+$"
        ),
    ),
    (
        "PATCH",
        re.compile(
            r"^/repos/[^/]+/[^/]+/issues/\d+$"
        ),
    ),

    # Repository contents
    (
        "GET",
        re.compile(
            r"^/repos/[^/]+/[^/]+/contents(?:/.*)?$"
        ),
    ),
    (
        "PUT",
        re.compile(
            r"^/repos/[^/]+/[^/]+/contents/.+$"
        ),
    ),

    # Branch information
    (
        "GET",
        re.compile(
            r"^/repos/[^/]+/[^/]+/branches(?:/[^/]+)?$"
        ),
    ),

    # Branch protection
    (
        "GET",
        re.compile(
            r"^/repos/[^/]+/[^/]+/"
            r"branches/[^/]+/protection$"
        ),
    ),
    (
        "PUT",
        re.compile(
            r"^/repos/[^/]+/[^/]+/"
            r"branches/[^/]+/protection$"
        ),
    ),
    (
    "GET",
    re.compile(
        r"^/repos/[^/]+/[^/]+/git/trees/[^/?]+"
        r"(?:\?recursive=1)?$"
    ),
),
(
    "GET",
    re.compile(
        r"^/repos/[^/]+/[^/]+/labels$"
    ),
),
(
    "GET",
    re.compile(
        r"^/repos/[^/]+/[^/]+/issues"
        r"(?:\?state=(?:open|closed|all))?$"
    ),
),
(
    "GET",
    re.compile(
        r"^/repos/[^/]+/[^/]+/commits/[^/?]+$"
    ),
),
(
    "GET",
    re.compile(
        r"^/repos/[^/]+/[^/]+/git/commits/[^/?]+$"
    ),
),
# All/revision-specific workflow runs
(
    "GET",
    re.compile(
        r"^/repos/[^/]+/[^/]+/actions/runs"
        r"(?:\?"
        r"(?:"
        r"head_sha=[A-Fa-f0-9]{7,64}"
        r"(?:&per_page=\d{1,3})?"
        r"|"
        r"per_page=\d{1,3}"
        r")"
        r")?$"
    ),
),

# Runs belonging to a specific workflow
(
    "GET",
    re.compile(
        r"^/repos/[^/]+/[^/]+/actions/workflows/"
        r"[^/?]+/runs"
        r"(?:\?per_page=\d{1,3})?$"
    ),
),

# Jobs belonging to a specific run
(
    "GET",
    re.compile(
        r"^/repos/[^/]+/[^/]+/actions/runs/"
        r"\d+/jobs"
        r"(?:\?per_page=\d{1,3})?$"
    ),
),
]

 
def validate_connected_app_request(
    *,
    provider,
    method,
    path,
):
    provider = provider.lower()
    method = method.upper()

    if not path.startswith("/"):
        raise ConnectedAppPermissionError(
            "Connected app path must begin with '/'."
        )

    if "://" in path or path.startswith("//"):
        raise ConnectedAppPermissionError(
            "Absolute external URLs are not allowed."
        )

    if ".." in path:
        raise ConnectedAppPermissionError(
            "Parent-path traversal is not allowed."
        )

    if method == "DELETE":
        raise ConnectedAppPermissionError(
            "DELETE requests are not permitted "
            "for autonomous agents."
        )

    if provider != "github":
        raise ConnectedAppPermissionError(
            f"Provider is not currently allowed: "
            f"{provider}"
        )

    for allowed_method, pattern in (
        GITHUB_ALLOWED_PATTERNS
    ):
        if (
            method == allowed_method
            and pattern.fullmatch(path)
        ):
            return

    raise ConnectedAppPermissionError(
        "The agent is not permitted to make "
        f"{method} {path} on {provider}."
    )