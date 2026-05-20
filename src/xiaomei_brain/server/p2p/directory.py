"""Agent 通讯录 — 读/写 agent_directory.yaml。"""

from __future__ import annotations

import os
import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

DEFAULT_DIRECTORY = Path.home() / ".xiaomei-brain" / "agent_directory.yaml"

DEFAULT_TEMPLATE = """\
# Agent 通讯录 — 每个 agent 的可寻址端点
# agent 启动时自动注册，远程 agent 手动添加
agents:
  # xiaomei:
  #   address: "localhost:18765"
  # xiaoming:
  #   address: "localhost:18766"
"""


class AgentDirectory:
    """管理 agent_directory.yaml 通讯录。"""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else DEFAULT_DIRECTORY
        self._ensure_exists()

    def _ensure_exists(self) -> None:
        if not self._path.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(DEFAULT_TEMPLATE, encoding="utf-8")

    def load(self) -> dict:
        """加载通讯录。"""
        try:
            with open(self._path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return data
        except Exception as e:
            logger.warning("[Directory] 加载通讯录失败: %s", e)
            return {}

    def save(self, data: dict) -> None:
        """保存通讯录。"""
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False)
        except Exception as e:
            logger.error("[Directory] 保存通讯录失败: %s", e)

    def resolve(self, agent_id: str) -> str | None:
        """查询 agent 地址。返回 "host:port" 或 None。"""
        data = self.load()
        agents = data.get("agents") or {}
        info = agents.get(agent_id, {})
        if isinstance(info, dict):
            return info.get("address")
        return info if isinstance(info, str) else None

    def register(self, agent_id: str, address: str) -> None:
        """注册/更新 agent 地址。"""
        data = self.load()
        if not data.get("agents"):
            data["agents"] = {}
        if isinstance(data["agents"].get(agent_id), dict):
            data["agents"][agent_id]["address"] = address
        else:
            data["agents"][agent_id] = {"address": address}
        self.save(data)
        logger.info("[Directory] 注册 %s -> %s", agent_id, address)

    def unregister(self, agent_id: str) -> None:
        """移除 agent。"""
        data = self.load()
        agents = data.get("agents") or {}
        agents.pop(agent_id, None)
        data["agents"] = agents
        self.save(data)

    def list_all(self) -> dict[str, str]:
        """列出所有 agent 及其地址。返回 {agent_id: address}。"""
        data = self.load()
        agents = data.get("agents") or {}
        result = {}
        for k, v in agents.items():
            if isinstance(v, dict):
                addr = v.get("address")
                if addr:
                    result[k] = addr
            elif isinstance(v, str):
                result[k] = v
        return result
