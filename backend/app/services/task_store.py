import asyncio
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, Set

from app.services.agnes_editor import (
    build_edit_plan,
    edit_segments,
    export_to_output,
    probe_video,
)

BASE_DIR = Path(__file__).resolve().parents[2]
UPLOADS_DIR = BASE_DIR / "uploads"
MAX_UPLOAD_BYTES = 2 * 1024 ** 3

AGNES_API_BASE = os.getenv("AGNES_API_BASE", "")
AGNES_API_KEY = os.getenv("AGNES_API_KEY", "")


class Status(str, Enum):
    QUEUED = "queued"
    UPLOADING = "uploading"
    ANALYZING = "analyzing"
    EDITING = "editing"
    EXPORTING = "exporting"
    READY = "ready"
    FAILED = "failed"


ALLOWED_TRANSITIONS: Dict[Status, Set[Status]] = {
    Status.QUEUED: {Status.UPLOADING, Status.FAILED},
    Status.UPLOADING: {Status.ANALYZING, Status.FAILED},
    Status.ANALYZING: {Status.EDITING, Status.FAILED},
    Status.EDITING: {Status.EXPORTING, Status.FAILED},
    Status.EXPORTING: {Status.READY, Status.FAILED},
    Status.READY: set(),
    Status.FAILED: set(),
}


class TaskNotFound(KeyError):
    pass


@dataclass
class Task:
    task_id: str
    status: Status
    progress: int
    message: str
    created_at: str
    updated_at: str
    output_url: Optional[str]
    file_name: Optional[str] = None
    target_duration_min: Optional[float] = None
    aspect_ratio: Optional[str] = None
    subtitles: bool = False


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStore:
    def __init__(self) -> None:
        self._tasks: Dict[str, Task] = {}

    def create(self, file_name: Optional[str] = None, target_duration_min: Optional[float] = None, aspect_ratio: Optional[str] = None, subtitles: bool = False) -> Task:
        task_id = uuid.uuid4().hex
        now = _utcnow()
        task = Task(
            task_id=task_id,
            status=Status.QUEUED,
            progress=0,
            message="task created, waiting for upload",
            created_at=now,
            updated_at=now,
            output_url=None,
            file_name=file_name,
            target_duration_min=target_duration_min,
            aspect_ratio=aspect_ratio,
            subtitles=subtitles,
        )
        self._tasks[task_id] = task
        return task

    def get(self, task_id: str) -> Task:
        try:
            return self._tasks[task_id]
        except KeyError:
            raise TaskNotFound(task_id) from None

    def count(self) -> int:
        return len(self._tasks)

    def upload_dir(self, task_id: str) -> Path:
        return UPLOADS_DIR / task_id

    def set_status(
        self,
        task_id: str,
        status: Status,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        output_url: Optional[str] = None,
    ) -> Task:
        task = self.get(task_id)
        if status != task.status and status not in ALLOWED_TRANSITIONS[task.status]:
            raise ValueError(f"illegal status transition: {task.status.value} -> {status.value}")
        task.status = status
        if progress is not None:
            task.progress = max(0, min(100, progress))
        if message is not None:
            task.message = message
        if output_url is not None:
            task.output_url = output_url
        task.updated_at = _utcnow()
        return task



def public_file_url(task_id: str) -> str:
    """Absolute media URL for browsers on :5173; override with PUBLIC_API_BASE."""
    base = (os.getenv("PUBLIC_API_BASE") or "http://127.0.0.1:8000").rstrip("/")
    return f"{base}/api/v1/files/{task_id}/output.mp4"

store = TaskStore()


async def process_task(task_id: str) -> None:
    """Background pipeline: analyzing -> editing -> exporting -> ready (or failed).

    Credentials are read from AGNES_API_BASE / AGNES_API_KEY env only (never
    hardcoded). Blocking ffmpeg / HTTP work is offloaded via asyncio.to_thread.
    """
    try:
        task = store.get(task_id)
        video_path = store.upload_dir(task_id) / (task.file_name or "video.mp4")
        if not video_path.is_file():
            raise FileNotFoundError(f"uploaded video not found: {video_path}")

        # 1. analyzing: ffprobe metadata + Agnes edit plan (heuristic fallback)
        store.set_status(
            task_id,
            Status.ANALYZING,
            progress=30,
            message="analyzing: ffprobe metadata + Agnes edit plan",
        )
        meta = await asyncio.to_thread(probe_video, video_path)
        target_sec = (task.target_duration_min * 60.0) if task.target_duration_min else None
        plan, plan_note = await asyncio.to_thread(build_edit_plan, meta, target_sec)

        # 2. editing: cut/concat segments into an intermediate mp4
        store.set_status(
            task_id,
            Status.EDITING,
            progress=60,
            message=f"editing: {plan_note}",
        )
        intermediate = store.upload_dir(task_id) / "intermediate.mp4"
        await asyncio.to_thread(
            edit_segments, video_path, plan, meta, intermediate,
            task.aspect_ratio, bool(task.subtitles),
        )

        # 3. exporting: publish uploads/{task_id}/output.mp4
        store.set_status(
            task_id,
            Status.EXPORTING,
            progress=85,
            message=(
                f"exporting final video"
                f" (aspect={task.aspect_ratio}, subtitles={bool(task.subtitles)})"
            ),
        )
        output_path = store.upload_dir(task_id) / "output.mp4"
        await asyncio.to_thread(export_to_output, intermediate, output_path)

        # 4. ready
        store.set_status(
            task_id,
            Status.READY,
            progress=100,
            message="done",
            output_url=public_file_url(task_id),
        )
    except Exception as exc:
        store.set_status(task_id, Status.FAILED, message=f"processing failed: {exc}")
