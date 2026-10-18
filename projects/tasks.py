import os
import time

from celery import shared_task
from django.conf import settings


@shared_task
def execute_agent_run_task(run_id):
    if not settings.PROJIVO_EXECUTE_LIVE_DISPATCH:
        return {
            "status": "blocked",
            "reason": "Live AI execution is disabled.",
            "run_id": run_id,
        }

    # Import only when execution is explicitly enabled.
    from projects.ai.services import execute_agent_run

    execute_agent_run(run_id)

    return {
        "status": "completed",
        "run_id": run_id,
    }


@shared_task
def test_worker_concurrency(seconds=5):
    started = time.time()
    time.sleep(seconds)

    return {
        "worker_pid": os.getpid(),
        "started": started,
        "finished": time.time(),
    }