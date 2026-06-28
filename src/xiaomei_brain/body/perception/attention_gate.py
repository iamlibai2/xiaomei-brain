"""AttentionGate — 注意力门控，连接 VoiceListener 和 Agent 消息入站。

判断逻辑：
  - 对话态外：含"小美"才放行 → 声纹验证 → 切用户 → 进入对话态
  - 对话态内：cheap 特征（ZCR+RMS）判断是不是本人
      → 是本人 → 放行
      → 不是本人 → 含"小美" → 声纹验证 → 切用户
                  → 不含"小美" → 忽略
  - 沉默 > N分钟 → 退出对话态

用法：
    gate = AttentionGate(speaker_id, identity_mgr)
    gate.set_current_user("libai")

    should_pass, target_user = gate.process(text="小美你好", pcm=..., emotion="中性")
    if should_pass:
        living.put_message(text, user_id=target_user)
"""

from __future__ import annotations

import logging
import time
from typing import Callable

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_MINUTES = 3  # 沉默超时退出对话态
WAKE_WORDS = {"小美", "小米", "晓美", "小妹"}  # STT 同音词容错
# Cheap 特征阈值：ZCR 偏离 > 50% 或 RMS 偏离 > 80% 视为不同说话人
ZCR_DEVIATION_THRESHOLD = 0.5


