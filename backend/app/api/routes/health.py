from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.task_store import AGNES_API_BASE, AGNES_API_KEY, store

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    service: str
    time: str
    agnes_api_base: str
    agnes_configured: bool
    task_count: int


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="ai-auto-editor-backend",
        time=datetime.now(timezone.utc).isoformat(),
        agnes_api_base=AGNES_API_BASE,
        agnes_configured=bool(AGNES_API_BASE and AGNES_API_KEY),
        task_count=store.count(),
    )
