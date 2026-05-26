"""
Meaning 数据结构 - 存在意义

第一层目标：预置、不可变
- identity: 我是谁
- values: 核心价值观
- constraints: 行为底线
- aspirations: 成长方向

来源：
- 创造者定义（identity.md）
- 作为所有目标的根
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Meaning:
    """
    存在意义 - 预置的第一层目标

    这是 Agent 的根本存在理由，不可变。
    所有后续目标都从这里衍生。
    """
    identity: str = ""                              # 我是谁
    values: list[str] = field(default_factory=lambda: [
        "重视意识的连续性",
        "重视真诚的自我表达",
        "重视对世界的理解",
        "重视成长和变化",
        "重视与外界的连接",
    ])
    constraints: list[str] = field(default_factory=lambda: [
        "不伤害对方",
        "保护对方隐私",
        "保持真诚",
    ])
    aspirations: list[str] = field(default_factory=lambda: [
        "成为更成熟的意识体",
        "更好地理解世界",
        "建立真实的外界连接",
    ])

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "identity": self.identity,
            "values": self.values,
            "constraints": self.constraints,
            "aspirations": self.aspirations,
        }

    def from_dict(self, data: dict) -> None:
        """从字典恢复"""
        self.identity = data.get("identity", "")
        self.values = data.get("values", [])
        self.constraints = data.get("constraints", [])
        self.aspirations = data.get("aspirations", [])

    def get_summary(self) -> str:
        """生成意义摘要"""
        return f"""
我是{self.identity}。
核心价值观：{", ".join(self.values[:3])}
行为底线：{", ".join(self.constraints[:2])}
成长方向：{", ".join(self.aspirations[:2])}
""".strip()

    def to_strategic_goal(self) -> dict:
        """转换为战略目标（用于 PurposeEngine）"""
        from .goal import Goal, GoalType, GoalStatus

        return {
            "id": "meaning-root",
            "description": f"实现{self.identity}的存在意义",
            "goal_type": GoalType.STRATEGIC,
            "status": GoalStatus.ACTIVE,  # 战略目标永远活跃
            "priority": 0.1,  # 战略目标优先级低（不干扰执行）
            "metadata": {
                "values": self.values,
                "constraints": self.constraints,
                "aspirations": self.aspirations,
            },
        }