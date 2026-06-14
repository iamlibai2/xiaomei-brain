"""Admin 管理门 — 独立 FastAPI app，不同端口。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

from .auth import set_admin_agent_id
from .routes.status import router as status_router, set_living as set_status_living
from .routes.config import router as config_router, set_config_path
from .routes.agents import router as agents_router, set_agent_manager
from .routes.sessions import router as sessions_router, set_living as set_sessions_living

logger = logging.getLogger(__name__)

admin_app = FastAPI(title="xiaomei-brain Admin")


@admin_app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


def create_admin_app(
    agent_id: str = "",
    living: Any = None,
    agent_manager: Any = None,
    config_path: str = "",
) -> FastAPI:
    """创建 Admin 管理门 FastAPI app。

    Args:
        agent_id: Agent ID（用于读取 admin token）
        living: ConsciousLiving 实例
        agent_manager: AgentManager 实例
        config_path: agent 配置文件路径（用于 ConfigProvider）
    """
    set_admin_agent_id(agent_id)
    set_status_living(living)
    set_sessions_living(living)
    if config_path:
        set_config_path(config_path)
    set_agent_manager(agent_manager)

    admin_app.include_router(status_router)
    admin_app.include_router(config_router)
    admin_app.include_router(agents_router)
    admin_app.include_router(sessions_router)

    logger.info("[Admin] 管理门已创建")
    return admin_app
