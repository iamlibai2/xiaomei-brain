"""GET/PATCH /api/config — 配置读写。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..auth import verify_admin

router = APIRouter()

_CONFIG: Any = None


def set_config(config: Any) -> None:
    global _CONFIG
    _CONFIG = config


@router.get("/api/config", dependencies=[Depends(verify_admin)])
def get_config() -> dict:
    if _CONFIG is None:
        raise HTTPException(status_code=503, detail="配置未加载")
    cfg = getattr(_CONFIG, "data", None)
    if cfg:
        return {"config": dict(cfg)}
    result = {}
    for attr in dir(_CONFIG):
        if not attr.startswith("_"):
            v = getattr(_CONFIG, attr)
            if isinstance(v, (str, int, float, bool, list, dict, type(None))):
                result[attr] = v
    return {"config": result}


@router.patch("/api/config", dependencies=[Depends(verify_admin)])
def patch_config(patch: dict) -> dict:
    if _CONFIG is None:
        raise HTTPException(status_code=503, detail="配置未加载")
    applied = []
    for key, value in patch.items():
        if hasattr(_CONFIG, key):
            setattr(_CONFIG, key, value)
            applied.append(key)
    return {"applied": applied}
