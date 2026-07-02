"""Body 系统状态快照。

Body.tick() 产出的轻量感知快照，不调用 LLM。
推入 SelfImage 后，各层只读快照了解身体感官状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BodyState:
    """感知快照 — tick() 产出，推入 SelfImage。"""

    timestamp: float = 0.0

    # 感官在线状态
    senses_online: dict[str, bool] = field(default_factory=dict)

    # 视觉
    visual_scene: str = ""               # 最近场景描述（LLM 按需填，L0 不调用）
    visual_faces: list[dict] = field(default_factory=list)  # 人脸识别结果
    visual_changed: bool = False         # 画面是否变化

    # 听觉
    audio_scene: str = ""                # 最近声音描述（LLM 按需填）
    audio_voice_id: str | None = None    # 声纹识别结果
    audio_level: float = 0.0             # 音量
    audio_changed: bool = False          # 声音是否变化

    # 发声（最近输出）
    last_spoken: str = ""
    last_played: str = ""

    # 观察到的情绪事件（Path A：ExpressionMonitor 阈值触发 → LLM 上下文）
    # 每项: {"time": float, "event": str, "identity": str|None, "emotion": str, "intensity": float}
    observed_emotions: list[dict] = field(default_factory=list)

    # 通用感官槽位。插件往里塞 section → {key: value}，渲染器自动遍历。
    # 例: {"环境感知": {"温度": 36.5}, "危险感知": {"烟雾浓度": 0.8}}
    sensory: dict[str, dict[str, Any]] = field(default_factory=dict)
