"""GET/POST /api/agents — Agent 管理。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..auth import verify_admin

router = APIRouter()

_AGENT_MANAGER: Any = None


def set_agent_manager(mgr: Any) -> None:
    global _AGENT_MANAGER
    _AGENT_MANAGER = mgr


@router.get("/api/agents", dependencies=[Depends(verify_admin)])
def list_agents() -> dict:
    if _AGENT_MANAGER is None:
        raise HTTPException(status_code=503, detail="AgentManager 未就绪")
    agents = _AGENT_MANAGER.list_agents() if hasattr(_AGENT_MANAGER, "list_agents") else []
    return {"agents": agents}


@router.get("/api/agents/{agent_id}", dependencies=[Depends(verify_admin)])
def get_agent(agent_id: str) -> dict:
    if _AGENT_MANAGER is None:
        raise HTTPException(status_code=503, detail="AgentManager 未就绪")
    info = _AGENT_MANAGER.get_agent_info(agent_id) if hasattr(_AGENT_MANAGER, "get_agent_info") else None
    if info is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' 不存在")
    return {"agent": info}


@router.post("/api/agents", dependencies=[Depends(verify_admin)])
def create_agent(data: dict) -> dict:
    if _AGENT_MANAGER is None:
        raise HTTPException(status_code=503, detail="AgentManager 未就绪")
    name = data.get("name", "")
    copy_from = data.get("copy_from")
    if not name:
        raise HTTPException(status_code=400, detail="缺少 name")
    result = _AGENT_MANAGER.create_agent(name, copy_from=copy_from)
    return {"agent": result}
