"""GET /api/sessions — 会话列表。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..auth import verify_admin

router = APIRouter()

_LIVING: Any = None


def set_living(living: Any) -> None:
    global _LIVING
    _LIVING = living


@router.get("/api/sessions", dependencies=[Depends(verify_admin)])
def list_sessions() -> dict:
    living = _LIVING
    if living is None:
        raise HTTPException(status_code=503, detail="Living 未就绪")
    sessions = getattr(living, '_sessions', {})
    return {
        "sessions": [
            {"id": k, "user_id": getattr(v, "user_id", ""), "agent_id": getattr(v, "agent_id", "")}
            for k, v in sessions.items()
        ]
    }
