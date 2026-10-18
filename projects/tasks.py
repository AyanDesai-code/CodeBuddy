from celery import shared_task

from projects.ai.services import execute_agent_run
import time


@shared_task
def execute_agent_run_task(run_id):
    execute_agent_run(run_id)


@shared_task
def test_worker_concurrency(seconds=5):
    import os

    started = time.time()
    time.sleep(seconds)

    return {
        "worker_pid": os.getpid(),
        "started": started,
        "finished": time.time(),
    }