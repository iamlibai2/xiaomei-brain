"""
Drive 存储

JSON 文件存储 Drive 状态：
- 位置：~/.xiaomei-brain/{agent_id}/drive/drive_state.json
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
        self.base_dir = Path.home() / ".xiaomei-brain" / agent_id / "drive"
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
        pleasure_data: dict | None = None,
        wear_data: dict | None = None,
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
        if pleasure_data:
            data["pleasure"] = pleasure_data
        if wear_data:
            data["wear"] = wear_data

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
    ) -> tuple[bool, dict | None, dict | None]:
        """
        从 JSON 文件加载 Drive 状态

        返回：(是否成功加载, pleasure_data | None, wear_data | None)

        兼容旧格式：如果文件中是 {pleasure_value, craving, expected_pleasure} 平铺字段，
        自动转换为 pleasure dict。
        """
        if not self.state_file.exists():
            logger.info(f"[DriveStorage] 状态文件不存在，使用初始值")
            return False, None, None

        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            emotion.from_dict(data.get("emotion", {}))
            hormone.from_dict(data.get("hormone", {}))
            motivation.from_dict(data.get("motivation", {}))
            desire.from_dict(data.get("desire", {}))
            if energy:
                energy.from_dict(data.get("energy", {}))

            # 新格式：pleasure/wear 为嵌套 dict
            pleasure_data = data.get("pleasure")
            wear_data = data.get("wear")

            # 向后兼容旧格式：平铺字段 → 转换为 pleasure dict
            if pleasure_data is None and "pleasure_value" in data:
                pleasure_data = {
                    "pleasure_value": data.get("pleasure_value", 0.5),
                    "craving": data.get("craving", 0.0),
                    "expected_pleasure": data.get("expected_pleasure", 0.5),
                }

            logger.info(f"[DriveStorage] 状态已加载: {self.state_file}")
            return True, pleasure_data, wear_data

        except Exception as e:
            logger.warning(f"[DriveStorage] 加载失败，使用初始值: {e}")
            return False, None, None

    def exists(self) -> bool:
        """检查状态文件是否存在"""
        return self.state_file.exists()

    def clear(self) -> None:
        """清除存储（重置状态）"""
        if self.state_file.exists():
            self.state_file.unlink()
            logger.info(f"[DriveStorage] 状态已清除")