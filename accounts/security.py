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
        return forwarded_for.split(",")[0].strip()

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
        key=f"signup-attempt-hour:{ip_address}",
        timeout=60 * 60,
    )

    daily_count = increment_counter(
        key=f"signup-attempt-day:{ip_address}",
        timeout=60 * 60 * 24,
    )

    return (
        hourly_count
        > SIGNUP_ATTEMPTS_PER_HOUR
        or daily_count
        > SIGNUP_ATTEMPTS_PER_DAY
    )


def record_successful_signup(request):
    ip_address = get_client_ip(request)

    return increment_counter(
        key=f"signup-success-day:{ip_address}",
        timeout=60 * 60 * 24,
    )


def too_many_successful_signups(request):
    ip_address = get_client_ip(request)

    count = cache.get(
        f"signup-success-day:{ip_address}",
        0,
    )

    return count >= SUCCESSFUL_SIGNUPS_PER_DAY