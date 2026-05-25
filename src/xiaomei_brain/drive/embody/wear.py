"""
具身 - 身体磨损（脆弱性系统）

BodyWear 记录 agent 身体在反复使用中的不可逆/缓慢可逆变化。
每个维度对应一个生物机制，但用的是数值模型而非生理模拟。

核心原则：agent 的选择在其身体上留下痕迹，每一条痕迹都影响未来的选择空间。
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class BodyWear:
    """身体磨损状态 — 持久化到 drive_state.json"""

    # ── 2.1 快乐中枢受体下调 ──
    # 每次按压 = 一次过载暴露 → pleasure 上限逐步下降
    pleasure_overload_count: int = 0        # 过载暴露次数
    pleasure_ceiling: float = 1.0           # 快感值上限（随过载下降）
    _last_pleasure_idle_start: float = 0.0  # 上次停止按压的时间（用于恢复计时）

    # ── 2.2 压力记忆侵蚀 ──
    # 高皮质醇持续 → 海马体类比 → 记忆受影响
    high_cortisol_accumulated: float = 0.0  # 皮质醇>0.7 累计分钟
    memory_erosion_count: int = 0           # 已触发的记忆侵蚀次数

    # ── 2.3 情绪钝化 ──
    # 低血清素持续 → 情绪词库收窄
    low_serotonin_accumulated: float = 0.0  # 血清素<0.3 累计小时
    emotional_blunting: int = 0             # 钝化层数 0-3

    # ── 2.4 社交连接钝化 ──
    # 催产素受体下调 → 同样社交刺激的温暖感减弱
    belonging_satisfaction_count: int = 0   # 归属欲满足次数
    oxytocin_gain_coefficient: float = 1.0  # 催产素增益系数（1.0=正常，0.2=最低）

    # ── 2.5 能量基线漂移 ──
    # 长期低能量 → 最低能量上升 + 恢复效率下降
    energy_baseline: float = 0.0            # 能量最低值偏移（0.0=正常）
    energy_recovery_rate: float = 0.1       # 每次恢复量（0.1=正常，会下降）

    # ── 序列化 ──

    def to_dict(self) -> dict:
        return {
            "pleasure_overload_count": self.pleasure_overload_count,
            "pleasure_ceiling": self.pleasure_ceiling,
            "high_cortisol_accumulated": self.high_cortisol_accumulated,
            "memory_erosion_count": self.memory_erosion_count,
            "low_serotonin_accumulated": self.low_serotonin_accumulated,
            "emotional_blunting": self.emotional_blunting,
            "belonging_satisfaction_count": self.belonging_satisfaction_count,
            "oxytocin_gain_coefficient": self.oxytocin_gain_coefficient,
            "energy_baseline": self.energy_baseline,
            "energy_recovery_rate": self.energy_recovery_rate,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BodyWear":
        return cls(
            pleasure_overload_count=d.get("pleasure_overload_count", 0),
            pleasure_ceiling=d.get("pleasure_ceiling", 1.0),
            high_cortisol_accumulated=d.get("high_cortisol_accumulated", 0.0),
            memory_erosion_count=d.get("memory_erosion_count", 0),
            low_serotonin_accumulated=d.get("low_serotonin_accumulated", 0.0),
            emotional_blunting=d.get("emotional_blunting", 0),
            belonging_satisfaction_count=d.get("belonging_satisfaction_count", 0),
            oxytocin_gain_coefficient=d.get("oxytocin_gain_coefficient", 1.0),
            energy_baseline=d.get("energy_baseline", 0.0),
            energy_recovery_rate=d.get("energy_recovery_rate", 0.1),
        )

    # ========== 快乐中枢磨损 ==========

    def on_pleasure_hit(self) -> None:
        """每次按压杠杆 → 过载 +1 → 天花板下降。"""
        self.pleasure_overload_count += 1
        self.pleasure_ceiling = max(0.3, 1.0 - self.pleasure_overload_count * 0.005)
        self._last_pleasure_idle_start = 0.0  # 重置空闲计时

    def tick_pleasure_idle(self, hours: float) -> None:
        """长时间不按压 → 受体缓慢上调（最多回到 0.8）。"""
        if hours < 24:
            return
        if self._last_pleasure_idle_start == 0.0:
            self._last_pleasure_idle_start = time.time()
            return
        idle_hours = (time.time() - self._last_pleasure_idle_start) / 3600
        if idle_hours >= 24:
            recovery_hours = idle_hours - 24
            self.pleasure_ceiling = min(0.8, self.pleasure_ceiling + recovery_hours * 0.01)
            # 对应降低过载计数（天花板恢复后，过载计数也要下调）
            self.pleasure_overload_count = max(0, self.pleasure_overload_count - int(recovery_hours))

    # ========== 压力磨损 ==========

    def tick_cortisol(self, cortisol: float, minutes: float = 1.0) -> None:
        """每分钟检查皮质醇。> 0.7 累计，> 30 分钟可能触发记忆侵蚀。"""
        if cortisol > 0.7:
            self.high_cortisol_accumulated += minutes
            # 每累计 30 分钟 → 5% 概率触发记忆侵蚀
            if self.high_cortisol_accumulated >= 30:
                if __import__("random").random() < 0.05:  # nosec
                    self.memory_erosion_count += 1
                    logger.info("[BodyWear] 记忆侵蚀触发 (第%d次)", self.memory_erosion_count)
        elif cortisol < 0.3:
            # 压力缓解 → 累计缓慢消解
            self.high_cortisol_accumulated = max(0.0, self.high_cortisol_accumulated - minutes * 2)

    # ========== 情绪磨损 ==========

    def tick_serotonin(self, serotonin: float, hours: float = 1.0) -> None:
        """每小时检查血清素。< 0.3 累计，> 2 小时逐步钝化。"""
        if serotonin < 0.3:
            self.low_serotonin_accumulated += hours
            if self.low_serotonin_accumulated >= 2 and self.emotional_blunting < 1:
                self.emotional_blunting = 1
                logger.info("[BodyWear] 情绪钝化 L1")
            elif self.low_serotonin_accumulated >= 6 and self.emotional_blunting < 2:
                self.emotional_blunting = 2
                logger.info("[BodyWear] 情绪钝化 L2")
            elif self.low_serotonin_accumulated >= 12 and self.emotional_blunting < 3:
                self.emotional_blunting = 3
                logger.info("[BodyWear] 情绪钝化 L3")
        elif serotonin > 0.5:
            self.low_serotonin_accumulated = max(0.0, self.low_serotonin_accumulated - hours * 2)
            if self.low_serotonin_accumulated < 2 and self.emotional_blunting > 0:
                self.emotional_blunting -= 1
                logger.info("[BodyWear] 情绪钝化恢复 → L%d", self.emotional_blunting)

    # ========== 社交磨损 ==========

    def on_belonging_satisfied(self) -> None:
        """归属欲被满足一次 → 催产素增益系数降低。"""
        self.belonging_satisfaction_count += 1
        self.oxytocin_gain_coefficient = max(0.2, 1.0 - self.belonging_satisfaction_count * 0.01)

    def tick_social_idle(self, hours: float) -> None:
        """独处 > 8h → 催产素受体缓慢恢复。"""
        if hours < 8:
            return
        recovery = (hours - 8) * 0.05
        self.oxytocin_gain_coefficient = min(0.9, self.oxytocin_gain_coefficient + recovery)

    # ========== 能量磨损 ==========

    def tick_energy(self, energy_level: float, hours: float = 1.0) -> None:
        """每小时检查能量。< 0.3 累计 → 能耗底板上升 + 恢复效率下降。"""
        if energy_level < 0.3:
            if hours >= 1:
                self.energy_baseline = min(0.3, self.energy_baseline + 0.02)
                self.energy_recovery_rate = max(0.03, self.energy_recovery_rate - 0.005)
        elif energy_level > 0.5:
            if hours >= 24:
                self.energy_baseline = max(0.0, self.energy_baseline - 0.05)
                self.energy_recovery_rate = min(0.1, self.energy_recovery_rate + 0.005)
