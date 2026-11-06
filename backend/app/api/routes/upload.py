import asyncio
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.services.task_store import MAX_UPLOAD_BYTES, Status, process_task, store

router = APIRouter()

CHUNK_SIZE = 1024 * 1024
ALLOWED_SUFFIXES = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv"}
ALLOWED_ASPECT = {"16:9", "9:16", "1:1"}


class UploadResponse(BaseModel):
    task_id: str


@router.post("/upload", response_model=UploadResponse, status_code=201)
async def upload_video(
    file: UploadFile = File(...),
    target_duration_min: Optional[float] = Form(None),
    aspect_ratio: Optional[str] = Form(None),
    subtitles: Optional[str] = Form(None),
) -> UploadResponse:
    safe_name = Path(file.filename or "video.mp4").name or "video.mp4"
    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail=f"unsupported video format {suffix or '(no extension)'}; allowed: {sorted(ALLOWED_SUFFIXES)}",
        )

    aspect = (aspect_ratio or "16:9").strip()
    if aspect not in ALLOWED_ASPECT:
        raise HTTPException(status_code=400, detail=f"invalid aspect_ratio; allowed: {sorted(ALLOWED_ASPECT)}")

    subs = str(subtitles or "false").strip().lower() in {"1", "true", "yes", "on"}
    target_min = float(target_duration_min) if target_duration_min is not None else None
    if target_min is not None and target_min <= 0:
        raise HTTPException(status_code=400, detail="target_duration_min must be positive")

    task = store.create(
        file_name=safe_name,
        target_duration_min=target_min,
        aspect_ratio=aspect,
        subtitles=subs,
    )
    store.set_status(task.task_id, Status.UPLOADING, progress=5, message="upload started")

    dest_dir = store.upload_dir(task.task_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / safe_name

    total = 0
    try:
        with target.open("wb") as out:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="video exceeds 2GB size limit")
                out.write(chunk)
    except HTTPException:
        store.set_status(task.task_id, Status.FAILED, message="upload failed: exceeds 2GB size limit")
        target.unlink(missing_ok=True)
        raise
    except Exception as exc:
        store.set_status(task.task_id, Status.FAILED, message=f"upload failed: {exc}")
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="upload save failed")

    asyncio.create_task(process_task(task.task_id))
    return UploadResponse(task_id=task.task_id)
