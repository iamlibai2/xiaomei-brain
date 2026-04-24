"""
Purpose 持久化

存储：
- goals.json: 目标树
- meaning.json: 存在意义（可选，通常从 identity.md 加载）

位置：~/.xiaomei-brain/agents/{agent_id}/purpose/
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from .meaning import Meaning
from .goal import Goal

logger = logging.getLogger(__name__)


class PurposeStorage:
    """Purpose 持久化存储"""

    def __init__(self, agent_id: str = "xiaomei"):
        self.agent_id = agent_id
        self.base_dir = Path.home() / ".xiaomei-brain" / "agents" / agent_id / "purpose"
        self.goals_file = self.base_dir / "goals.json"
        self.meaning_file = self.base_dir / "meaning.json"

        # 确保目录存在
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_goals(self, goals: dict[str, Goal]) -> None:
        """保存目标树"""
        data = {
            "goals": {id: g.to_dict() for id, g in goals.items()},
            "updated_at": time.time(),
        }

        try:
            with open(self.goals_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.debug("[PurposeStorage] 目标已保存: %d 个", len(goals))

        except Exception as e:
            logger.warning("[PurposeStorage] 保存失败: %s", e)

    def load_goals(self) -> dict[str, Goal]:
        """加载目标树"""
        if not self.goals_file.exists():
            logger.info(f"[PurposeStorage] 目标文件不存在，返回空")
            return {}

        try:
            with open(self.goals_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            goals = {}
            for id, g_data in data.get("goals", {}).items():
                goal = Goal()
                goal.from_dict(g_data)
                goals[id] = goal

            logger.info(f"[PurposeStorage] 目标已加载: {len(goals)} 个")
            return goals

        except Exception as e:
            logger.warning(f"[PurposeStorage] 加载失败: {e}")
            return {}

    def save_meaning(self, meaning: Meaning) -> None:
        """保存存在意义"""
        try:
            with open(self.meaning_file, "w", encoding="utf-8") as f:
                json.dump(meaning.to_dict(), f, indent=2, ensure_ascii=False)

            logger.debug(f"[PurposeStorage] 存在意义已保存")

        except Exception as e:
            logger.warning(f"[PurposeStorage] 保存失败: {e}")

    def load_meaning(self) -> Optional[Meaning]:
        """加载存在意义"""
        if not self.meaning_file.exists():
            return None

        try:
            with open(self.meaning_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            meaning = Meaning()
            meaning.from_dict(data)

            logger.info(f"[PurposeStorage] 存在意义已加载")
            return meaning

        except Exception as e:
            logger.warning(f"[PurposeStorage] 加载失败: {e}")
            return None

    def exists(self) -> bool:
        """检查存储是否存在"""
        return self.goals_file.exists()

    def clear(self) -> None:
        """清除存储"""
        if self.goals_file.exists():
            self.goals_file.unlink()
        if self.meaning_file.exists():
            self.meaning_file.unlink()
        logger.info("[PurposeStorage] 存储已清除")