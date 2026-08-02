from posthog import Posthog

from django.conf import settings


posthog_client = None

if settings.POSTHOG_KEY:
    posthog_client = Posthog(
        settings.POSTHOG_KEY,
        host=settings.POSTHOG_HOST,
    )


def capture_event(
    *,
    distinct_id,
    event,
    properties=None,
):
    if posthog_client is None:
        return

    try:
        posthog_client.capture(
            event,
            distinct_id=str(distinct_id),
            properties=properties or {},
        )

    except Exception as error:
        print(
            "PostHog capture failed:",
            type(error).__name__,
        )