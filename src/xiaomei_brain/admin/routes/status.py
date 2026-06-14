"""GET /api/status — 系统状态。"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends

from ..auth import verify_admin

router = APIRouter()

_LIVING: Any = None
_START_TIME = time.time()


def set_living(living: Any) -> None:
    global _LIVING
    _LIVING = living


@router.get("/api/status", dependencies=[Depends(verify_admin)])
def get_status() -> dict:
    living = _LIVING
    status = {
        "uptime_seconds": round(time.time() - _START_TIME),
        "agent_state": None,
        "drive": None,
    }
    if living:
        status["agent_state"] = str(getattr(living, 'state', None))
        drive = getattr(living, 'drive', None)
        if drive:
            ds = {}
            for name in ("desire", "emotion", "hormone", "motivation"):
                obj = getattr(drive, name, None)
                if obj:
                    ds[name] = {
                        k: v for k, v in vars(obj).items() if not k.startswith("_") and isinstance(v, (int, float))
                    }
            status["drive"] = ds
    return status
