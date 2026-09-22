from celery import shared_task


from projects.ai.services import execute_agent_run

@shared_task
def execute_agent_run_task(run_id):
    execute_agent_run(run_id)