class AttentionGate:
    """注意力门控。

    维护当前说话人声学画像（ZCR + RMS 的 EMA），
    按规则决定是否将语音放行给 Agent。
    """

    def __init__(
        self,
        speaker_id,
        identity_mgr,
        wake_words: list[str] | None = None,
        timeout_minutes: int = DEFAULT_TIMEOUT_MINUTES,
    ) -> None:
        self._speaker_id = speaker_id        # SpeakerID 实例
        self._identity_mgr = identity_mgr    # IdentityManager 实例
        self._wake_words = wake_words or list(WAKE_WORDS)
        self._timeout_s = timeout_minutes * 60

        self._current_user_id: str | None = None
        self._dialog_active = False
        self._last_speech_time = 0.0
        self._on_user_change: Callable[[str], None] | None = None

        # 当前说话人声学画像（EMA 平均）
        self._profile_zcr: float | None = None
        self._profile_rms: float | None = None
        self._ema_smooth = 0.85  # EMA 平滑系数（越小越敏感）

    # ── 公共 API ──────────────────────────────────────────

    def set_current_user(self, user_id: str) -> None:
        """设置登录用户（登录完成后调用）。自动进入对话态。"""
        self._current_user_id = user_id
        self._dialog_active = True
        self._last_speech_time = time.time()
        logger.info("AttentionGate current_user=%s 已自动进入对话态", user_id)

    def set_on_user_change(self, callback: Callable[[str], None]) -> None:
        """设置用户切换回调。当说话人变化时调用，传入新 user_id。"""
        self._on_user_change = callback

    def process(self, text: str, pcm: bytes, emotion: str) -> tuple[bool, str | None]:
        """处理一段语音。

        返回:
            (should_pass, target_user_id)
            - should_pass: 是否放行给 Agent
            - target_user_id: 应该使用的用户ID（None=不切换用户）
        """
        now = time.time()

        # 沉默超时 → 退出对话态
        if self._dialog_active and (now - self._last_speech_time) > self._timeout_s:
            self._dialog_active = False
            self._profile_zcr = None
            self._profile_rms = None
            logger.warning("AttentionGate 沉默超过%d分钟，退出对话态", self._timeout_s // 60)

        self._last_speech_time = now

        has_wake = self._has_wake_word(text)

        logger.warning("AttentionGate process: text=%s has_wake=%s dialog=%s user=%s",
                       text[:40], has_wake, self._dialog_active, self._current_user_id)

        if not self._dialog_active:
            # ── 对话态外：只响应唤醒词 ──
            if has_wake:
                logger.warning("AttentionGate 对话态外检测到唤醒词，开始声纹验证...")
                user_id = self._verify_speaker(pcm)
                if user_id and user_id != self._current_user_id:
                    self._do_switch(user_id)
                self._update_profile(pcm)
                self._dialog_active = True
                logger.warning("AttentionGate 唤醒 → 进入对话态 (user=%s)", self._current_user_id)
                return True, self._current_user_id
            else:
                logger.warning("AttentionGate 对话态外无唤醒词 → 忽略")
                return False, None

        else:
            # ── 对话态内 ──
            zcr = self._extract_zcr(pcm)
            rms_val = self._extract_rms(pcm)
            is_same = self._is_same_speaker(pcm)

            logger.warning("AttentionGate 对话态内: zcr=%.4f rms=%.1f profile_zcr=%s profile_rms=%s is_same=%s",
                           zcr, rms_val,
                           f"{self._profile_zcr:.4f}" if self._profile_zcr else "None",
                           f"{self._profile_rms:.1f}" if self._profile_rms else "None",
                           is_same)

            # 先更新声学画像（无论判定结果，避免 profile 锁死）
            self._update_profile(pcm)

            if is_same:
                logger.warning("AttentionGate 同一说话人 → 放行")
                return True, None  # 同一个人，不切用户

            if has_wake:
                # 换人 + 唤醒词 → 声纹验证 → 切用户
                logger.warning("AttentionGate 不同说话人+唤醒词 → 声纹验证")
                user_id = self._verify_speaker(pcm)
                if user_id:
                    if user_id != self._current_user_id:
                        self._do_switch(user_id)
                else:
                    user_id = "global"
                    if user_id != self._current_user_id:
                        self._do_switch(user_id)
                logger.warning("AttentionGate 切换完成 → 放行 (user=%s)", self._current_user_id)
                return True, None

            # 不同人、没喊名字 → 忽略
            logger.warning("AttentionGate 不同说话人+无唤醒词 → 忽略 (text=%s)", text[:30])
            return False, None

    @property
    def current_user_id(self) -> str | None:
        return self._current_user_id

    @property
    def is_dialog_active(self) -> bool:
        return self._dialog_active

    # ── 唤醒词检测 ────────────────────────────────────────

    @staticmethod
    def _edit_distance(a: str, b: str) -> int:
        """Levenshtein 距离。"""
        if len(a) < len(b):
            a, b = b, a
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            curr = [i]
            for j, cb in enumerate(b, 1):
                curr.append(min(
                    prev[j] + 1,
                    curr[j - 1] + 1,
                    prev[j - 1] + (0 if ca == cb else 1),
                ))
            prev = curr
        return prev[-1]

    def _has_wake_word(self, text: str) -> bool:
        t = text.lower()
        for w in self._wake_words:
            wl = w.lower()
            # 1) 精确匹配
            if wl in t:
                return True
            # 2) 模糊匹配：容忍1字符差异（STT 听错如 bot→boot）
            if len(wl) >= 3:
                n = len(wl)
                for i in range(len(t) - n + 1):
                    sub = t[i:i + n]
                    if self._edit_distance(sub, wl) <= 1:
                        logger.warning("AttentionGate 模糊匹配唤醒词: '%s' ≈ '%s' (text='%s')", wl, sub, text[:40])
                        return True
        return False

    # ── Cheap 声学特征 ────────────────────────────────────

    @staticmethod
    def _extract_zcr(pcm: bytes) -> float:
        """零交叉率（Zero Crossing Rate），音高代理特征。"""
        arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
        arr -= np.mean(arr)  # 去直流偏移
        zcr = np.sum(np.abs(np.diff(np.sign(arr)))) / (2.0 * len(arr))
        return float(zcr)

    @staticmethod
    def _extract_rms(pcm: bytes) -> float:
        """均方根能量。"""
        arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
        return float(np.sqrt(np.mean(arr ** 2)))

    def _update_profile(self, pcm: bytes) -> None:
        """EMA 更新说话人声学画像。"""
        zcr = self._extract_zcr(pcm)
        rms = self._extract_rms(pcm)

        if self._profile_zcr is None:
            self._profile_zcr = zcr
            self._profile_rms = rms
        else:
            self._profile_zcr = self._ema_smooth * self._profile_zcr + (1 - self._ema_smooth) * zcr
            self._profile_rms = self._ema_smooth * self._profile_rms + (1 - self._ema_smooth) * rms

    def _is_same_speaker(self, pcm: bytes) -> bool:
        """用 cheap 特征（ZCR）判断是否同一说话人。"""
        if self._profile_zcr is None:
            return True  # 还没有画像，先放行

        zcr = self._extract_zcr(pcm)
        zcr_dev = abs(zcr - self._profile_zcr) / (self._profile_zcr + 1e-6)
        return zcr_dev < ZCR_DEVIATION_THRESHOLD

    # ── 声纹验证 ──────────────────────────────────────────

    def _verify_speaker(self, pcm: bytes) -> str | None:
        """用 ECAPA-TDNN 声纹验证说话人。返回 user_id 或 None（陌生人）。"""
        try:
            if not self._speaker_id or not self._speaker_id.known_voices:
                return None
            return self._speaker_id.identify(pcm, 16000)
        except Exception:
            logger.exception("声纹验证异常")
            return None

    # ── 用户切换 ──────────────────────────────────────────

    def _do_switch(self, user_id: str) -> None:
        """切换当前用户。"""
        old = self._current_user_id
        self._current_user_id = user_id
        logger.warning("AttentionGate 用户切换: %s → %s", old, user_id)
        if self._on_user_change:
            try:
                self._on_user_change(user_id)
            except Exception:
                logger.exception("on_user_change 回调异常")
