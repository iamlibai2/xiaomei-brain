"""ExpressionMonitor — 独立后台线程，高频实时表情监控。

双通道输出：
- Path B（高频低量）: 身份 + 情绪 → SocialPerception 社交信号 → 间接影响 Drive
- Path A（低频高量）: 阈值触发 → SelfBody.observed_emotions → LLM 上下文

不经过 Body.tick()，独立线程，独立节奏。
类比 VoiceListener：后台持续监听 → 检测到有意义信号 → 推送。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)


# ── 观察到的情绪 → 社交信号映射 ────────────────────────────
#  身份感知：熟悉的人信号强度 1.0x，陌生人 0.3~0.5x

_EMOTION_TO_SIGNAL: dict[str, str | None] = {
    "Happiness": "user_happy",
    "Sadness":   "user_low_mood",
    "Anger":     "user_angry",
    "Fear":      "user_stressed",
    "Disgust":   "user_cold",
    "Surprise":  None,     # 惊讶方向不明，不映射
    "Neutral":   None,     # 中性不产生社交信号
}

_FAMILIAR_SCALE: float = 1.0    # 熟人信号强度系数
_STRANGER_SCALE: float = 0.4    # 陌生人信号强度系数


class ExpressionMonitor:
    """后台线程：cv2 取帧 → dlib 人脸检测 → FaceID + EmotiEffLib → 双通道推送。

    Path B（每帧）: identity + emotion → drive.apply_social_signal()
    Path A（阈值触发）: 情绪剧变 / 极端情绪 / 持续高强度 → SelfBody.observed_emotions

    Usage:
        monitor = ExpressionMonitor(drive, self_image, face_id)
        monitor.start()
        # ... 后台运行 ...
        monitor.stop()
    """

    def __init__(
        self,
        drive: Any,           # DriveEngine 实例
        self_image: Any,      # SelfImage 实例
        face_id: Any = None,  # FaceID 实例（可选）
        interval: float = 0.1,  # 采样间隔（秒），~10 FPS
        camera_id: int = 0,
    ) -> None:
        self._drive = drive
        self._si = self_image
        self._face_id = face_id
        self._interval = interval
        self._camera_id = camera_id

        self._running = False
        self._thread: threading.Thread | None = None

        # Path A 状态跟踪
        self._emotion_history: list[tuple[str, float, float]] = []  # [(emotion, prob, ts), ...]
        self._current_emotion: str | None = None
        self._emotion_start_time: float = 0.0

        # 懒加载
        self._recognizer: Any = None
        self._cap: Any = None

    # ── 生命周期 ──────────────────────────────────────────

    def start(self) -> None:
        """启动后台监控线程。"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ExpressionMonitor")
        self._thread.start()
        logger.info("[ExpressionMonitor] 启动，interval=%.2fs", self._interval)

    def stop(self) -> None:
        """停止后台监控。"""
        self._running = False
        logger.info("[ExpressionMonitor] 停止")

    # ── 主循环 ────────────────────────────────────────────

    def _loop(self) -> None:
        """后台主循环：取帧 → 检测 → 识别 → 推送。"""
        import cv2

        self._cap = cv2.VideoCapture(self._camera_id)
        if not self._cap.isOpened():
            logger.warning("[ExpressionMonitor] 无法打开摄像头 camera_id=%d", self._camera_id)
            return

        try:
            while self._running:
                ret, frame = self._cap.read()
                if not ret:
                    time.sleep(self._interval)
                    continue

                # 处理一帧
                try:
                    self._process_frame(frame)
                except Exception:
                    logger.debug("[ExpressionMonitor] 帧处理异常", exc_info=True)

                time.sleep(self._interval)
        finally:
            self._cap.release()
            self._cap = None

    def _process_frame(self, frame) -> None:
        """处理单帧：人脸检测 → 情绪分类 → Path B + Path A。"""
        import face_recognition

        # BGR → RGB
        rgb = frame[:, :, ::-1]  # cv2 默认 BGR

        # HOG 人脸检测（快）
        face_locations = face_recognition.face_locations(rgb)
        if not face_locations:
            return

        for top, right, bottom, left in face_locations:
            face_img = rgb[top:bottom, left:right]

            # 跳过太小的人脸
            h, w = face_img.shape[:2]
            if h < 60 or w < 60:
                continue

            # 情绪分类
            result = self._classify_emotion(face_img)
            if result is None:
                continue

            # 身份识别（尝试匹配）
            identity = self._identify(rgb, (top, right, bottom, left))

            # Path B: 社交信号 → Drive
            self._push_path_b(identity, result)

            # Path A: 阈值检测 → 事件
            self._check_path_a(identity, result)

    # ── 情绪分类 ──────────────────────────────────────────

    def _classify_emotion(self, face_img) -> dict | None:
        """EmotiEffLib 情绪分类。"""
        try:
            self._init_recognizer()
            return self._recognizer.classify(face_img)
        except Exception:
            logger.debug("[ExpressionMonitor] 情绪分类失败", exc_info=True)
            return None

    def _init_recognizer(self) -> None:
        """懒加载 EmotiEffLib ONNX 推理器。"""
        if self._recognizer is None:
            from .face_emotion import EmotiEffLibRecognizer
            self._recognizer = EmotiEffLibRecognizer()

    # ── 身份识别 ──────────────────────────────────────────

    def _identify(self, rgb, bbox: tuple) -> dict:
        """尝试识别当前人脸的身份。

        Returns:
            {"name": "李白" | None, "familiar": bool}
        """
        if self._face_id is None:
            return {"name": None, "familiar": False}

        try:
            import face_recognition
            top, right, bottom, left = bbox
            encoding = face_recognition.face_encodings(rgb, [(top, right, bottom, left)])
            if encoding:
                name = self._face_id.match(encoding[0])
                return {"name": name, "familiar": name is not None}
        except Exception:
            logger.debug("[ExpressionMonitor] 身份识别失败", exc_info=True)

        return {"name": None, "familiar": False}

    # ── Path B: 社交信号 → Drive ──────────────────────────

    def _push_path_b(self, identity: dict, emotion_result: dict) -> None:
        """每帧推送：情绪 + 身份 → 社交信号 → Drive。

        不做 1:1 映射（"看到笑 ≠ 自己开心"），而是产生社交信号，
        由 Drive.apply_social_signal() 根据现有映射表决定内部反应。
        """
        dominant = emotion_result.get("dominant", "Neutral")
        prob = emotion_result.get("probabilities", {}).get(dominant, 0.0)

        signal_type = _EMOTION_TO_SIGNAL.get(dominant)
        if signal_type is None:
            # Surprise / Neutral → 不产生社交信号
            return

        # 强度：情绪概率 × 信号强度 × 身份系数
        scale = _FAMILIAR_SCALE if identity.get("familiar") else _STRANGER_SCALE
        intensity = min(1.0, prob * scale)

        # 阈值：强度太低忽略（避免噪声）
        if intensity < 0.25:
            return

        try:
            self._drive.apply_social_signal(signal_type, intensity)
        except Exception:
            logger.debug("[ExpressionMonitor] Path B 推送失败", exc_info=True)

    # ── Path A: 阈值事件 → SelfBody ────────────────────────

    def _check_path_a(self, identity: dict, emotion_result: dict) -> None:
        """阈值触发：情绪剧变 / 极端情绪 / 持续高强度 → SelfBody.observed_emotions。"""
        dominant = emotion_result.get("dominant", "Neutral")
        prob = emotion_result.get("probabilities", {}).get(dominant, 0.0)
        now = time.time()

        # 维护最近 30 秒历史
        self._emotion_history.append((dominant, prob, now))
        self._emotion_history = [
            (e, p, t) for e, p, t in self._emotion_history
            if now - t < 30.0
        ]

        event = None

        # 条件 1: 极端情绪（概率 >0.9）
        if prob > 0.9:
            event = {
                "time": now,
                "event": "extreme_emotion",
                "identity": identity.get("name"),
                "familiar": identity.get("familiar", False),
                "emotion": dominant,
                "intensity": prob,
            }

        # 条件 2: 情绪剧变（3秒内 Happiness↔Anger 等对立切换）
        if event is None and len(self._emotion_history) >= 2:
            prev_emotion, prev_prob, prev_ts = self._emotion_history[-2]
            if (
                now - prev_ts < 3.0
                and prev_prob > 0.5 and prob > 0.5
                and self._is_shift(prev_emotion, dominant)
            ):
                event = {
                    "time": now,
                    "event": "emotion_shift",
                    "identity": identity.get("name"),
                    "familiar": identity.get("familiar", False),
                    "from": prev_emotion,
                    "to": dominant,
                    "intensity": prob,
                }

        # 条件 3: 持续高强度（同一情绪 >0.7 持续 >10秒）
        if event is None and prob > 0.7:
            if self._current_emotion == dominant:
                if now - self._emotion_start_time > 10.0:
                    event = {
                        "time": now,
                        "event": "sustained_emotion",
                        "identity": identity.get("name"),
                        "familiar": identity.get("familiar", False),
                        "emotion": dominant,
                        "intensity": prob,
                        "duration": now - self._emotion_start_time,
                    }
                    # 重置计时避免重复触发
                    self._emotion_start_time = now
            else:
                self._current_emotion = dominant
                self._emotion_start_time = now
        else:
            # 强度不够或情绪变了，重置
            if prob <= 0.7:
                self._current_emotion = None
                self._emotion_start_time = 0.0

        # 条件 4: 熟人 + 负面情绪（Anger/Sadness >0.7）
        if event is None and identity.get("familiar") and prob > 0.7:
            if dominant in ("Anger", "Sadness", "Fear"):
                event = {
                    "time": now,
                    "event": "familiar_negative",
                    "identity": identity.get("name"),
                    "familiar": True,
                    "emotion": dominant,
                    "intensity": prob,
                }

        if event:
            self._push_observed_event(event)

    @staticmethod
    def _is_shift(prev: str, cur: str) -> bool:
        """判断是否为有意义的情绪切换。"""
        positive = {"Happiness", "Surprise"}
        negative = {"Anger", "Sadness", "Fear", "Disgust"}
        if prev == cur:
            return False
        return (prev in positive and cur in negative) or (prev in negative and cur in positive)

    def _push_observed_event(self, event: dict) -> None:
        """推送 Path A 事件到 SelfBody.observed_emotions。"""
        try:
            self._si.body.observed_emotions.append(event)
            # 只保留最近 20 条
            if len(self._si.body.observed_emotions) > 20:
                self._si.body.observed_emotions = self._si.body.observed_emotions[-20:]
            logger.info(
                "[ExpressionMonitor] Path A 事件: %s emotion=%s identity=%s",
                event["event"], event.get("emotion", ""), event.get("identity", "?"),
            )
        except Exception:
            logger.debug("[ExpressionMonitor] Path A 推送失败", exc_info=True)
