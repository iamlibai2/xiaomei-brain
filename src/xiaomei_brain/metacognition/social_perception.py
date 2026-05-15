"""社交感知：对话轮次级的自我监督。

属于 Metacognition 层（自我监督与反省），和 PACE（任务执行监控）互补：
- PACE → 向内：我做对了吗？我卡住了吗？
- SocialPerception → 向外：我刚才说话合适吗？用户状态变了吗？

触发方式：对话轮次完成后，每 N 轮做一次轻量 LLM 感知。
输出两条路径进入 SelfImage（中枢）：
- 感知文本 → SelfImage.mind.social_perceptions（给 LLM 读）
- 结构化信号 → Drive（情绪/激素/欲望自动代理到 SelfImage.body）
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)


# ── 社交信号 → Drive 映射表（代码决定数值，LLM 只识别类型）────

SOCIAL_SIGNAL_MAP: dict[str, dict] = {
    "user_low_mood": {      # 用户情绪低落
        "emotion": "sadness",
        "cortisol": +0.08,
        "belonging": +0.10,      # 想关心/陪伴
        "oxytocin": +0.08,
    },
    "user_enthusiastic": {  # 用户热情、有活力
        "emotion": "joy",
        "oxytocin": +0.12,
        "dopamine": +0.08,
    },
    "user_cold": {          # 用户冷淡疏远
        "cortisol": +0.12,
        "belonging": -0.08,
        "oxytocin": -0.08,
    },
    "user_angry": {         # 用户愤怒/不满
        "emotion": "fear",
        "cortisol": +0.15,
    },
    "user_happy": {         # 用户开心满足
        "emotion": "joy",
        "oxytocin": +0.10,
        "serotonin": +0.05,
    },
    "user_stressed": {      # 用户压力大
        "cortisol": +0.10,
        "norepinephrine": +0.08,
    },
    "user_trusting": {      # 用户信任/亲近
        "oxytocin": +0.15,
        "belonging": +0.12,
        "serotonin": +0.05,
    },
}


class SocialPerception:
    """社交感知器：回看最近对话，收集用户状态变化信号。

    输出两条路径进入 SelfImage：
    1. 感知文本 → social_perceptions（给 LLM 读）
    2. 结构化信号 → Drive（情绪/激素/欲望自动代理到 SelfImage.body）

    后续可扩展更多感知维度：
    - 关系温度感知
    - 用户兴趣变化感知
    - 对话节奏感知
    """

    def __init__(self, interval: int = 3) -> None:
        self._round_count: int = 0
        self._interval: int = interval

    def on_round_complete(
        self,
        conversation_db: Any,
        llm: Any,
        session_id: str,
        social_perceptions: list[dict],
    ) -> list[dict]:
        """对话轮次完成时调用。

        Returns:
            结构化信号列表 [{"signal": "user_low_mood", "intensity": 0.5}, ...]
            调用方负责应用到 Drive。
        """
        self._round_count += 1
        if self._round_count % self._interval != 0:
            return []
        if not conversation_db or not llm:
            return []

        rows = conversation_db.get_recent(12, session_id=session_id)
        if not rows:
            return []

        recent = [
            {"role": r.get("role", ""), "content": r.get("content", "")[:300]}
            for r in rows
        ]

        system = (
            "你是小美，你在和用户对话。请专注感知用户的状态变化。\n"
            "只关注你能从对话中直接感受到的，不要编造，不要解释。"
        )
        user_prompt = (
            "回顾以下最近的对话，感受用户的状态是否有变化：\n\n"
            + "\n".join(f"[{m['role']}]: {m['content'][:200]}" for m in recent)
            + "\n\n请回答（简洁，每行一条感知，没有就说\"无明显变化\"）：\n"
            "1. 用户今天说话的方式和之前有什么不同？\n"
            "2. 用户的情绪状态如何？有变化吗？\n"
            "3. 有什么微妙的不对劲吗？\n"
            "\n"
            "最后，用一个 JSON 描述你感知到的主要社交信号（没有则输出空对象{}）：\n"
            '{"social_signal": "<类型>", "intensity": <0.0-1.0>}\n'
            "类型可选：user_low_mood / user_enthusiastic / user_cold / "
            "user_angry / user_happy / user_stressed / user_trusting"
        )

        try:
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ]
            response = llm.chat(messages)
            result = response.content if response else None
            if not result:
                return []

            # ── 分离 JSON 信号和文本感知 ──
            signals: list[dict] = []
            perception_text = result.strip()

            json_match = re.search(r"\{[\s\S]*\}", perception_text)
            if json_match:
                try:
                    signal_data = json.loads(json_match.group())
                    signal_type = signal_data.get("social_signal", "")
                    intensity = float(signal_data.get("intensity", 0))
                    if signal_type in SOCIAL_SIGNAL_MAP and intensity > 0.1:
                        signals.append({
                            "signal": signal_type,
                            "intensity": min(intensity, 1.0),
                        })
                    # 从文本中移除 JSON 块，保留纯感知文本
                    perception_text = perception_text[:json_match.start()].strip()
                except (json.JSONDecodeError, ValueError):
                    pass

            # ── 写入感知文本（给 LLM 读）──
            if perception_text and "无明显变化" not in perception_text:
                social_perceptions.append({
                    "content": perception_text,
                    "round": self._round_count,
                    "time": time.time(),
                })
                if len(social_perceptions) > 20:
                    social_perceptions[:] = social_perceptions[-20:]
                logger.info(
                    "[SocialPerception] 轮次感知 (第%d轮): %s",
                    self._round_count, perception_text[:60],
                )

            if signals:
                logger.info("[SocialPerception] 社交信号: %s", signals)

            return signals

        except Exception as e:
            logger.warning("[SocialPerception] 感知失败: %s", e)
            return []
