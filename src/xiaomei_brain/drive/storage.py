"""
Drive 存储

JSON 文件存储 Drive 状态：
- 位置：~/.xiaomei-brain/agents/{agent_id}/drive/drive_state.json
- 跨会话持久化
"""

import json
from pathlib import Path
import logging
from typing import Any

from .state import (
    EmotionalState,
    HormoneState,
    MotivationState,
    DesireState,
    EnergyState,
)

logger = logging.getLogger(__name__)


class DriveStorage:
    """Drive 状态存储"""

    def __init__(self, agent_id: str = ""):
        self.agent_id = agent_id
        self.base_dir = Path.home() / ".xiaomei-brain" / "agents" / agent_id / "drive"
        self.state_file = self.base_dir / "drive_state.json"

        # 确保目录存在
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        emotion: EmotionalState,
        hormone: HormoneState,
        motivation: MotivationState,
        desire: DesireState,
        energy: EnergyState | None = None,
    ) -> None:
        """保存 Drive 状态到 JSON 文件"""
        data = {
            "emotion": emotion.to_dict(),
            "hormone": hormone.to_dict(),
            "motivation": motivation.to_dict(),
            "desire": desire.to_dict(),
        }
        if energy:
            data["energy"] = energy.to_dict()

        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug(f"[DriveStorage] 状态已保存: {self.state_file}")
        except Exception as e:
            logger.warning(f"[DriveStorage] 保存失败: {e}")

    def load(
        self,
        emotion: EmotionalState,
        hormone: HormoneState,
        motivation: MotivationState,
        desire: DesireState,
        energy: EnergyState | None = None,
    ) -> bool:
        """
        从 JSON 文件加载 Drive 状态

        返回：是否成功加载（文件不存在返回 False）
        """
        if not self.state_file.exists():
            logger.info(f"[DriveStorage] 状态文件不存在，使用初始值")
            return False

        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            emotion.from_dict(data.get("emotion", {}))
            hormone.from_dict(data.get("hormone", {}))
            motivation.from_dict(data.get("motivation", {}))
            desire.from_dict(data.get("desire", {}))
            if energy:
                energy.from_dict(data.get("energy", {}))

            logger.info(f"[DriveStorage] 状态已加载: {self.state_file}")
            return True

        except Exception as e:
            logger.warning(f"[DriveStorage] 加载失败，使用初始值: {e}")
            return False

    def exists(self) -> bool:
        """检查状态文件是否存在"""
        return self.state_file.exists()

    def clear(self) -> None:
        """清除存储（重置状态）"""
        if self.state_file.exists():
            self.state_file.unlink()
            logger.info(f"[DriveStorage] 状态已清除")