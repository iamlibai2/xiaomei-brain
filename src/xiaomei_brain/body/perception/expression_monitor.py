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

import numpy as np

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
    """后台线程：Camera 订阅帧 → dlib 人脸检测 → FaceID + EmotiEffLib → 双通道推送。

    Path B（每帧）: identity + emotion → drive.apply_social_signal()
    Path A（阈值触发）: 情绪剧变 / 极端情绪 / 持续高强度 → SelfBody.observed_emotions

    纯算法处理器——不持有摄像头，通过 Camera.subscribe_frames() 消费帧。

    Usage:
        monitor = ExpressionMonitor(drive, self_image, face_id, camera)
        monitor.start()
        # ... 后台运行 ...
        monitor.stop()
    """

    def __init__(
        self,
        drive: Any,           # DriveEngine 实例
        self_image: Any,      # SelfImage 实例
        face_id: Any = None,  # FaceID 实例（可选）
        camera: Any = None,   # Camera 设备（body.device.Camera）
        interval: float = 3.0,  # 采样间隔（秒），默认每 3 秒一次
    ) -> None:
        self._drive = drive
        self._si = self_image
        self._face_id = face_id
        self._camera = camera
        self._interval = interval

        self._running = False
        self._thread: threading.Thread | None = None
        self._subscription: Any = None  # FrameSubscription | None

        # Path A 状态跟踪
        self._emotion_history: list[tuple[str, float, float]] = []  # [(emotion, prob, ts), ...]
        self._current_emotion: str | None = None
        self._emotion_start_time: float = 0.0

        # 最近识别到的熟人（供登录等场景复用，避免重复拍照）
        self._last_seen: dict[str, float] = {}  # {identity_name: timestamp}

        # 懒加载
        self._recognizer: Any = None
        self._recognizer_failed: bool = False  # 缓存失败，避免反复重试

    # ── 生命周期 ──────────────────────────────────────────

    def start(self) -> None:
        """启动后台监控线程。"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ExpressionMonitor")
        self._thread.start()
        logger.warning("[ExpressionMonitor] 启动，interval=%.2fs", self._interval)

    def stop(self) -> None:
        """停止后台监控。"""
        self._running = False
        if self._subscription is not None:
            self._subscription.unsubscribe()
        logger.warning("[ExpressionMonitor] 停止")

    def recent_familiar(self, within_seconds: float = 5.0) -> str | None:
        """返回最近 N 秒内识别到的熟人 identity_name，没有则返回 None。"""
        now = time.time()
        for name, ts in self._last_seen.items():
            if now - ts < within_seconds:
                return name
        # 清理过期条目
        self._last_seen = {n: t for n, t in self._last_seen.items() if now - t < within_seconds}
        return None

    # ── 主循环 ────────────────────────────────────────────

    def _loop(self) -> None:
        """后台主循环：通过 Camera.subscribe_frames() 订阅帧 → 处理。"""
        if self._camera is None:
            logger.warning("[ExpressionMonitor] 无摄像头设备，跳过")
            return

        if not hasattr(self._camera, 'subscribe_frames'):
            logger.warning("[ExpressionMonitor] 摄像头不支持流式取帧，跳过")
            return

        sub = self._camera.subscribe_frames(
            self._process_frame, fps=1.0 / self._interval
        )
        if sub is None:
            logger.warning("[ExpressionMonitor] 摄像头流式取帧不可用（设备不支持 subscribe_frames），跳过")
            return

        self._subscription = sub
        logger.warning("[ExpressionMonitor] 已订阅摄像头帧流，interval=%.1fs，开始监控", self._interval)

        # 阻塞等待停止信号
        while self._running:
            time.sleep(0.5)

        sub.unsubscribe()
        self._subscription = None

    def _process_frame(self, frame) -> None:
        """处理单帧：人脸检测 → 情绪分类 → Path B + Path A。"""
        import face_recognition

        t0 = time.time()
        h, w = frame.shape[:2]
        logger.debug("[ExpressionMonitor] 收到帧 %dx%d", w, h)

        # BGR → RGB（ascontiguousarray 必须：切片逆序产生负步长，dlib C++ 不认）
        rgb = np.ascontiguousarray(frame[:, :, ::-1])

        # HOG 人脸检测（快）
        face_locations = face_recognition.face_locations(rgb)
        if not face_locations:
            return

        for top, right, bottom, left in face_locations:
            face_img = rgb[top:bottom, left:right]

            # 跳过太小的人脸
            if face_img.shape[0] < 60 or face_img.shape[1] < 60:
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

        logger.debug("[ExpressionMonitor] 帧处理完成 (%.0fms)", (time.time() - t0) * 1000)

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
        """懒加载 EmotiEffLib ONNX 推理器。只尝试一次，失败后不再重试。"""
        if self._recognizer is not None:
            return
        if self._recognizer_failed:
            raise RuntimeError("EmotiEffLib 已初始化失败（ONNX 模型未下载），跳过")
        try:
            from .face_emotion import EmotiEffLibRecognizer
            self._recognizer = EmotiEffLibRecognizer()
        except Exception:
            self._recognizer_failed = True
            logger.debug("[ExpressionMonitor] EmotiEffLib 初始化失败（ONNX 模型可能未下载），跳过情绪分类")
            raise

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
            encoding = face_recognition.face_encodings(rgb, known_face_locations=[(top, right, bottom, left)])
            if encoding:
                name = self._face_id.match(encoding[0])
                if name:
                    self._last_seen[name] = time.time()
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

        # 条件 1: 极端情绪（概率 >0.6）
        if prob > 0.6:
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
            logger.warning(
                "[ExpressionMonitor] Path A 事件: %s emotion=%s identity=%s probability=%.2f",
                event["event"], event.get("emotion", ""), event.get("identity", "?"), event.get("intensity", 0),
            )
        except Exception:
            logger.debug("[ExpressionMonitor] Path A 推送失败", exc_info=True)
