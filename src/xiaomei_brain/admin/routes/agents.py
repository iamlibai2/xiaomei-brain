"""GET/POST /api/agents — Agent 管理（CLI + REST 共用 AgentManager）。"""

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
    return {"agents": _AGENT_MANAGER.list_agents_info()}


@router.get("/api/agents/{agent_id}", dependencies=[Depends(verify_admin)])
def get_agent(agent_id: str) -> dict:
    if _AGENT_MANAGER is None:
        raise HTTPException(status_code=503, detail="AgentManager 未就绪")
    info = _AGENT_MANAGER.get_agent_info(agent_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' 不存在")
    return {"agent": info}


@router.post("/api/agents", dependencies=[Depends(verify_admin)])
def create_agent(data: dict) -> dict:
    if _AGENT_MANAGER is None:
        raise HTTPException(status_code=503, detail="AgentManager 未就绪")
    name = data.get("name", "")
    copy_from = data.get("copy_from") or ""
    identity_content = data.get("identity", "")
    config_yaml = data.get("config_yaml", "")
    if not name:
        raise HTTPException(status_code=400, detail="缺少 name")
    try:
        result = _AGENT_MANAGER.create_agent(
            name, copy_from=copy_from,
            identity_content=identity_content,
            brain_yaml_content=config_yaml,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"agent": result}
