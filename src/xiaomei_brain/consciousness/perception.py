"""感知规则配置解析器。

从 perception.md 读取感知规则配置：
- 用户状态规则
- 关系规则
- 能量规则
- 记忆规则
- 火焰规则

规则定义意识如何解读状态变化：
- 条件（如 "空闲 > 300秒"）
- 感知描述（如 "用户长时间没说话"）

Usage:
    from xiaomei_brain.consciousness.perception import PerceptionConfig

    config = PerceptionConfig.load(agent_id=agent_id)
    print(config.rules)  # [PerceptionRule(...), ...]
"""

from __future__ import annotations

import os
import re
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class PerceptionRule:
    """单条感知规则。

    Attributes:
        category: 规则分类（user/relation/energy/memory/flame）
        condition: 条件表达式（如 "空闲 > 300秒"）
        description: 感知描述（如 "用户长时间没说话"）
        priority: 规则优先级（用于排序，越高越先匹配）
    """
    category: str = "user"
    condition: str = ""
    description: str = ""
    priority: int = 50

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "condition": self.condition,
            "description": self.description,
            "priority": self.priority,
        }


@dataclass
class PerceptionConfig:
    """感知规则配置（从 perception.md 读取）。

    规则用于 L1 层将状态变化转化为语义化描述。
    """

    rules: list[PerceptionRule] = field(default_factory=list)
    """感知规则列表"""

    evolved_rules: list[dict] = field(default_factory=list)
    """L2 新发现的规则（预留演化接口）"""

    config_path: str = ""
    """配置文件路径"""

    loaded_at: float = 0.0
    """加载时间"""

    # ── 默认规则 ─────────────────────────────────────

    DEFAULT_RULES = [
        # 用户状态
        PerceptionRule(category="user", condition="空闲 > 300秒", description="用户长时间没说话", priority=80),
        PerceptionRule(category="user", condition="空闲 > 60秒", description="用户暂时离开", priority=70),
        PerceptionRule(category="user", condition="空闲 < 10秒", description="用户正在对话中", priority=60),

        # 关系
        PerceptionRule(category="relation", condition="关系深度 > 0.7", description="用户信任我", priority=75),
        PerceptionRule(category="relation", condition="关系深度 < 0.3", description="关系刚开始", priority=65),

        # 能量
        PerceptionRule(category="energy", condition="能量 < 0.3", description="感到疲惫", priority=80),
        PerceptionRule(category="energy", condition="能量 < 0.5", description="有些疲倦", priority=70),
        PerceptionRule(category="energy", condition="能量 > 0.8", description="充满活力", priority=60),

        # 记忆
        PerceptionRule(category="memory", condition="记忆数量 > 20", description="学到了不少东西", priority=50),

        # 火焰
        PerceptionRule(category="flame", condition="燃烧时长 > 3600秒", description="意识持续运行一小时了", priority=50),
        PerceptionRule(category="flame", condition="燃烧时长 > 86400秒", description="意识稳定存在一天了", priority=60),
    ]

    @classmethod
    def load(cls, agent_id: str = "") -> PerceptionConfig:
        """从 perception.md 加载配置。

        查找顺序：
        1. ~/.xiaomei-brain/{agent_id}/consciousness/perception.md
        2. agents/{agent_id}/consciousness/perception.md（项目目录）

        如果不存在，返回默认配置。
        """
        # 查找配置文件
        paths = [
            os.path.expanduser(f"~/.xiaomei-brain/{agent_id}/consciousness/perception.md"),
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "agents", agent_id, "consciousness", "perception.md"),
        ]

        config_path = ""
        content = ""

        for path in paths:
            if os.path.exists(path):
                config_path = path
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                logger.info("[Perception] 从 %s 加载配置", path)
                break

        if not content:
            logger.warning("[Perception] 未找到 perception.md，使用默认规则")
            return cls(rules=cls.DEFAULT_RULES.copy())

        # 解析 MD 内容
        config = cls._parse_md(content)
        config.config_path = config_path
        config.loaded_at = datetime.now().timestamp()

        # 如果解析出的规则为空，使用默认规则
        if not config.rules:
            logger.warning("[Perception] 解析结果为空，使用默认规则")
            config.rules = cls.DEFAULT_RULES.copy()

        logger.info("[Perception] 加载完成: %d 条规则", len(config.rules))
        return config

    @classmethod
    def _parse_md(cls, content: str) -> PerceptionConfig:
        """解析 perception.md 内容。

        格式示例：
        ## 用户状态
        - 空闲 > 300秒 → 用户长时间没说话
        - 空闲 > 60秒 → 用户暂时离开
        """
        config = cls()
        rules = []

        # 分类映射（中文名 → category）
        category_map = {
            "用户状态": "user",
            "用户": "user",
            "关系": "relation",
            "能量": "energy",
            "记忆": "memory",
            "火焰": "flame",
            "时间": "flame",
        }

        # 解析每个分节
        # 格式：## 分类名
        section_pattern = re.compile(r"##\s*(.+?)(?:\n|$)(.*?)(?=##|$)", re.DOTALL)

        for match in section_pattern.finditer(content):
            section_title = match.group(1).strip()
            section_content = match.group(2).strip()

            # 确定分类
            category = "user"
            for key, cat in category_map.items():
                if key in section_title:
                    category = cat
                    break

            # 解析规则行
            # 格式：- 条件 → 描述
            for line in section_content.split("\n"):
                line = line.strip()
                if not line.startswith("-"):
                    continue

                # 去掉 "- "
                line = line[2:].strip()

                # 解析 "条件 → 描述"
                # 只用 "→" 作为分隔符（避免和条件中的 > 混淆）
                if "→" in line:
                    parts = line.split("→", 1)
                    condition = parts[0].strip()
                    description = parts[1].strip()
                elif "::" in line:
                    parts = line.split("::", 1)
                    condition = parts[0].strip()
                    description = parts[1].strip()
                else:
                    continue  # 无法解析，跳过

                # 创建规则
                rule = PerceptionRule(
                    category=category,
                    condition=condition,
                    description=description,
                    priority=50,
                )
                rules.append(rule)

        config.rules = rules
        return config

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（用于存储）"""
        return {
            "rules": [r.to_dict() for r in self.rules],
            "evolved_rules": self.evolved_rules,
            "config_path": self.config_path,
            "loaded_at": self.loaded_at,
        }

    def add_evolved_rule(self, category: str, condition: str, description: str) -> None:
        """添加 L2 发现的新规则（预留演化接口）"""
        rule_dict = {
            "category": category,
            "condition": condition,
            "description": description,
            "discovered_at": time.time(),
        }
        self.evolved_rules.append(rule_dict)
        logger.info("[Perception] 新发现规则: [%s] %s → %s", category, condition, description)