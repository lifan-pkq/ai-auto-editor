from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.task_store import TaskNotFound, store

router = APIRouter()


class TaskDetail(BaseModel):
    task_id: str
    status: str
    progress: int
    message: str
    created_at: str
    updated_at: str
    output_url: Optional[str] = None


class TaskProgress(BaseModel):
    task_id: str
    status: str
    progress: int
    message: str
    output_url: Optional[str] = None


@router.get("/tasks/{task_id}", response_model=TaskDetail)
def get_task(task_id: str) -> TaskDetail:
    try:
        task = store.get(task_id)
    except TaskNotFound:
        raise HTTPException(status_code=404, detail="task not found")
    return TaskDetail(
        task_id=task.task_id,
        status=task.status.value,
        progress=task.progress,
        message=task.message,
        created_at=task.created_at,
        updated_at=task.updated_at,
        output_url=task.output_url,
    )


@router.get("/tasks/{task_id}/progress", response_model=TaskProgress)
def get_progress(task_id: str) -> TaskProgress:
    try:
        task = store.get(task_id)
    except TaskNotFound:
        raise HTTPException(status_code=404, detail="task not found")
    return TaskProgress(
        task_id=task.task_id,
        status=task.status.value,
        progress=task.progress,
        message=task.message,
        output_url=task.output_url,
    )
