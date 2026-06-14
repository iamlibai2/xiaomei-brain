"""GET/PATCH/PUT /api/config — 配置读写，基于 ConfigProvider。

GET  → 返回完整配置 + hash（供后续 PATCH/PUT 做冲突检测）
PATCH → JSON Merge Patch，需要 baseHash
PUT   → 完整替换，需要 baseHash
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from xiaomei_brain.base.config_provider import ConfigProvider, ConflictError

from ..auth import verify_admin

router = APIRouter()

_PROVIDER: ConfigProvider | None = None


def set_config_path(path: str) -> None:
    global _PROVIDER
    _PROVIDER = ConfigProvider(path)


@router.get("/api/config", dependencies=[Depends(verify_admin)])
def get_config() -> dict:
    if _PROVIDER is None:
        raise HTTPException(status_code=503, detail="ConfigProvider 未初始化")
    return {
        "config": _PROVIDER.get(),
        "hash": _PROVIDER.hash,
    }


@router.patch("/api/config", dependencies=[Depends(verify_admin)])
def patch_config(body: dict) -> dict:
    if _PROVIDER is None:
        raise HTTPException(status_code=503, detail="ConfigProvider 未初始化")
    partial = body.get("config", body)  # 支持 {"config": {...}} 或直接 {...}
    base_hash = body.get("baseHash", "")
    try:
        _PROVIDER.patch(partial, base_hash)
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"success": True, "hash": _PROVIDER.hash}


@router.put("/api/config", dependencies=[Depends(verify_admin)])
def apply_config(body: dict) -> dict:
    if _PROVIDER is None:
        raise HTTPException(status_code=503, detail="ConfigProvider 未初始化")
    config = body.get("config", body)
    base_hash = body.get("baseHash", "")
    try:
        _PROVIDER.apply(config, base_hash)
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"success": True, "hash": _PROVIDER.hash}
