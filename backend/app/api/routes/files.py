from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.services.task_store import UPLOADS_DIR, TaskNotFound, store

router = APIRouter()

ALLOWED_NAMES = {"output.mp4", "intermediate.mp4"}


@router.get("/files/{task_id}/{filename}")
def get_task_file(task_id: str, filename: str) -> FileResponse:
    safe_name = Path(filename).name
    if safe_name != filename or safe_name not in ALLOWED_NAMES:
        raise HTTPException(status_code=400, detail="invalid filename")
    try:
        store.get(task_id)
    except TaskNotFound:
        raise HTTPException(status_code=404, detail="task not found")
    path = (UPLOADS_DIR / task_id / safe_name).resolve()
    root = UPLOADS_DIR.resolve()
    if not str(path).startswith(str(root) + "/") or not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path, media_type="video/mp4", filename=safe_name)
