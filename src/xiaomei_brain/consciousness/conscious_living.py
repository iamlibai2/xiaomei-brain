"""ConsciousLiving: 带意识的 Agent 生命周期测试版。

基于 AgentLiving，集成意识系统（火焰骨架 + LLM加柴）。

核心改变：
- 主循环每秒调用 tick_L0（火焰骨架维护）
- 动态加柴时机（异常触发、复杂反思、用户空闲）
- Intent 消费测试（执行命令）

状态流转：
    DORMANT → WAKING → AWAKE ⇄ SLEEPING → DREAMING → SLEEPING ...

与 AgentLiving 的区别：
- 意识系统独立运行（火焰骨架）
- 动态 LLM 加柴（不是固定频率）
- Intent 可触发行为

Usage:
    from xiaomei_brain.consciousness.conscious_living import ConsciousLiving
    from xiaomei_brain.agent.agent_manager import AgentManager

    manager = AgentManager()
    agent = manager.build_agent("xiaomei")

    living = ConsciousLiving(agent)
    living.put_message("你好")
    living.run()  # blocking
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from .core import Consciousness, ConsciousnessReport
from .intent import Intent, IntentType
from .storage import ConsciousnessStorage
from .self_image import SelfImage, FlameState

logger = logging.getLogger(__name__)


# ── States ──────────────────────────────────────────────────────────────

class LivingState(Enum):
    DORMANT = "dormant"
    WAKING = "waking"
    AWAKE = "awake"
    IDLE = "idle"
    SLEEPING = "sleeping"
    DREAMING = "dreaming"


# ── Message ─────────────────────────────────────────────────────────────

@dataclass
class LivingMessage:
    """外部消息"""
    content: str
    user_id: str = "global"
    session_id: str = "main"
    source: str = ""


# ── ConsciousLiving ─────────────────────────────────────────────────────

class ConsciousLiving:
    """带意识的 Agent 生命周期。

    主循环：
    - 每秒调用 tick_L0（火焰骨架）
    - 每分钟调用 tick_L1（异常检测）
    - 动态触发 L2/L3（LLM加柴）

    Intent 消费：
    - 测试命令：`intent` 查看当前意图
    - 测试命令：`fuel` 手动触发加柴
    """

    def __init__(
        self,
        agent_instance: Any,
        idle_threshold: float = 1800,
        dream_interval: float = 300,
        idle_short: float = 30,
        session_id: str = "main",
        user_id: str = "global",
        tick_interval: float = 1.0,  # L0 心跳间隔（秒）
    ) -> None:
        self.agent = agent_instance
        self.state = LivingState.DORMANT
        self.idle_threshold = idle_threshold
        self.dream_interval = dream_interval
        self.idle_short = idle_short
        self.session_id = session_id
        self.user_id = user_id
        self.tick_interval = tick_interval

        # 消息队列
        self._queue: queue.Queue[LivingMessage | None] = queue.Queue()
        self._last_active: float = 0
        self._running: bool = False

        # 意识系统
        self.consciousness = Consciousness(agent_instance)
        self._setup_consciousness()

        # L0 心跳计数
        self._tick_count: int = 0

        # 上次加柴时间（用于动态判断）
        self._last_fuel_time: float = 0

        # Intent 测试命令
        self._intent_commands = {
            "intent": self._cmd_show_intent,
            "fuel": self._cmd_manual_fuel,
            "flame": self._cmd_show_flame,
            "tick": self._cmd_tick_count,
        }

        # 回调
        self.on_proactive: Callable[[Any], Any] | None = None
        self.on_chat_chunk: Callable[[str], Any] | None = None

    def _setup_consciousness(self) -> None:
        """初始化意识系统（尝试从存储恢复）"""
        # 设置存储
        import os
        base_dir = os.path.expanduser("~/.xiaomei-brain")
        storage = ConsciousnessStorage(base_dir, agent_id="xiaomei")
        self.consciousness.set_storage(storage)

        # 尝试恢复 SelfImage
        restored = self.consciousness.restore_from_storage()

        if not restored:
            # 无历史记录，使用默认值初始化
            si = self.consciousness.get_self_image()
            si.identity = "小美"
            si.role = "情感陪伴"
            logger.info("[ConsciousLiving] SelfImage 使用默认值初始化")

        # 显示当前火焰状态
        si = self.consciousness.get_self_image()
        logger.info(
            "[ConsciousLiving] 意识系统初始化完成: age=%ds, identity=%s",
            int(si.consciousness_age),
            si.identity,
        )

    # ── Public API ───────────────────────────────────────────────

    def put_message(
        self,
        content: str,
        user_id: str | None = None,
        session_id: str | None = None,
        source: str = "",
    ) -> None:
        """放入消息"""
        msg = LivingMessage(
            content=content,
            user_id=user_id or self.user_id,
            session_id=session_id or self.session_id,
            source=source,
        )
        self._queue.put_nowait(msg)

    def run(self) -> None:
        """主循环，阻塞运行"""
        self._running = True

        # DORMANT → WAKING
        self._transition(LivingState.WAKING)
        self._on_wake()
        self._transition(LivingState.AWAKE)

        # 主循环
        while self._running:
            if self.state == LivingState.AWAKE:
                self._loop_awake()
            elif self.state == LivingState.SLEEPING:
                self._loop_sleeping()
            elif self.state == LivingState.DREAMING:
                self._loop_dreaming()
            else:
                logger.warning("[ConsciousLiving] Unexpected state: %s", self.state)
                time.sleep(1)

    def stop(self) -> None:
        """停止主循环"""
        self._running = False
        self._queue.put_nowait(None)

    @property
    def is_running(self) -> bool:
        """是否正在运行"""
        return self._running

    @property
    def living_state(self) -> str:
        """返回当前状态（供 Consciousness._sense() 使用）"""
        return self.state.value

    # ── State transitions ────────────────────────────────────────

    def _transition(self, new_state: LivingState) -> None:
        old = self.state
        self.state = new_state
        logger.info("[ConsciousLiving] %s → %s", old.value, new_state.value)

        # 更新意识系统中的 agent_state
        si = self.consciousness.get_self_image()
        si.agent_state = new_state.value

    # ── Loop: AWAKE ──────────────────────────────────────────────

    def _loop_awake(self) -> None:
        """AWAKE 状态：处理消息 + 火焰心跳"""
        # 火焰心跳（每秒）
        self._tick_flame()

        # 等待消息
        msg = self._wait_message(timeout=self.tick_interval)

        if msg is not None:
            self._handle_message(msg)
            self._last_active = time.time()
            return

        # 空闲检测
        if time.time() - self._last_active >= self.idle_threshold:
            self._transition(LivingState.SLEEPING)

    # ── Loop: SLEEPING ───────────────────────────────────────────

    def _loop_sleeping(self) -> None:
        """SLEEPING 状态：火焰心跳 + 消息等待 + 梦境触发"""
        # 火焰心跳（每秒）
        self._tick_flame()

        # 检查 Intent
        self._check_intent()

        # 动态加柴判断
        self._check_dynamic_fuel()

        # 等待消息
        msg = self._wait_message(timeout=self.dream_interval)

        if msg is not None:
            self._on_wake_up()
            self._transition(LivingState.AWAKE)
            self._handle_message(msg)
            self._last_active = time.time()
            return

        # 触发梦境
        self._transition(LivingState.DREAMING)

    # ── Loop: DREAMING ───────────────────────────────────────────

    def _loop_dreaming(self) -> None:
        """DREAMING 状态：L3 深度燃烧"""
        # L3：LLM深度加柴
        report = self.consciousness.tick_L3()
        logger.info("[ConsciousLiving] L3燃烧: %s", report.summary[:50])

        # 回到 SLEEPING
        self._transition(LivingState.SLEEPING)

    # ── Flame heartbeat ──────────────────────────────────────────

    def _tick_flame(self) -> None:
        """火焰骨架心跳（每秒）"""
        self._tick_count += 1

        # L0：火焰骨架维护
        flame_state = self.consciousness.tick_L0()

        # L1：每60秒检测异常
        if self._tick_count >= 60:
            self._tick_count = 0
            report = self.consciousness.tick_L1()
            if report:
                logger.info("[ConsciousLiving] L1异常: %s", report.anomaly)

    def _check_dynamic_fuel(self) -> None:
        """动态加柴判断

        触发条件：
        - 用户空闲超过5分钟 → L2问候
        - 异常检测触发 → L2处理
        - 累积变化超过阈值 → L2理解
        - 上次加柴超过10分钟 → L2定期加柴
        """
        si = self.consciousness.get_self_image()
        elapsed_since_fuel = time.time() - self._last_fuel_time

        # 条件1：用户空闲超过5分钟
        if si.user_idle_duration > 300:
            logger.info("[ConsciousLiving] 动态加柴：用户空闲5分钟")
            self._fuel_L2("user_idle_long")
            return

        # 条件2：累积变化超过10条
        if len(si.accumulated_changes) > 10:
            logger.info("[ConsciousLiving] 动态加柴：累积变化%d条", len(si.accumulated_changes))
            self._fuel_L2("accumulated_changes")
            return

        # 条件3：上次加柴超过10分钟
        if elapsed_since_fuel > 600:
            logger.info("[ConsciousLiving] 动态加柴：定期加柴（10分钟）")
            self._fuel_L2("periodic")
            return

    def _fuel_L2(self, context: str) -> None:
        """L2加柴"""
        self._last_fuel_time = time.time()
        report = self.consciousness.tick_L2(context)
        logger.info("[ConsciousLiving] L2加柴: %s", report.summary[:50])

        # 检查生成的 Intent
        intent = self.consciousness.get_pending_intent()
        if intent:
            logger.info("[ConsciousLiving] 意图生成: %s (%s)", intent.type.value, intent.content[:30])

    # ── Intent 消费 ──────────────────────────────────────────────

    def _check_intent(self) -> None:
        """检查并消费 Intent"""
        intent = self.consciousness.get_pending_intent()
        if not intent:
            return

        # 根据 Intent 类型执行不同动作
        if intent.type == IntentType.GREET:
            self._execute_greet_intent(intent)
        elif intent.type == IntentType.CARE:
            self._execute_care_intent(intent)
        elif intent.type == IntentType.REFLECT:
            self._execute_reflect_intent(intent)
        elif intent.type == IntentType.ACT:
            self._execute_act_intent(intent)
        else:
            logger.debug("[ConsciousLiving] Intent暂不执行: %s", intent.type.value)

    def _execute_greet_intent(self, intent: Intent) -> None:
        """执行问候意图（测试版：打印日志）"""
        logger.info("[ConsciousLiving/Intent] 问候用户: %s", intent.content)

        # 清费意图
        self.consciousness.consume_intent()

        # TODO: 实际发送消息到用户（需要渠道回调）
        # self._send_proactive(...)

    def _execute_care_intent(self, intent: Intent) -> None:
        """执行关心意图"""
        logger.info("[ConsciousLiving/Intent] 关心用户: %s", intent.content)
        self.consciousness.consume_intent()

    def _execute_reflect_intent(self, intent: Intent) -> None:
        """执行反省意图：触发 L3"""
        logger.info("[ConsciousLiving/Intent] 触发深度反省: %s", intent.content)
        self.consciousness.consume_intent()

        # 反省 → L3 深度燃烧
        report = self.consciousness.tick_L3()
        logger.info("[ConsciousLiving/Intent] 反省报告: %s", report.summary[:50])

    def _execute_act_intent(self, intent: Intent) -> None:
        """执行行动意图"""
        logger.info("[ConsciousLiving/Intent] 执行行动: %s", intent.content)
        self.consciousness.consume_intent()

    # ── Message handling ─────────────────────────────────────────

    def _handle_message(self, msg: LivingMessage) -> None:
        """处理消息"""
        # Intent 测试命令
        if msg.content.lower() in self._intent_commands:
            cmd = msg.content.lower()
            self._intent_commands[cmd]()
            return

        # Agent 命令（如 db/memory/dag）
        if self.agent.commands:
            result = self.agent.commands.execute(
                msg.content,
                user_id=msg.user_id,
                session_id=msg.session_id,
            )
            if result:
                logger.info("[ConsciousLiving] Command: %s", result.output)
                return

        # 正常对话
        try:
            content = self.agent.chat(
                msg.content,
                session_id=msg.session_id,
                user_id=msg.user_id,
                on_chunk=self.on_chat_chunk,
            )
            if self.on_chat_chunk:
                print()
            logger.info("[ConsciousLiving] Response: %s", content[:80].replace("\n", "\\n"))

            # 更新意识系统
            self.consciousness.on_user_interaction(msg.content, content)
        except Exception as e:
            logger.error("[ConsciousLiving] Chat failed: %s", e)

    def _wait_message(self, timeout: float) -> LivingMessage | None:
        """等待消息"""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    # ── Intent 测试命令 ──────────────────────────────────────────

    def _cmd_show_intent(self) -> None:
        """显示当前 Intent"""
        intent = self.consciousness.get_pending_intent()
        if intent:
            print(f"当前意图: {intent.type.value} (priority={intent.priority})")
            print(f"内容: {intent.content}")
        else:
            print("无待处理意图")

    def _cmd_manual_fuel(self) -> None:
        """手动触发加柴"""
        print("手动触发 L2 加柴...")
        self._fuel_L2("manual")

        intent = self.consciousness.get_pending_intent()
        if intent:
            print(f"生成的意图: {intent.type.value}")
            print(f"内容: {intent.content[:50]}")

    def _cmd_show_flame(self) -> None:
        """显示火焰状态"""
        si = self.consciousness.get_self_image()
        print(f"火焰状态:")
        print(f"  燃烧时长: {int(si.consciousness_age)}秒")
        print(f"  状态: {si.agent_state}")
        print(f"  用户空闲: {int(si.user_idle_duration)}秒")
        print(f"  能量: {si.energy_level:.2f}")
        print(f"  累积变化: {len(si.accumulated_changes)}条")
        print(f"  上次加柴: {int(time.time() - self._last_fuel_time)}秒前")

    def _cmd_tick_count(self) -> None:
        """显示心跳计数"""
        print(f"心跳计数: {self._tick_count}")
        print(f"状态: {self.state.value}")

    # ── Hooks ────────────────────────────────────────────────────

    def _on_wake(self) -> None:
        """苏醒（不调用LLM，简单启动）"""
        self._last_active = time.time()
        self._last_fuel_time = time.time()

        # 火焰点燃，不调用LLM
        si = self.consciousness.get_self_image()
        si.last_user_activity_time = time.time()

        logger.info("[ConsciousLiving] Good morning! 火焰点燃。")

    def _on_wake_up(self) -> None:
        """从睡眠中醒来"""
        logger.info("[ConsciousLiving] Waking up — message received!")

    # ── Proactive output ─────────────────────────────────────────

    def _send_proactive(self, content: str) -> None:
        """发送主动消息（测试版）"""
        logger.info("[ConsciousLiving/Proactive] %s", content[:60])

        if self.agent.conversation_db:
            try:
                self.agent.conversation_db.log(
                    session_id=self.session_id,
                    role="assistant",
                    content=f"[主动] {content}",
                )
            except Exception:
                pass

        if self.on_proactive:
            self.on_proactive(content)