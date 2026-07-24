from datetime import date

from pydantic import BaseModel


class ScheduledTask(BaseModel):
    task_id: int

    start_date: date | None

    due_date: date | None

    estimated_hours: float | None

    milestone: str | None

    dependency_ids: list[int]


class ProjectSchedule(BaseModel):
    summary: str

    tasks: list[ScheduledTask]