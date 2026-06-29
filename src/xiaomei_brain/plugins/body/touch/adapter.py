"""触觉器官插件 — Touch + ScrollSensor + TouchpadSensor → Body。

平台分发：
- WSL2  → Windows 全局钩子桥接（ScrollSensor + TouchpadSensor）
- 其他平台 → 暂不可用（Phase 3/4 实现）

L0 视觉/听觉按 5-10 分钟节流，但触觉不同——触摸是即时交互，
需要每 tick 识别手势 → 翻译为肢体动作描述 → 注入 SelfImage.body.sensory。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import yaml

from xiaomei_brain.body.sense import Sense
from xiaomei_brain.cli.platform_utils import is_wsl2
from .gesture import GestureRecognizer

logger = logging.getLogger(__name__)

# 默认映射表（随插件分发）
_DEFAULT_MAP = Path(__file__).parent / "touch_map.yaml"


def _load_touch_map(agent_id: str | None = None) -> dict:
    """加载触摸手势映射表。用户配置优先，回退到默认。"""
    user_map = None
    if agent_id:
        user_path = Path.home() / ".xiaomei-brain" / agent_id / "touch_map.yaml"
        if user_path.exists():
            try:
                with open(user_path, encoding="utf-8") as f:
                    user_map = yaml.safe_load(f)
                logger.info("触觉映射已加载用户配置: %s", user_path)
            except Exception as e:
                logger.warning("触觉映射加载用户配置失败: %s", e)

    if user_map:
        return user_map

    if _DEFAULT_MAP.exists():
        with open(_DEFAULT_MAP, encoding="utf-8") as f:
            return yaml.safe_load(f)

    logger.warning("触觉映射表未找到，手势将不翻译")
    return {}


def _translate_gesture(gesture: dict, touch_map: dict) -> str | None:
    """将手势翻译为自然语言肢体动作描述。"""
    gestures_cfg = touch_map.get("gestures", {})
    gesture_type = gesture.get("gesture", "")
    zone = gesture.get("zone", "middle")

    # 查找匹配的手势配置
    cfg = gestures_cfg.get(gesture_type)
    if not cfg:
        # 回退：尝试去掉多指前缀
        if gesture_type.startswith("two_finger_"):
            base = gesture_type[len("two_finger_"):]
            cfg = gestures_cfg.get(base)
        elif gesture_type.startswith("three_finger"):
            cfg = gestures_cfg.get("three_finger")

    if cfg and isinstance(cfg, dict):
        desc = cfg.get(zone)
        if desc:
            # 替换变量
            fingers = gesture.get("fingers", 1)
            intensity = gesture.get("intensity", "")
            duration_ms = gesture.get("duration_ms", 0)
            desc = desc.replace("{fingers}", str(fingers))
            desc = desc.replace("{intensity}", intensity)
            desc = desc.replace("{duration}", f"{duration_ms / 1000:.0f}s")
            return desc

    if cfg and isinstance(cfg, str):
        return cfg

    return None


class Touch(Sense):
    """触觉 — 感知用户的物理交互（滚轮 + 触摸板）。

    - feel(): 读取最近的原始触觉事件（滚轮 + 触摸板）
    - feel_body(): 读取并翻译为肢体动作描述（注入 SelfImage）
    - scroll(): 仅滚轮
    - touchpad(): 仅触摸板
    """

    name = "touch"

    def __init__(self):
        super().__init__()
        self._touchpad: Any = None
        self._recognizer = GestureRecognizer()
        self._touch_map: dict = {}
        self._agent_id: str | None = None
        # 累积的已翻译肢体描述，等待被消费
        self._body_descriptions: list[str] = []

    def set_touchpad(self, device) -> None:
        self._touchpad = device

    def init_body_touch(self, agent_id: str) -> None:
        """初始化身体触觉：加载映射表。"""
        self._agent_id = agent_id
        self._touch_map = _load_touch_map(agent_id)

    def is_available(self) -> bool:
        base = super().is_available()
        tp_ok = self._touchpad is not None and self._touchpad.is_operational()
        return base or tp_ok

    # ------------------------------------------------------------------
    # 原始数据
    # ------------------------------------------------------------------

    def feel(self, window_seconds: float = 5.0) -> dict | None:
        """感知最近 window_seconds 秒的全部触觉事件（原始 + 翻译）。"""
        scroll_data = None
        touchpad_data = None

        if self._device and self._device.is_operational():
            scroll_data = self._device.capture(window_seconds=window_seconds)
        if self._touchpad and self._touchpad.is_operational():
            touchpad_data = self._touchpad.capture(window_seconds=window_seconds)

        active = (scroll_data and scroll_data.get("active")) or \
                 (touchpad_data and touchpad_data.get("active"))

        # 手势识别
        gestures = []
        body_descriptions: list[str] = []
        if touchpad_data and touchpad_data.get("events"):
            gestures = self._recognizer.feed(touchpad_data["events"])
            for g in gestures:
                desc = _translate_gesture(g, self._touch_map)
                if desc:
                    body_descriptions.append(desc)
                    self._body_descriptions.append(desc)

        # trim 累积描述
        if len(self._body_descriptions) > 100:
            self._body_descriptions = self._body_descriptions[-50:]

        return {
            "scroll": scroll_data,
            "touchpad": touchpad_data,
            "active": active,
            "gestures": gestures,
            "body_descriptions": body_descriptions,
        }

    def feel_body(self, window_seconds: float = 5.0) -> dict:
        """读取并翻译最近的身体触觉。用于每 tick 注入 SelfImage。

        Returns:
            {"descriptions": ["单指在你额头上轻轻点了一下", ...],
             "active": bool,
             "current_contact": bool,     # 当前是否有手指在触摸板上
             "fingers": int,
             "zone": str | None}
        """
        result = self.feel(window_seconds=window_seconds)
        if not result:
            return {"descriptions": [], "active": False,
                    "current_contact": False, "fingers": 0, "zone": None}

        tp = result.get("touchpad") or {}
        gestures = result.get("gestures") or []
        body_descriptions = result.get("body_descriptions") or []

        # 准备辅助函数：从 map 取 zone 对应的描述
        _gestures_cfg = self._touch_map.get("gestures", {})

        def _map_desc(key: str, _zone: str, **vars) -> str | None:
            cfg = _gestures_cfg.get(key, {})
            if not isinstance(cfg, dict):
                return None
            template = cfg.get(_zone, "")
            if template:
                for k, v in vars.items():
                    template = template.replace(f"{{{k}}}", str(v))
                return template
            return None

        # 判断当前是否还在接触中
        tp_events = tp.get("events", [])
        if tp_events:
            last_event = tp_events[-1]
            fingers = last_event.get("fingers", 0)
            y = last_event.get("y", 0.5)
            if y < 0.33:
                zone = "upper"
            elif y < 0.66:
                zone = "middle"
            else:
                zone = "lower"

            # 如果没有已识别的手势但有接触，用 raw_contact 生成描述
            if not body_descriptions and fingers > 0:
                finger_text = "一根手指" if fingers == 1 else f"{fingers}根手指" if fingers <= 3 else "手掌"
                desc = _map_desc("raw_contact", zone, finger_text=finger_text)
                if desc:
                    body_descriptions = [desc]

            has_data = len(body_descriptions) > 0 or fingers > 0
            return {
                "descriptions": body_descriptions,
                "active": has_data,
                "current_contact": fingers > 0,
                "fingers": fingers,
                "zone": zone,
            }

        # 没有触摸板事件，但有滚轮或其他活动
        if not body_descriptions and result.get("active"):
            desc = _map_desc("brief_touch", "middle")
            if desc:
                body_descriptions = [desc]

        return {"descriptions": body_descriptions, "active": result.get("active", False),
                "current_contact": False, "fingers": 0, "zone": None}

    def consume_body_descriptions(self) -> list[str]:
        """消费并清空累积的肢体描述。"""
        descs = self._body_descriptions
        self._body_descriptions = []
        return descs

    # ------------------------------------------------------------------
    # 单项查询
    # ------------------------------------------------------------------

    def scroll(self, window_seconds: float = 5.0) -> dict | None:
        if self._device and self._device.is_operational():
            return self._device.capture(window_seconds=window_seconds)
        return None

    def touchpad(self, window_seconds: float = 5.0) -> dict | None:
        if self._touchpad and self._touchpad.is_operational():
            return self._touchpad.capture(window_seconds=window_seconds)
        return None

    # ------------------------------------------------------------------
    # BodyState 贡献
    # ------------------------------------------------------------------

    def contribute_to(self, body_state) -> None:
        """Body.tick() 回调：将触觉数据写入 BodyState.sensory。"""
        fb = self.feel_body(window_seconds=3.0)
        body_state.sensory["触觉"] = fb


def register(ctx):
    touch = Touch()

    if is_wsl2():
        from .wsl2 import ScrollSensor, TouchpadSensor
    else:
        from .mock import MockScrollSensor as ScrollSensor, MockTouchpadSensor as TouchpadSensor

    # 滚轮传感器（主设备）
    scroll = ScrollSensor()
    if scroll.open():
        ctx.register_sense(touch, scroll)
        logger.info("触觉：滚轮已就绪")
    else:
        logger.warning("触觉：滚轮不可用")

    # 触摸板传感器（辅助设备）
    touchpad = TouchpadSensor()
    if touchpad.open():
        touch.set_touchpad(touchpad)
        logger.info("触觉：触摸板已就绪")
    else:
        logger.warning("触觉：触摸板不可用")

    # 初始化身体触觉映射
    agent_id = getattr(ctx, 'agent_id', None)
    if agent_id:
        touch.init_body_touch(agent_id)
