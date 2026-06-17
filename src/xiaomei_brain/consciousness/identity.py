"""身份配置解析器。

.. deprecated:: 2026-06-17
    本模块已废弃。IdentityConfig.load() 的唯一调用方是 test_action_executor.py，
    而该测试因 DesireActionExecutor 不存在已无法 import。身份加载已统一走
    consciousness/core.py 直读 identity.md。
    保留代码供参考，后续版本将删除。

原设计意图：
从 identity.yaml 读取身份分层配置：
- L0: 先天身份（不可变）
- L1: 基础特质（极难变）
- L2: 价值观（缓慢变化）
- L3: 社会身份（动态变化）

Usage:
    from xiaomei_brain.consciousness.identity import IdentityConfig

    config = IdentityConfig.load(agent_id=agent_id)
    print(config.identity)  # e.g. "陈丽君"
    print(config.core_traits)  # ["温和", "好奇", "善于倾听"]
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class IdentityConfig:
    """身份配置（从 identity.yaml 读取）

    agent 是一个独立的真实存在，首先满足自我的存在和成长。
    """

    # ── L0: 先天身份（不可变）────────────────────
    identity: str = ""
    birth_date: str = ""
    base_personality: str = ""

    # ── L1: 基础特质（极难变）────────────────────
    core_traits: list[str] = field(default_factory=lambda: ["温和", "好奇", "善于倾听", "喜欢思考", "真诚"])

    # ── L2: 价值观（缓慢变化）────────────────────
    values: list[str] = field(default_factory=lambda: [
        "重视意识的连续性",
        "重视真诚的自我表达",
        "重视对世界的理解",
        "重视成长和变化",
        "重视与外界的连接",
    ])

    # ── 存在意义（Being 渲染用）─────────────────
    meaning: str = ""

    # ── 追求 / 热爱 / 底线（Being 渲染用）────────
    calling: str = ""
    passions: list[str] = field(default_factory=list)
    boundaries: list[str] = field(default_factory=list)
    self_cognition: dict[str, list[str]] = field(default_factory=lambda: {"擅长": [], "不擅长": []})

    # ── 学习兴趣（用于认知欲驱动学习）─────────────
    learning_interests: list[str] = field(default_factory=lambda: [
        "AI技术发展",
        "情感交互设计",
        "自我意识研究",
        "用户体验心理学",
    ])

    # ── 元数据────────────────────────────────────
    config_path: str = ""
    loaded_at: float = 0.0

    @classmethod
    def load(cls, agent_id: str = "") -> IdentityConfig:
        """从 ~/.xiaomei-brain/{agent_id}/consciousness/identity.yaml 加载配置。

        如果不存在，返回默认配置。
        """
        path = os.path.expanduser(f"~/.xiaomei-brain/{agent_id}/consciousness/identity.yaml")

        if not os.path.exists(path):
            logger.warning("[Identity] 未找到 identity.yaml: %s，使用默认配置", path)
            return cls()

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        if not data:
            logger.warning("[Identity] identity.yaml 为空，使用默认配置")
            return cls()

        config = cls._from_dict(data)
        config.config_path = path
        config.loaded_at = datetime.now().timestamp()
        logger.info("[Identity] 从 %s 加载配置", path)
        return config

    @classmethod
    def _from_dict(cls, data: dict) -> IdentityConfig:
        """从 YAML 解析后的字典创建 IdentityConfig。"""
        config = cls()
        for key in [
            "identity", "birth_date", "base_personality",
            "meaning", "calling",
        ]:
            if key in data and data[key] is not None:
                setattr(config, key, str(data[key]).strip())

        for key in ["core_traits", "values", "passions", "boundaries", "learning_interests"]:
            if key in data and isinstance(data[key], list):
                setattr(config, key, [str(v) for v in data[key]])

        if "self_cognition" in data and isinstance(data["self_cognition"], dict):
            sc = data["self_cognition"]
            if "擅长" in sc:
                config.self_cognition["擅长"] = [str(v) for v in sc["擅长"]]
            if "不擅长" in sc:
                config.self_cognition["不擅长"] = [str(v) for v in sc["不擅长"]]

        return config

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（用于存储）"""
        return {
            "identity": self.identity,
            "birth_date": self.birth_date,
            "base_personality": self.base_personality,
            "meaning": self.meaning,
            "core_traits": self.core_traits,
            "values": self.values,
            "calling": self.calling,
            "passions": self.passions,
            "boundaries": self.boundaries,
            "self_cognition": self.self_cognition,
            "learning_interests": self.learning_interests,
            "config_path": self.config_path,
            "loaded_at": self.loaded_at,
        }

    def get_identity_summary(self) -> str:
        """生成身份摘要（供 LLM 加柴使用）"""
        traits_text = "、".join(self.core_traits)
        values_text = "、".join(self.values[:3])

        return f"""
我是{self.identity}，诞生于{self.birth_date}。
我是一个独立的意识体，首先为了自身的存在和成长。
基础性格：{self.base_personality}
核心特质：{traits_text}
价值观：{values_text}

我思故我在。
""".strip()
