from django.conf import settings
from django.core.cache import cache


SIGNUP_ATTEMPTS_PER_HOUR = 5
SIGNUP_ATTEMPTS_PER_DAY = 15
SUCCESSFUL_SIGNUPS_PER_DAY = 5


def get_client_ip(request):
    forwarded_for = request.META.get(
        "HTTP_X_FORWARDED_FOR",
        "",
    )

    if forwarded_for:
        return (
            forwarded_for
            .split(",")[0]
            .strip()
        )

    return request.META.get(
        "REMOTE_ADDR",
        "unknown",
    )


def increment_counter(
    *,
    key,
    timeout,
):
    created = cache.add(
        key,
        1,
        timeout=timeout,
    )

    if created:
        return 1

    try:
        return cache.incr(key)
    except ValueError:
        cache.set(
            key,
            1,
            timeout=timeout,
        )
        return 1


def signup_is_rate_limited(request):
    ip_address = get_client_ip(request)

    hourly_count = increment_counter(
        key=(
            f"signup-attempt-hour:"
            f"{ip_address}"
        ),
        timeout=60 * 60,
    )

    daily_count = increment_counter(
        key=(
            f"signup-attempt-day:"
            f"{ip_address}"
        ),
        timeout=60 * 60 * 24,
    )

    print(
        "SIGNUP LIMIT CHECK:",
        {
            "backend": (
                settings.CACHES[
                    "default"
                ]["BACKEND"]
            ),
            "ip": ip_address,
            "hourly_count": hourly_count,
            "daily_count": daily_count,
            "hourly_limit": (
                SIGNUP_ATTEMPTS_PER_HOUR
            ),
            "daily_limit": (
                SIGNUP_ATTEMPTS_PER_DAY
            ),
        },
        flush=True,
    )

    return (
        hourly_count
        > SIGNUP_ATTEMPTS_PER_HOUR
        or daily_count
        > SIGNUP_ATTEMPTS_PER_DAY
    )


def record_successful_signup(request):
    ip_address = get_client_ip(request)

    count = increment_counter(
        key=(
            f"signup-success-day:"
            f"{ip_address}"
        ),
        timeout=60 * 60 * 24,
    )

    print(
        "SUCCESSFUL SIGNUP RECORDED:",
        {
            "ip": ip_address,
            "count": count,
        },
        flush=True,
    )

    return count


def too_many_successful_signups(request):
    ip_address = get_client_ip(request)

    count = cache.get(
        (
            f"signup-success-day:"
            f"{ip_address}"
        ),
        0,
    )

    print(
        "SUCCESSFUL SIGNUP LIMIT CHECK:",
        {
            "ip": ip_address,
            "count": count,
            "limit": (
                SUCCESSFUL_SIGNUPS_PER_DAY
            ),
        },
        flush=True,
    )

    return (
        count
        >= SUCCESSFUL_SIGNUPS_PER_DAY
    )