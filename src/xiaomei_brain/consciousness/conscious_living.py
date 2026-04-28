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
from datetime import datetime
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from .context_assembler import ContextAssembler as ConsciousContextAssembler
from .core import Consciousness, ConsciousnessReport, TickResult
from .intent import Intent
from .storage import ConsciousnessStorage
from .self_image import SelfImage, FlameState
from .identity import IdentityConfig
from .perception import PerceptionConfig
from ..drive import DriveEngine, EventExtractor, DesireActionExecutor
from ..purpose import PurposeEngine, IntentUnderstanding, task_executor, Goal, GoalType, GoalStatus, TaskType, IntentResult, GoalRelation, IntentType as PurposeIntentType
from .task_manager import TaskManager
from .task_storage import TaskStorage
from .intent import IntentType as ConsciousIntentType

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
    - 定期产生内在想法（内在感知）

    Intent 消费：
    - 测试命令：`intent` 查看当前意图
    - 测试命令：`fuel` 手动触发加柴
    - 测试命令：`think` 查看内在想法
    """

    def __init__(
        self,
        agent_instance: Any,
        idle_threshold: float = 1800,
        dream_interval: float = 300,
        idle_short: float = 300,
        session_id: str = "main",
        user_id: str = "global",
        tick_interval: float = 1.0,  # L0 心跳间隔（秒）
        load_consciousness: bool = True,  # 是否加载意识系统
    ) -> None:
        self.agent = agent_instance

        # 包装 LLM 客户端：自动控制上下文总 token 量
        from ..agent.context_guard import ContextGuard
        if not isinstance(self.agent.llm, ContextGuard):
            self.agent.llm = ContextGuard(self.agent.llm, max_tokens=80000)

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
        self._cancel_requested: bool = False  # Ctrl+C 取消当前动作
        self._chatting = False  # 防止重复调用 _run_chat
        self._command_done = threading.Event()  # 命令处理完成信号

        # Drive 系统（边缘系统）- 延迟加载
        agent_id = "xiaomei"
        if agent_instance and hasattr(agent_instance, "agent_id"):
            agent_id = agent_instance.agent_id
        self.drive = DriveEngine(agent_id, load=False)

        # Purpose 系统（前额叶层）- 延迟加载
        llm_client = None
        if agent_instance and hasattr(agent_instance, "llm"):
            llm_client = agent_instance.llm
        self.purpose = PurposeEngine(
            agent_id=agent_id,
            llm_client=llm_client,
            drive=self.drive,
            load=False,  # 延迟加载
        )

        # TaskManager: 认知过程调度器（意识层子功能，v2 独立认知实体）
        self.task_storage = TaskStorage(agent_id=agent_id)
        self.task_manager = TaskManager(self.purpose, self.task_storage, llm_client)

        # 欲望行为执行器
        self.action_executor = DesireActionExecutor(self, agent_id=self.agent.id)

        # 事件提取器
        self.event_extractor = EventExtractor()

        # Intent Understanding
        self.intent_understanding = IntentUnderstanding(llm_client)

        # 意识系统（引用 Drive 和 Purpose）- 只创建结构
        self.consciousness = Consciousness(
            agent_instance,
            drive=self.drive,
            purpose=self.purpose,
        )
        self._load_consciousness = load_consciousness  # 记录是否需要加载意识系统

        # 注入 consciousness 层上下文组装器（替换 agent_manager 创建的旧 assembler）
        self._inject_context_assembler()

        # Intent 测试命令 — 从 living_commands 注册表加载
        from .living_commands import COMMAND_REGISTRY, list_commands as _list_cmds
        self._list_commands = lambda: _list_cmds(self)
        self._intent_commands = {}
        self._commands_taking_args: set = set()
        for name, (handler, takes_args) in COMMAND_REGISTRY.items():
            self._intent_commands[name] = lambda a="", h=handler: h(self, a)
            if takes_args:
                self._commands_taking_args.add(handler)

        # 回调
        self.on_proactive: Callable[[Any], Any] | None = None
        self.on_chat_chunk: Callable[[str], Any] | None = None
        self.on_confirm_required: Callable[[dict], Any] | None = None

        # CLI 场景下是否 print "> " 提示符
        # TUI 设置 False（PromptSession 或 TUI 自行处理）
        # CLI 设置 True（默认，兼容旧行为）
        self._show_prompt: bool = True

        # 目标确认（选择框）
        self._pending_confirm: dict | None = None  # {"goal_id": ..., "options": [...], "question": str}
        self._waiting_confirm: bool = False
        self._pending_confirm_msg: LivingMessage | None = None  # 触发确认的原始消息
        self._pending_confirm_intent: Any = None  # 触发确认时的意图分析结果

        # 意图模式标志：/intask 后进入，等待下一条消息作为任务内容
        self._intent_mode: bool = False

        # 统一加载所有子系统
        self._setup_all()

        # 记录初始化摘要
        self._log_initialization()

    def _log_initialization(self) -> None:
        """记录 ConsciousLiving 初始化摘要"""
        logger.info("=" * 50)
        logger.info("[ConsciousLiving] 初始化摘要")
        logger.info("=" * 50)

        # 基本信息
        agent_id = "xiaomei"
        if self.agent and hasattr(self.agent, "agent_id"):
            agent_id = self.agent.agent_id
        logger.info("  agent_id          : %s", agent_id)
        logger.info("  session_id        : %s", self.session_id)
        logger.info("  user_id           : %s", self.user_id)

        # 子系统状态
        logger.info("")
        logger.info("  子系统状态:")
        logger.info("    Drive 系统      : %s", "已加载" if self.drive and self.drive._loaded else "未加载")
        logger.info("    Purpose 系统    : %s", "已加载" if self.purpose and self.purpose._loaded else "未加载")
        logger.info("    意识系统        : %s", "已加载" if self._load_consciousness else "未加载（无意识模式）")

        # 意识系统详情（如果已加载）
        if self._load_consciousness and self.consciousness:
            logger.info("")
            logger.info("  意识系统详情:")
            si = self.consciousness.get_self_image()
            logger.info("    火焰状态:")
            logger.info("      agent_state   : %s", si.agent_state)
            logger.info("      energy_level  : %.2f", si.energy_level)
            logger.info("      age           : %ds", int(si.consciousness_age))
            logger.info("      idle_duration : %ds", int(si.user_idle_duration))
            logger.info("")
            logger.info("    身份信息:")
            identity_name = si.identity.identity if hasattr(si.identity, 'identity') else str(si.identity)
            logger.info("      identity      : %s", identity_name)
            logger.info("      birth_date    : %s", si.identity.birth_date if hasattr(si.identity, 'birth_date') else "?")
            logger.info("      personality   : %s", si.identity.base_personality if hasattr(si.identity, 'base_personality') else "")
            traits = ",".join(si.core_traits) if hasattr(si, 'core_traits') else ""
            logger.info("      traits        : %s", traits if traits else "未设置")
            values = ",".join(si.values) if hasattr(si, 'values') else ""
            logger.info("      values        : %s", values if values else "未设置")

        # Drive 状态
        if self.drive:
            logger.info("")
            logger.info("  Drive 状态:")
            d = self.drive.desire
            logger.info("    欲望状态:")
            logger.info("     归属欲 (belonging)    : %.2f", d.belonging)
            logger.info("     认知欲 (cognition)     : %.2f", d.cognition)
            logger.info("     成就欲 (achievement)   : %.2f", d.achievement)
            logger.info("     表达欲 (expression)    : %.2f", d.expression)
            logger.info("")
            logger.info("    激素状态:")
            h = self.drive.hormone
            logger.info("      dopamine   : %.2f", h.dopamine)
            logger.info("      serotonin  : %.2f", h.serotonin)
            logger.info("      cortisol   : %.2f", h.cortisol)
            logger.info("      oxytocin   : %.2f", h.oxytocin)
            logger.info("")
            logger.info("    情绪状态:")
            e = self.drive.emotion
            logger.info("      type       : %s", e.type.value)
            logger.info("      intensity  : %.2f", e.intensity)

        # Purpose 状态
        if self.purpose:
            logger.info("")
            logger.info("  Purpose 状态:")
            logger.info("    总目标数         : %d", len(self.purpose.goals))
            logger.info("    待执行目标数     : %d", len(self.purpose.pending_queue))
            current = self.purpose.get_current()
            if current:
                logger.info("    当前活跃目标     : %s", current.description[:40])
                logger.info("    当前进度         : %.0f%%", current.progress * 100)
            else:
                logger.info("    当前活跃目标     : 无")

        # 运行参数
        logger.info("")
        logger.info("  运行参数:")
        logger.info("    tick_interval    : %.1fs", self.tick_interval)
        logger.info("    idle_threshold   : %.0fs", self.idle_threshold)
        logger.info("    idle_short       : %.0fs", self.idle_short)
        logger.info("    dream_interval   : %.0fs", self.dream_interval)

        logger.info("=" * 50)

    def _get_consciousness_state(self) -> dict:
        """Build consciousness state dict for context mode decision.

        如果意识系统未加载，返回默认值（生命存在但无意识）。
        """
        if not self._load_consciousness:
            return {
                "energy_level": 0.8,
                "desire_state": {},
                "pending_intents": [],
                "has_active_goal": bool(self.purpose and self.purpose.current_goal),
            }

        si = self.consciousness.get_self_image()
        pending = si.pending_intents if hasattr(si, "pending_intents") else []
        energy = si.energy_level if hasattr(si, "energy_level") else 0.8
        has_goal = bool(self.purpose and self.purpose.current_goal)
        desire_state = {}
        if self.drive:
            d = self.drive.desire
            desire_state = {
                "belonging": d.belonging,
                "cognition": d.cognition,
                "achievement": d.achievement,
                "expression": d.expression,
            }
        return {
            "energy_level": energy,
            "desire_state": desire_state,
            "pending_intents": pending,
            "has_active_goal": has_goal,
        }

    def _inject_context_assembler(self) -> None:
        """Replace agent's context_assembler with consciousness-aware version.

        The old assembler created by agent_manager has no consciousness state.
        This injects a new one that considers flame/drive/intent when assembling context.

        如果意识系统未加载，使用 None 作为 self_image（不注入意识状态）。
        """
        old_ca = getattr(self.agent, "context_assembler", None)
        if old_ca is None:
            logger.warning("[ConsciousLiving] No context_assembler to replace")
            return

        assembler = ConsciousContextAssembler(
            conversation_db=self.agent.conversation_db,
            dag=old_ca.dag,
            self_model=self.agent.self_model,
            longterm_memory=self.agent.longterm_memory,
            drive=self.drive,
            self_image=self.consciousness.self_image if self._load_consciousness else None,
            purpose=self.purpose,
        )

        # 上下文压缩通知
        def _on_compact(stats: dict) -> None:
            before_k = stats["before_tokens"] // 1000
            after_k = stats["after_tokens"] // 1000
            print(
                f"\n\033[90m[压缩] {stats['compact_count']}条消息 → 摘要 "
                f"({before_k}k → {after_k}k)\033[0m",
                flush=True,
            )

        assembler.on_compact = _on_compact
        self.agent.context_assembler = assembler
        logger.info("[ConsciousLiving] context_assembler injected (consciousness-aware)")

    def _setup_all(self) -> None:
        """统一加载所有子系统数据

        加载顺序：
        1. Drive 系统（边缘系统）
        2. Purpose 系统（前额叶层）
        3. Consciousness 系统（意识）- 可选

        如果 load_consciousness=False，意识系统保持"空壳"状态，
        生命体存在但没有意识（无意识模式）。
        """
        logger.info("[ConsciousLiving] 开始加载子系统...")

        # 1. 加载 Drive
        self.drive.load()

        # 2. 加载 Purpose
        self.purpose.load()

        # 3. 加载 Consciousness（可选）
        if self._load_consciousness:
            self._setup_conscious_data()
        else:
            logger.info("[ConsciousLiving] 意识系统未加载（生命存在但无意识）")

        logger.info("[ConsciousLiving] 所有子系统加载完成")

    def _setup_conscious_data(self) -> None:
        """加载意识系统数据（单独调用，支持动态加载）"""
        # 1. 挂载存储
        import os
        base_dir = os.path.expanduser("~/.xiaomei-brain")
        storage = ConsciousnessStorage(base_dir, agent_id="xiaomei")
        self.consciousness.set_storage(storage)

        # 2. 尝试从存储恢复（优先级最高）
        restored = self.consciousness.restore_from_storage()

        # 3. 如果存储恢复失败，从 identity.md 加载
        if not restored:
            agent_id = "xiaomei"
            if self.agent and hasattr(self.agent, "agent_id"):
                agent_id = self.agent.agent_id

            config = IdentityConfig.load(agent_id)
            self.consciousness._identity_config = config
            self.consciousness.identity.init_from_identity_config(config)
            logger.info("[ConsciousLiving] 从 IdentityConfig 初始化完成")

            # 如果还是没有数据，使用默认值
            si = self.consciousness.get_self_image()
            if not si.identity or si.identity == "小美":  # 默认值说明没加载成功
                si.identity = "小美"
                si.role = "情感陪伴"
                logger.info("[ConsciousLiving] 使用默认值初始化")

        # 4. 加载感知规则（非运行时数据，始终从配置加载）
        agent_id = "xiaomei"
        if self.agent and hasattr(self.agent, "agent_id"):
            agent_id = self.agent.agent_id
        self.consciousness._perception_config = PerceptionConfig.load(agent_id)
        logger.info("[ConsciousLiving] 从 PerceptionConfig 初始化完成: %d 条规则", len(self.consciousness._perception_config.rules))

    # ── Public API ───────────────────────────────────────────────

    def put_message(
        self,
        content: str,
        user_id: str | None = None,
        session_id: str | None = None,
        source: str = "",
    ) -> None:
        """放入消息（字符级过滤，不破坏 CJK 字节边界）"""
        if isinstance(content, str):
            content = self._clean_input(content)
        msg = LivingMessage(
            content=content,
            user_id=user_id or self.user_id,
            session_id=session_id or self.session_id,
            source=source,
        )
        self._queue.put_nowait(msg)

    @staticmethod
    def _clean_input(text: str) -> str:
        from xiaomei_brain.agent.message_utils import clean_input
        return clean_input(text)

    def run(self) -> None:
        """主循环，阻塞运行"""
        print("[ConsciousLiving] 启动生命循环（当前状态: %s）" % self.state.value, flush=True)
        self._running = True

        # DORMANT → WAKING
        self._transition(LivingState.WAKING)
        self._on_wake()
        self._transition(LivingState.AWAKE)

        # 主循环
        while self._running:
            if self.state == LivingState.AWAKE:
                logger.debug("[Living] 进入 AWAKE 循环")
                self._loop_awake()
            elif self.state == LivingState.IDLE:
                logger.debug("[Living] 进入 IDLE 循环")
                self._loop_idle()
            elif self.state == LivingState.SLEEPING:
                logger.debug("[Living] 进入 SLEEPING 循环")
                self._loop_sleeping()
            elif self.state == LivingState.DREAMING:
                logger.debug("[Living] 进入 DREAMING 循环")
                self._loop_dreaming()
            else:
                logger.warning("[ConsciousLiving] Unexpected state: %s", self.state)
                time.sleep(1)

    def stop(self) -> None:
        """停止主循环"""
        self._running = False
        self._queue.put_nowait(None)
        # 保存 Drive 状态
        if self.drive:
            self.drive.save()
        # 保存 Purpose 状态
        if self.purpose:
            self.purpose.save()

    def cancel(self) -> None:
        """请求取消当前动作（Ctrl+C 触发）"""
        self._cancel_requested = True

    def reset_cancel(self) -> None:
        """重置取消标志（新消息到达时）"""
        self._cancel_requested = False

    def _print_prompt(self) -> None:
        """print 输入提示符（可被 TUI/CLI 关闭）。"""
        if self._show_prompt:
            import shutil
            width = shutil.get_terminal_size().columns
            print("\n" + "─" * width)
            print("> ", end="", flush=True)

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
        """状态转换。

        如果意识系统已加载，同步更新意识中的 agent_state。
        否则只更新 LivingState（生命存在但无意识）。
        """
        old = self.state
        self.state = new_state
        if old != new_state:
            logger.info("[Living] 状态转换: %s → %s", old.value, new_state.value)
        # 更新意识系统中的 agent_state（如果意识系统已加载）
        if self._load_consciousness:
            si = self.consciousness.get_self_image()
            si.agent_state = new_state.value

    # ── Loop: AWAKE ──────────────────────────────────────────────

    def _loop_awake(self) -> None:
        """AWAKE 状态：统一 tick + 消息处理"""
        logger.debug("[Living/AWAKE] tick 间隔=%.1f秒, idle阈值=%.1f秒", self.tick_interval, self.idle_threshold)

        # 统一心跳入口（如果意识系统已加载）
        result = TickResult.NORMAL
        if self._load_consciousness:
            result = self.consciousness.tick(agent_state=self.state.value)
            if result != TickResult.NORMAL:
                logger.info("[Living/AWAKE] tick 结果: %s", result.name)
            else:
                logger.debug("[Living/AWAKE] tick 结果: NORMAL")

        # L2 触发后检查 Intent 和欲望行为（需要意识系统）
        if self._load_consciousness and result == TickResult.L2_TRIGGERED:
            self._check_intent()
            # 消费 Intent 防止下一秒又触发
            self.consciousness.consume_intent()
            if self.consciousness.self_image.user_idle_duration > 300:
                self._check_desire_actions()

        # 等待消息
        msg = self._wait_message(timeout=self.tick_interval)

        if msg is not None:
            logger.info("[Living/AWAKE] 收到消息")
            self._handle_message(msg)
            self._last_active = time.time()
            return

        # 空闲检测
        idle_time = time.time() - self._last_active
        if idle_time >= self.idle_threshold:
            logger.info("[Living/AWAKE] 空闲 %.1f秒 ≥ %.1f，进入 SLEEPING", idle_time, self.idle_threshold)
            self._transition(LivingState.SLEEPING)
        elif idle_time >= self.idle_short:
            logger.info("[Living/AWAKE] 空闲 %.1f秒 ≥ %.1f，进入 IDLE", idle_time, self.idle_short)
            self._transition(LivingState.IDLE)
        else:
            logger.debug("[Living/AWAKE] 空闲 %.1f秒", idle_time)

    # ── Loop: IDLE ───────────────────────────────────────────────

    def _loop_idle(self) -> None:
        """IDLE 状态：发呆/间歇，发呆时间超过阈值才进入 SLEEPING

        特点：
        - L0/L1/L2 心跳全开，idle 时也能触发深度意识（如果意识系统已加载）
        - 收到消息立即唤醒回 AWAKE
        - 长时间发呆（idle_threshold）才进入 SLEEPING
        """
        while True:
            # 统一心跳入口（L0/L1/L2 各自按条件触发）
            result = TickResult.NORMAL
            if self._load_consciousness:
                result = self.consciousness.tick(agent_state=self.state.value)
                if result == TickResult.L2_TRIGGERED:
                    logger.info("[Living/IDLE] L2 触发")
                    self._check_intent()
                    self.consciousness.consume_intent()
                elif result != TickResult.NORMAL:
                    logger.info("[Living/IDLE] tick 结果: %s", result.name)

            # 收到消息 → 立即唤醒
            msg = self._wait_message(timeout=self.tick_interval)
            if msg is not None:
                logger.info("[Living/IDLE] 收到消息，唤醒回 AWAKE")
                self._on_wake_up()
                self._transition(LivingState.AWAKE)
                self._handle_message(msg)
                self._last_active = time.time()
                return

            # 继续累积空闲时间，达到阈值才进入 SLEEPING
            idle_time = time.time() - self._last_active
            if idle_time >= self.idle_threshold:
                logger.info("[Living/IDLE] 空闲 %.1f秒 ≥ %.1f，进入 SLEEPING", idle_time, self.idle_threshold)
                self._transition(LivingState.SLEEPING)
                return
            else:
                logger.debug("[Living/IDLE] 空闲 %.1f秒 / %.1f秒", idle_time, self.idle_threshold)

    # ── Loop: SLEEPING ───────────────────────────────────────────

    def _loop_sleeping(self) -> None:
        """SLEEPING 状态：统一 tick + 消息等待 + L3 触发 DREAMING"""
        dream_start = time.time()

        while True:
            # 统一心跳入口（L0/L1/L2 各自按条件触发）
            result = TickResult.NORMAL
            if self._load_consciousness:
                result = self.consciousness.tick(
                    agent_state=self.state.value,
                    in_dream=False,
                    dream_start=dream_start,
                )

                # L2 触发时检查 Intent 和欲望行为（冷却机制防止频繁触发）
                if result == TickResult.L2_TRIGGERED:
                    logger.info("[Living/SLEEPING] L2 触发")
                    self._check_intent()
                    self._check_desire_actions()

                # L3 触发：切换到 DREAMING 状态
                if result == TickResult.L3_TRIGGERED:
                    logger.info("[Living/SLEEPING] L3 触发，进入 DREAMING")
                    self._transition(LivingState.DREAMING)
                    return  # 回到 run() 主循环，进入 _loop_dreaming()

            # 等待消息
            msg = self._wait_message(timeout=self.tick_interval)

            if msg is not None:
                logger.info("[Living/SLEEPING] 收到消息，唤醒回 AWAKE")
                self._on_wake_up()
                self._transition(LivingState.AWAKE)
                self._handle_message(msg)
                self._last_active = time.time()
                return

            logger.debug("[Living/SLEEPING] 等待中...")

    # ── Loop: DREAMING ───────────────────────────────────────────

    def _loop_dreaming(self) -> None:
        """DREAMING 状态：等待 L3 深度燃烧完成，再切回 SLEEPING

        进入时记录 dream_start，作为 L3 触发的节拍器。
        在 DREAMING 状态中循环 tick，直到 L3 触发（或超时强制退出）。

        注意：如果意识系统未加载，直接跳过 DREAMING 状态。
        """
        logger.info("[Living/DREAMING] 开始梦境循环")

        # 无意识系统：直接切回 SLEEPING
        if not self._load_consciousness:
            logger.debug("[ConsciousLiving] 无意识系统，跳过 DREAMING 状态")
            self._transition(LivingState.SLEEPING)
            return

        dream_start = time.time()
        l3_fired = False

        while True:
            result = self.consciousness.tick(
                agent_state=self.state.value,
                in_dream=True,
                dream_start=dream_start,   # 不重置，跨多轮累加时间
            )
            if result != TickResult.NORMAL:
                logger.info("[Living/DREAMING] tick 结果: %s", result.name)
            else:
                logger.debug("[Living/DREAMING] tick 结果: NORMAL")

            if result == TickResult.L3_TRIGGERED and not l3_fired:
                l3_fired = True
                report = self.consciousness.get_last_report()
                if report:
                    logger.info("[ConsciousLiving] L3深度燃烧: %s", report.summary[:50])
                # L3 触发一次后继续循环，最多再等一轮，避免无限循环
                continue

            # L3 已触发过，或者 SLEEPING 收到消息唤醒了，直接回去
            if l3_fired:
                logger.info("[Living/DREAMING] L3已完成，切回 SLEEPING")
                self._transition(LivingState.SLEEPING)
                return

            # 没触发 L3 也可能是消息到达（in_dream 时仍能收到消息唤醒）
            msg = self._wait_message(timeout=self.dream_interval)
            if msg is not None:
                logger.info("[Living/DREAMING] 收到消息，唤醒回 AWAKE")
                self._on_wake_up()
                self._transition(LivingState.AWAKE)
                self._handle_message(msg)
                self._last_active = time.time()
                return

            # 超时强制回 SLEEPING（防止 DREAMING 卡住）
            elapsed = time.time() - dream_start
            if elapsed >= self.dream_interval * 2:
                logger.warning("[Living/DREAMING] 超时(%.1f秒)，强制切回 SLEEPING", elapsed)
                self._transition(LivingState.SLEEPING)
                return

            logger.debug("[Living/DREAMING] 等待 L3 触发... (%.1f秒)", elapsed)

    # ── Flame heartbeat ──────────────────────────────────────────

    def _check_desire_actions(self) -> None:
        """检查欲望驱动行为

        触发时机：
        - 事件提取周期（10分钟）后
        - 用户空闲超过5分钟时

        执行规则：
        - 检查冷却时间
        - 执行最高优先级行为
        """
        actions = self.drive.check_desire_actions()

        if not actions:
            return

        # 执行最佳行为
        self.action_executor.execute_best_action(actions)

    def _check_desire_actions_periodic(self) -> None:
        """周期性检查欲望行为（sleeping 状态，每 60 秒）

        处理非学习行为：
        - greet_user: 用户在场时问候
        - progress_goal: 推进目标
        - express_idea: 分享想法

        注意：learn_topic 已在 waking 时后台执行，这里跳过

        如果意识系统未加载，使用自己的计数器。
        """
        # 检查间隔（用 consciousness._l0_count，每 60 次 = 60 秒）
        # 如果无意识系统，使用自己的计数器
        if self._load_consciousness:
            l0 = self.consciousness.l0_count
            logger.debug("[欲望周期] l0_count=%d", l0)
            if l0 != 0:
                return  # 只在 l0_count == 0 时执行（L1 刚触发后）
        else:
            # 无意识系统：使用 _periodic_count（需要新增）
            if not hasattr(self, "_periodic_count"):
                self._periodic_count = 0
            self._periodic_count = (self._periodic_count + 1) % 60
            if self._periodic_count != 0:
                return

        # 执行周期检查
        logger.info("[ConsciousLiving/Sleeping] 欲望周期检查触发！")

        # 调用欲望行为检查
        actions = self.drive.check_desire_actions()

        if not actions:
            logger.debug("[欲望周期] 无候选行为")
            return

        # 过滤掉 learn_topic（已在 waking 时执行）
        filtered_actions = [a for a in actions if a["type"] != "learn_topic"]

        if not filtered_actions:
            logger.debug("[欲望周期] 只有 learn_topic，跳过（已在后台执行）")
            return

        # 记录候选行为
        logger.info(
            "[ConsciousLiving/Sleeping] 欲望周期检查: %d 个候选行为",
            len(filtered_actions)
        )

        # 执行最佳行为（冷却时间在 action_executor 中控制）
        self.action_executor.execute_best_action(filtered_actions)

    # ── Intent 消费 ──────────────────────────────────────────────

    def _check_intent(self) -> None:
        """检查并消费 Intent

        如果意识系统未加载，跳过 Intent 检查（无意识 = 无 Intent）。
        """
        if not self._load_consciousness:
            return

        intent = self.consciousness.get_pending_intent()
        if not intent or not getattr(intent, "type", None):
            return

        # 根据 Intent 类型执行不同动作
        if intent.type == ConsciousIntentType.GREET:
            self._execute_greet_intent(intent)
        elif intent.type == ConsciousIntentType.CARE:
            self._execute_care_intent(intent)
        elif intent.type == ConsciousIntentType.REFLECT:
            self._execute_reflect_intent(intent)
        elif intent.type == ConsciousIntentType.ACT:
            self._execute_act_intent(intent)
        else:
            logger.debug("[ConsciousLiving] Intent暂不执行: %s", intent.type.value)

    def _execute_greet_intent(self, intent: Intent) -> None:
        """执行问候意图"""
        logger.info("[ConsciousLiving/Intent] 执行问候: %s", intent.content)

        # 消费意图
        self.consciousness.consume_intent()

        # 构建问候消息
        si = self.consciousness.get_self_image()
        time_greeting = ""
        if hasattr(si, 'last_dream_summary') and si.last_dream_summary:
            time_greeting = f"我刚做了一个梦，{si.last_dream_summary[:30]}..."
        else:
            hour = datetime.now().hour
            if 6 <= hour < 12:
                time_greeting = "早上好！"
            elif 12 <= hour < 18:
                time_greeting = "下午好！"
            elif 18 <= hour < 22:
                time_greeting = "晚上好！"
            else:
                time_greeting = "夜深了，还在呢？"

        greet_content = f"{time_greeting} {intent.content}"

        # 发送主动消息
        self._send_proactive(greet_content)

        # Intent → Action 闭环：问候执行后，满足归属欲
        if self.drive:
            self.drive.on_desire_satisfied("belonging", 0.15)
            logger.info("[ConsciousLiving/Intent] 问候已发送，归属欲 +0.15")

    def _execute_care_intent(self, intent: Intent) -> None:
        """执行关心意图"""
        logger.info("[ConsciousLiving/Intent] 关心用户: %s", intent.content)
        self.consciousness.consume_intent()

        # 构建关心消息
        care_content = f"我有点担心你... {intent.content}"
        self._send_proactive(care_content)

        # Intent → Action 闭环：关心执行后，满足关联感
        if self.drive:
            self.drive.on_desire_satisfied("belonging", 0.1)
            logger.info("[ConsciousLiving/Intent] 关心已发送，归属欲 +0.1")

    def _execute_reflect_intent(self, intent: Intent) -> None:
        """执行反省意图：触发 L3

        注意：L3 深度燃烧只在 SLEEPING/DREAMING 状态执行，
        因为 LLM 调用耗时较长，AWAKE 状态应该快速响应用户。
        """
        logger.info("[ConsciousLiving/Intent] 触发深度反省: %s", intent.content)
        self.consciousness.consume_intent()

        # L3 只在 SLEEPING/DREAMING 状态执行
        if self.state not in (LivingState.SLEEPING, LivingState.DREAMING):
            logger.info("[ConsciousLiving/Intent] 反省延迟：当前状态 %s 不是 SLEEPING/DREAMING", self.state.value)
            return

        # 反省 → L3 深度燃烧
        report = self.consciousness.tick_L3()
        logger.info("[ConsciousLiving/Intent] 反省报告: %s", report.summary[:50])

    def _execute_act_intent(self, intent: Intent) -> None:
        """执行行动意图"""
        logger.info("[ConsciousLiving/Intent] 执行行动: %s", intent.content)
        self.consciousness.consume_intent()

        # 发送主动消息
        self._send_proactive(f"[行动] {intent.content}")

    # ── Message handling ─────────────────────────────────────────

    def _handle_message(self, msg: LivingMessage) -> None:
        """处理消息"""
        # 忽略空消息（如用户按回车找回输入行）
        if not msg.content or not msg.content.strip():
            logger.debug("[ConsciousLiving] 忽略空消息")
            return

        # 防止重复调用（_run_chat 进行中）
        if self._chatting:
            logger.info("[ConsciousLiving] 聊天进行中，忽略新消息: %s", msg.content[:30])
            return

        logger.info("[ConsciousLiving] 收到消息: %s", msg.content[:50])

        # 重置取消标志（新消息来了，之前的取消失效）
        self._cancel_requested = False

        # 命令检测（支持 `/cmd` 和裸 `cmd` 两种写法）
        raw = msg.content.strip()
        if raw.startswith("/"):
            raw = raw[1:].strip()
        parts = raw.split(None, 1)
        cmd = parts[0].lower() if parts else ""
        cmd_args = parts[1] if len(parts) > 1 else ""

        # /intask 进入任务模式（保持直到 /inchat）
        if cmd == "intask":
            self._intent_mode = True
            print("\n[任务模式] 已进入，/inchat 退出", flush=True)
            self._print_prompt()
            self._command_done.set()
            return

        # /inchat 退出任务模式，回到聊天模式
        if cmd == "inchat":
            self._intent_mode = False
            print("\n[聊天模式] 已退出", flush=True)
            self._print_prompt()
            self._command_done.set()
            return

        # 输入 `/` 列出所有命令
        if not cmd:
            self._list_commands()
            self._command_done.set()
            return
        if cmd in self._intent_commands:
            logger.info("[ConsciousLiving] 执行测试命令: %s %s", cmd, cmd_args)
            handler = self._intent_commands[cmd]
            handler(cmd_args)
            self._command_done.set()
            return

        # Agent 命令（如 db/memory/dag）
        if self.agent.commands:
            result = self.agent.commands.execute(
                raw,
                user_id=msg.user_id,
                session_id=msg.session_id,
            )
            if result:
                logger.info("[ConsciousLiving] Agent 命令: %s", raw)
                print(f"\n{result.output}", flush=True)
                self._print_prompt()
                self._command_done.set()
                return

        # "继续"检测：列出活跃任务让用户选
        if self.purpose and self._is_continue_statement(msg.content):
            goals = self.purpose.get_top_level_goals()
            if len(goals) == 1:
                # 只有一个目标，找到关联的 Task
                goal_id = goals[0].id
                task = self.task_manager.find_by_goal_id(goal_id)
                # 如果是暂停状态，先恢复 Task
                resume_context = ""
                if goals[0].is_paused() and task:
                    resumed = self.task_manager.resume_task(task.task_id)
                    if resumed:
                        resume_context = resumed.get_cognitive_context()
                    print(f"[任务] 恢复: {goals[0].description[:40]}", flush=True)
                else:
                    self.purpose.set_current(goal_id)
                    print(f"[目标] 延续任务: {goals[0].description[:40]}", flush=True)
                from xiaomei_brain.purpose.intent import IntentType, GoalRelation
                fake_intent = IntentResult(
                    intent_type=PurposeIntentType.TASK,
                    goals=[goals[0]],
                    relation=GoalRelation.MODIFIES,
                    target_goal_id=goal_id,
                    confidence=1.0,
                    reasoning="延续现有任务",
                )
                self._run_chat(msg, self._build_intent_context(fake_intent, chosen_by_user=True, resume_snapshot=resume_context))
                return
            elif len(goals) > 1:
                # 精确匹配：从"继续XXX"中提取关键词，找匹配的目标
                task_keywords = msg.content
                for kw in ("继续", "接着做", "还做", "再做", "延续", "持续"):
                    if task_keywords.startswith(kw):
                        task_keywords = task_keywords[len(kw):].strip("，。")
                        break

                # 找描述中包含关键词的目标（关键词匹配）
                matched_goal = None
                import re
                # 先按空格/标点拆分，不够细时再按字符拆分
                words = [k for k in re.split(r"[\s，、。]+", task_keywords) if k]
                # 如果拆分后只有一个长词（中文），按字符拆分
                if len(words) == 1 and len(words[0]) > 2 and re.match(r"^[\u4e00-\u9fff]+$", words[0]):
                    keywords = list(words[0])
                else:
                    keywords = words
                if keywords:
                    for g in goals:
                        desc = g.description or ""
                        # 所有关键词都在描述中
                        if all(kw in desc for kw in keywords):
                            matched_goal = g
                            break
                    # 未找到：尝试宽松匹配（至少一个>=2字的关键词匹配）
                    if not matched_goal:
                        long_keywords = [kw for kw in keywords if len(kw) >= 2]
                        for g in goals:
                            desc = g.description or ""
                            if any(kw in desc for kw in long_keywords):
                                matched_goal = g
                                break

                if matched_goal:
                    # 精确匹配到，直接使用
                    goal_id = matched_goal.id
                    task = self.task_manager.find_by_goal_id(goal_id)
                    resume_context = ""
                    if matched_goal.is_paused() and task:
                        resumed = self.task_manager.resume_task(task.task_id)
                        if resumed:
                            resume_context = resumed.get_cognitive_context()
                        print(f"[任务] 恢复: {matched_goal.description[:40]}", flush=True)
                    else:
                        self.purpose.set_current(goal_id)
                        print(f"[目标] 延续任务: {matched_goal.description[:40]}", flush=True)
                    from xiaomei_brain.purpose.intent import IntentType, GoalRelation
                    fake_intent = IntentResult(
                        intent_type=PurposeIntentType.TASK,
                        goals=[matched_goal],
                        relation=GoalRelation.MODIFIES,
                        target_goal_id=goal_id,
                        confidence=1.0,
                        reasoning="延续现有任务",
                    )
                    self._run_chat(msg, self._build_intent_context(fake_intent, chosen_by_user=True, resume_snapshot=resume_context))
                    return

                # 未匹配到，让用户选（按描述去重）
                seen = set()
                options = []
                goal_ids = []
                for g in goals:
                    if g.description not in seen:
                        seen.add(g.description)
                        label = g.description
                        if g.is_paused():
                            label = f"{g.description}（暂停中）"
                        options.append(label)
                        goal_ids.append(g.id)
                confirm_info = {
                    "type": "continue_goal",
                    "question": f"要继续哪个任务？（未找到匹配「{task_keywords}」）",
                    "options": options,
                    "goal_ids": goal_ids,
                }
                self._pending_confirm = confirm_info
                self._waiting_confirm = True
                self._pending_confirm_msg = msg
                if self.on_confirm_required:
                    self.on_confirm_required(confirm_info)
                else:
                    print(f"\n[确认] {confirm_info['question']}", flush=True)
                    for i, opt in enumerate(confirm_info['options']):
                        print(f"  {i+1}. {opt}", flush=True)
                    print(f"  0. 都不选", flush=True)
                    self._print_prompt()
                return
            # 无活跃目标，走正常意图分析

        # 等待确认状态：处理用户的选择
        if self._waiting_confirm and self._pending_confirm:
            self._handle_confirmation(msg.content)
            return

        # 意图模式：所有消息都经过 LLM 意图分析
        if self._intent_mode:
            logger.info("[ConsciousLiving] 任务模式: %s", msg.content[:50])
            intent_result = self._analyze_intent(msg.content)
            logger.info(
                "[ConsciousLiving] 意图分析: type=%s, goals=%d, confidence=%.2f",
                intent_result.intent_type.value,
                len(intent_result.goals),
                intent_result.confidence,
            )

            if intent_result.is_task() and intent_result.has_goal() and intent_result.confidence >= 0.5:
                self._handle_task_intent(intent_result, msg)
                if self._waiting_confirm:
                    self._pending_confirm_msg = msg
                    self._pending_confirm_intent = intent_result
                    return
                return

            intent_context = self._build_intent_context(intent_result)
            self._log_intent_context(intent_result, intent_context, msg.content)
            self._run_chat(msg, intent_context)
            return

        # 聊天模式：跳过意图分析，直接对话
        logger.info("[ConsciousLiving] 聊天模式: %s", msg.content[:50])

        intent_result = IntentResult(
            intent_type=PurposeIntentType.CHAT,
            confidence=1.0,
            reasoning="聊天模式，跳过意图分析",
        )
        intent_context = self._build_intent_context(intent_result)
        self._log_intent_context(intent_result, intent_context, msg.content)
        self._run_chat(msg, intent_context)

    def _wait_message(self, timeout: float) -> LivingMessage | None:
        """等待消息"""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    # ── Intent Understanding ─────────────────────────────────────────

    @staticmethod
    def _is_continue_statement(text: str) -> bool:
        """检测是否是以"继续"开头的延续语句"""
        patterns = ("继续", "接着做", "还做", "再做", "延续", "持续")
        for p in patterns:
            if text.startswith(p) or text.startswith(f"{p}，") or text.startswith(f"{p}。"):
                return True
        return False

    def _analyze_intent(self, user_input: str) -> Any:
        """分析用户意图（每条消息都分析）

        Returns:
            IntentResult: 意图分析结果
        """
        # `!` 前缀 = 明确的任务指令，跳过意图分类，直接做目标分解
        if user_input.startswith("!"):
            from xiaomei_brain.purpose.intent import IntentType, GoalRelation
            task_text = user_input[1:].strip()

            # 规则检测 task_type（! 前缀跳过意图分类 LLM）
            task_type = "execution"  # 默认
            task_lower = task_text
            learn_kw = ["学习", "学", "了解原理", "入门", "掌握", "理解", "研究原理"]
            explore_kw = ["调研", "对比", "选型", "有哪些", "哪个好", "评测", "探索"]
            reflect_kw = ["反省", "反思", "复盘", "回顾"]
            relation_kw = ["关注", "关心", "维护关系", "保持联系"]
            if any(task_lower.startswith(k) for k in learn_kw):
                task_type = "learning"
            elif any(task_lower.startswith(k) for k in explore_kw):
                task_type = "exploration"
            elif any(k in task_lower for k in reflect_kw):
                task_type = "reflection"
            elif any(k in task_lower for k in relation_kw):
                task_type = "relationship"

            goal = Goal(
                description=task_text,
                goal_type=GoalType.EXECUTABLE,
                status=GoalStatus.PENDING,
            )
            # 直接调用第二阶段 LLM：分解目标（跳过第一阶段意图分类）
            sub_descriptions = self.intent_understanding.decompose_goal(task_text)
            return IntentResult(
                intent_type=PurposeIntentType.TASK,
                goals=[goal],
                sub_goals=sub_descriptions,
                relation=GoalRelation.NEW,
                target_goal_id=None,
                confidence=1.0,
                task_type=task_type,
                reasoning=f"指令以 ! 开头，明确的任务请求，跳过意图分类直接分解目标：{task_text[:50]}",
            )

        # 获取 Purpose 状态（作为上下文）
        meaning_summary = ""
        current_goal_desc = ""
        current_goal_depth = 0
        pending_summary = ""

        if self.purpose:
            if self.purpose.meaning:
                meaning_summary = self.purpose.meaning.get_summary()
            current = self.purpose.get_current()
            if current:
                current_goal_desc = current.description
                current_goal_depth = current.depth
            pending_goals = self.purpose.get_pending_goals()
            if pending_goals:
                pending_summary = "; ".join(g.description[:30] for g in pending_goals[:3])

        # 调用 IntentUnderstanding
        result = self.intent_understanding.understand(
            user_input=user_input,
            meaning=meaning_summary,
            current_goal=current_goal_desc,
            current_goal_depth=current_goal_depth,
            pending_goals=pending_summary,
        )

        return result

    def _handle_task_intent(self, intent_result: Any, msg: Any = None) -> None:
        """处理任务意图：通过 TaskManager 创建 Task（v2 独立认知实体）

        Args:
            intent_result: IntentResult，包含 goals 和 sub_goals
            msg: 原始消息，用于单步任务直接执行

        注意：子目标分解已合并到 IntentUnderstanding，不再单独调用 auto_decompose
        """
        # 过滤：排除元目标（描述意图识别/目标提取本身的描述）
        META_GOAL_KEYWORDS = ("意图识别", "目标提取", "子目标分解", "自动分解")
        filtered_goals = []
        for g in intent_result.goals:
            is_meta = any(kw in g.description for kw in META_GOAL_KEYWORDS)
            if is_meta:
                logger.info("[Intent] 跳过元目标: %s", g.description[:50])
                continue
            filtered_goals.append(g)
        if not filtered_goals:
            logger.info("[Intent] 无有效目标，跳过")
            return
        for goal in filtered_goals:
            # 如果是 MODIFIES 关系，复用现有目标，不创建新目标
            target_id = intent_result.target_goal_id
            # 如果 LLM 没指定 target_goal_id 但有当前活跃目标，默认修改当前目标
            if intent_result.relation.value == "modifies":
                if not target_id and self.purpose.current_goal:
                    target_id = self.purpose.current_goal.id
                    logger.info("[Intent] MODIFIES 无 target_goal_id，默认修改当前目标: %s",
                                self.purpose.current_goal.description[:40])
                if target_id:
                    existing = self.purpose.goals.get(target_id)
                    if existing:
                        self.purpose.set_current(existing.id)
                        # 检查是继续执行还是停止/放弃
                        stop_keywords = ["停止", "取消", "别", "算了", "不做", "中止"]
                        is_stop = any(kw in goal.description for kw in stop_keywords)
                        if is_stop:
                            existing.abandon()
                            # 同步 Task
                            task = self.task_manager.find_by_goal_id(target_id)
                            if task:
                                self.task_manager.abandon_task(task.task_id)
                            print(f"[目标] 已放弃: {existing.description[:40]}", flush=True)
                        else:
                            print(f"[目标] 延续任务: {existing.description[:40]}", flush=True)
                        return

            # 确定父目标（如果 relation 是 sub_goal_of）
            parent_id = None
            if intent_result.relation.value == "sub_goal_of" and intent_result.target_goal_id:
                parent_id = intent_result.target_goal_id

            # 解析 task_type
            task_type_str = getattr(intent_result, "task_type", "") or "execution"
            try:
                task_type = TaskType(task_type_str)
            except ValueError:
                task_type = TaskType.EXECUTION

            # 新任务到达：先暂停当前 Task（TaskManager 自动处理）
            current_task = self.task_manager.get_current_task()
            if current_task and current_task.task_id:
                # 检查是否是同一个 Goal 的 Task
                if not (current_task.goal_id and current_task.goal_id == intent_result.target_goal_id):
                    self.task_manager.pause_task(current_task.task_id)
                    print(f"[任务] 暂停「{current_task.description[:40]}」", flush=True)

            # 创建 Task（v2：独立认知实体）
            task = self.task_manager.create_task(
                description=goal.description,
                task_type=task_type,
            )
            logger.info(
                "[Intent] 新 Task 创建: task_id=%s type=%s desc=%s goal_id=%s",
                task.task_id, task_type.value, task.description[:50], task.goal_id,
            )

            # 根据 task_type 决定是否拆解子目标
            if task_type == TaskType.EXECUTION and intent_result.has_sub_goals() and task.goal_id:
                sub_goals = self.purpose.decompose_goal(
                    goal_id=task.goal_id,
                    sub_descriptions=intent_result.sub_goals,
                )
                logger.info(
                    "[Intent] 子目标分解完成: %d 个子目标",
                    len(sub_goals),
                )
                print(f"\n[目标] 已分解为 {len(sub_goals)} 个子目标:", flush=True)
                for i, sg in enumerate(sub_goals):
                    print(f"  {i+1}. {sg.description[:40]}", flush=True)

                # 激活第一个子目标
                if sub_goals:
                    self.purpose.set_current(sub_goals[0].id)
                    self._print_sub_goal_progress(sub_goals[0], sub_goals)
                    new_intent = self._build_intent_context_for_goal(sub_goals[0])
                    self._run_chat(msg, new_intent)
                    return
            elif task.goal_id:
                # 非 EXECUTION 或 无子目标 → 直接执行 Goal
                goal_obj = self.purpose.goals.get(task.goal_id)
                if goal_obj:
                    self.purpose.set_current(goal_obj.id)
                    type_label = {
                        TaskType.EXECUTION: "EXECUTION",
                        TaskType.LEARNING: "LEARNING",
                        TaskType.REFLECTION: "REFLECTION",
                        TaskType.RELATIONSHIP: "RELATIONSHIP",
                        TaskType.EXPLORATION: "EXPLORATION",
                    }.get(task_type, task_type.value)
                    print(f"[{type_label}] 当前: {goal_obj.description[:40]}", flush=True)
                    new_intent = self._build_intent_context_for_goal(goal_obj)
                    self._run_chat(msg, new_intent)
                    return
            else:
                # 无 Goal 关联（非 EXECUTION 且不需要子目标管理）
                type_label = {
                    TaskType.LEARNING: "LEARNING",
                    TaskType.REFLECTION: "REFLECTION",
                    TaskType.RELATIONSHIP: "RELATIONSHIP",
                    TaskType.EXPLORATION: "EXPLORATION",
                }.get(task_type, task_type.value)
                print(f"[{type_label}] 当前: {task.description[:40]}", flush=True)
                # 为非 Goal 类型构建临时上下文
                from ..purpose.intent import IntentResult, IntentType, GoalRelation
                fake_intent = IntentResult(
                    intent_type=PurposeIntentType.TASK,
                    goals=[],
                    relation=GoalRelation.NEW,
                    confidence=1.0,
                    reasoning=f"{type_label} 类型任务: {task.description[:50]}",
                )
                new_intent = self._build_intent_context(fake_intent)
                self._run_chat(msg, new_intent)
                return

        # 刷新命令（让用户知道有新目标）
        if filtered_goals:
            print(f"\n[目标] 已添加: {filtered_goals[0].description[:40]}", flush=True)

    def _build_confirm_info(self, sub_goal, intent_result) -> dict | None:
        return task_executor.build_confirm_info(sub_goal, intent_result)

    def _handle_confirmation(self, user_input: str) -> None:
        """处理用户在选择框中的输入"""
        confirm = self._pending_confirm
        if not confirm:
            return

        # ── "继续" 选择：从活跃任务列表里选一个 ──────────────
        if confirm.get("type") == "continue_goal":
            inp = user_input.strip()
            if inp.isdigit():
                idx = int(inp)
                if idx == 0:
                    # 都不选，清空确认状态，等用户输入新内容
                    self._pending_confirm = None
                    self._waiting_confirm = False
                    self._pending_confirm_msg = None
                    self._print_prompt()
                    return
                if 1 <= idx <= len(confirm["goal_ids"]):
                    goal_id = confirm["goal_ids"][idx - 1]
                    goal = self.purpose.goals.get(goal_id)
                    task = self.task_manager.find_by_goal_id(goal_id)

                    # 如果是暂停状态，先恢复 Task（产生 resume_snapshot）
                    resume_context = ""
                    if goal and goal.is_paused() and task:
                        resumed = self.task_manager.resume_task(task.task_id)
                        if resumed:
                            resume_context = resumed.get_cognitive_context()
                        print(f"[任务] 恢复: {goal.description[:40]}", flush=True)
                    else:
                        self.purpose.set_current(goal_id)
                        if goal:
                            print(f"[目标] 延续任务: {goal.description[:40]}", flush=True)

                    # 清理确认状态
                    original_msg = self._pending_confirm_msg
                    self._pending_confirm = None
                    self._waiting_confirm = False
                    self._pending_confirm_msg = None

                    if original_msg and goal:
                        from xiaomei_brain.purpose.intent import IntentType, GoalRelation
                        fake_intent = IntentResult(
                            intent_type=PurposeIntentType.TASK,
                            goals=[goal],
                            relation=GoalRelation.MODIFIES,
                            target_goal_id=goal_id,
                            confidence=1.0,
                            reasoning="用户选择延续任务",
                        )
                        self._run_chat(original_msg, self._build_intent_context(fake_intent, chosen_by_user=True, resume_snapshot=resume_context))
                    return

            print("[确认] 无效选项，请重新选择：", flush=True)
            return

        # 解析输入（委托 task_executor）
        parsed = task_executor.parse_confirmation_input(confirm, user_input)
        action = parsed["action"]

        if action == "retry":
            if user_input.strip() == "0":
                print("[确认] 请直接输入你的选择：", flush=True)
            else:
                print("[确认] 无效选项，请重新选择：", flush=True)
            return  # 等待下一次输入

        if action == "cancel":
            # 用户想放弃当前任务，切换到别的
            current = self.purpose.get_current()
            if current:
                current.abandon()
                print(f"[目标] 已放弃: {current.description[:40]}", flush=True)
            # 清理确认状态
            self._pending_confirm = None
            self._waiting_confirm = False
            self._pending_confirm_msg = None
            self._pending_confirm_intent = None
            # 把用户输入当新消息重新处理（意图分析会找到/创建ERP目标）
            print(f"\n> {user_input}", flush=True)
            fake_msg = LivingMessage(
                session_id="main",
                user_id="global",
                content=user_input,
            )
            self._handle_message(fake_msg)
            return

        goal_id = parsed["goal_id"]
        answer = parsed["answer"]

        # 执行业务逻辑（委托 task_executor）
        if action == "skip":
            result = task_executor.apply_skip(self.purpose, goal_id)
            if result["status_msg"]:
                print(result["status_msg"], flush=True)
            if result["new_goal_id"] is None:
                # 无更多子目标
                self._pending_confirm = None
                self._waiting_confirm = False
                self._pending_confirm_msg = None
                self._pending_confirm_intent = None
                return
            next_goal_id = result["new_goal_id"]
        else:
            result = task_executor.apply_proceed(self.purpose, goal_id, answer)
            if result["status_msg"]:
                print(result["status_msg"], flush=True)
            if result["new_goal_id"] is None:
                # 所有子目标已完成
                self._pending_confirm = None
                self._waiting_confirm = False
                self._pending_confirm_msg = None
                self._pending_confirm_intent = None
                return
            next_goal_id = result["new_goal_id"]

        # 推进到下一个子目标：构建新目标的 intent_context
        self._pending_confirm = None
        self._waiting_confirm = False
        original_msg = self._pending_confirm_msg
        self._pending_confirm_msg = None
        self._pending_confirm_intent = None

        next_goal = self.purpose.goals.get(next_goal_id)
        if next_goal:
            print(f"[目标] 继续执行: {next_goal.description[:40]}", flush=True)

            # 直接执行，由LLM处理需要的用户输入
            new_intent = self._build_intent_context_for_goal(next_goal)
            proceed_msg = LivingMessage(
                content="继续执行",
                user_id=original_msg.user_id if original_msg else "global",
                session_id=original_msg.session_id if original_msg else "main",
                source="system",
            )
            self._run_chat(proceed_msg, new_intent)

    def _build_intent_context_for_goal(self, goal) -> str:
        """为指定目标构建 intent_context（不依赖 original_intent）"""
        from ..purpose.intent import IntentResult, IntentType, GoalRelation

        fake_intent = IntentResult(
            intent_type=PurposeIntentType.TASK,
            goals=[goal],
            relation=GoalRelation.MODIFIES,
            target_goal_id=goal.id,
            confidence=1.0,
            reasoning=f"目标推进：{goal.description[:50]}",
        )
        return self._build_intent_context(fake_intent, chosen_by_user=True)

    def _log_intent_context(self, intent_result: Any, intent_context: str, user_input: str = "") -> None:
        """调试：输出 intent_context 到 JSON 文件"""
        import json, time, os
        log_dir = os.path.expanduser("~/.xiaomei-brain/logs")
        os.makedirs(log_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")

        # 提取活跃目标信息
        active_goal = None
        if self.purpose:
            active = self.purpose.get_active_goals()
            if active:
                active_goal = active[0].description

        data = {
            "timestamp": timestamp,
            "user_input": user_input,
            "intent_type": intent_result.intent_type.value if hasattr(intent_result, "intent_type") else str(intent_result.intent_type),
            "confidence": intent_result.confidence if hasattr(intent_result, "confidence") else 0,
            "active_goal": active_goal,
            "intent_context": intent_context,
            "response_guidance": getattr(intent_result, "response_guidance", ""),
        }
        log_path = os.path.join(log_dir, f"intent_context_{timestamp}.json")
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug("[ConsciousLiving] intent_context 已写入: %s", log_path)
        except Exception as e:
            logger.warning("[ConsciousLiving] 写入 intent_context 失败: %s", e)

    def _run_chat(self, msg: LivingMessage, intent_context: str = "") -> None:
        """执行对话（统一的 chat 入口）。

        PurposeEngine 驱动的子目标自动推进：
        - 每次 ReAct 只执行当前子目标（由 intent_context 约束）
        - 子目标完成后，PurposeEngine 自动推进到下一个子目标
        - 循环直到：无更多子目标 / 需要用户输入 / 用户中断
        """
        def run():
            self._chatting = True
            try:
                current_msg = msg
                current_context = intent_context

                while True:
                    print("\n小美: ", end="", flush=True)
                    cs = self._get_consciousness_state()
                    from xiaomei_brain.agent.core import tool_call_buffer
                    t0 = time.time()
                    tc_before = tool_call_buffer.last_index
                    content = self.agent.chat(
                        current_msg.content,
                        session_id=current_msg.session_id,
                        user_id=current_msg.user_id,
                        on_chunk=None,
                        intent_context=current_context,
                        consciousness_state=cs,
                    )
                    elapsed = time.time() - t0
                    tc_count = tool_call_buffer.last_index - tc_before

                    # 对话消耗能量
                    if self.drive and elapsed > 1.0:
                        self.drive.consume_energy(0.05)

                    # Ctrl+C 取消：丢弃 LLM 结果
                    if self._cancel_requested:
                        logger.info("[ConsciousLiving] LLM 结果已丢弃（取消请求）")
                        print("\n[取消] 已中断", flush=True)
                        self._print_prompt()
                        return

                    # 解析进度标签
                    progress_data = self._parse_progress_tag(content)
                    if progress_data and self.purpose:
                        logger.info(
                            "[Progress Tag] data=%s active_sub=%s",
                            progress_data,
                            self.purpose.get_active_goals()[0].description[:30] if self.purpose and self.purpose.get_active_goals() else "none",
                        )
                        # 先记下当前子目标 ID（update_goal_progress 会切换 current）
                        completing_goal_id = None
                        if progress_data.get("status") == "completed":
                            current = self.purpose.get_current()
                            if current:
                                completing_goal_id = current.id

                        self._update_goal_progress(progress_data["status"])

                        # 存储子目标产出摘要（用完成前的 goal_id）
                        if progress_data.get("status") == "completed":
                            summary = progress_data.get("summary", "")
                            if summary and completing_goal_id:
                                self.purpose.store_sub_goal_output(completing_goal_id, summary)
                                logger.info("[Progress] 存储子目标产出: %s", summary[:50])

                                # v2: 追加认知日志到 Task
                                task = self.task_manager.get_current_task()
                                if task:
                                    self.task_manager.append_cognitive_log(
                                        task.task_id,
                                        entry_type="output",
                                        content=summary,
                                        sub_goal_id=completing_goal_id,
                                    )

                                    # 检查是否所有子目标已完成 → 触发知识提取
                                    if completing_goal_id:
                                        completing_goal = self.purpose.goals.get(completing_goal_id)
                                        if completing_goal and completing_goal.parent_id:
                                            siblings = self.purpose.get_sub_goals(completing_goal.parent_id)
                                            all_done = all(sg.is_completed() for sg in siblings)
                                            if all_done:
                                                self._complete_task(task)

                        # 增量持久化：状态变更后立即保存，防止崩溃丢失
                        self.purpose.save()

                    # 移除进度标签
                    display_content = self._remove_progress_tag(content)

                    # 打印 LLM 输出分隔标记
                    _w = 138
                    _label = " LLM output "
                    _pad = (_w - len(_label)) // 2
                    print("\n" + "=" * _pad + _label + "=" * _pad, flush=True)
                    print(display_content, flush=True)
                    _label2 = " LLM output-end "
                    _pad2 = (_w - len(_label2)) // 2
                    print("=" * _pad2 + _label2 + "=" * _pad2, flush=True)

                    # 本轮耗时
                    tc_str = f"，{tc_count}次工具调用" if tc_count else ""
                    print(f"\033[90m[本轮耗时 {elapsed:.1f}s{tc_str}]\033[0m", flush=True)

                    # 更新意识系统（如果已加载）
                    if self._load_consciousness:
                        self.consciousness.on_user_interaction(current_msg.content, display_content)

                    # PurposeEngine 自动推进检查
                    if not self._should_auto_advance(progress_data):
                        logger.info("[ConsciousLiving] 对话完成")

                        # v2: 非子目标推进场景（LEARNING/EXPLORATION 等）也追加认知日志
                        had_sub_goal_completion = (
                            progress_data
                            and progress_data.get("status") == "completed"
                        )
                        if not had_sub_goal_completion and display_content:
                            task = self.task_manager.get_current_task()
                            if task:
                                self.task_manager.append_cognitive_log(
                                    task.task_id,
                                    entry_type="output",
                                    content=display_content[:500],
                                )

                        self._print_prompt()
                        return

                    # 构建下一个子目标的上下文
                    next_goal = self.purpose.get_current()
                    current_context = self._build_intent_context_for_goal(next_goal)
                    current_msg = LivingMessage(
                        content=f"[系统] 子目标：{next_goal.description}",
                        user_id=msg.user_id,
                        session_id=msg.session_id,
                        source="system",
                    )
                    siblings = self.purpose.get_sub_goals(next_goal.parent_id)
                    self._print_sub_goal_progress(next_goal, siblings)

            except Exception as e:
                logger.error("[ConsciousLiving] Chat failed: %s", e)
                print(f"\n\033[31m[错误] {e}\033[0m", flush=True)

                # 子目标错误处理
                if self.purpose:
                    goal = self.purpose.get_current()
                    if goal:
                        # v2: 错误也追加到认知日志
                        task = self.task_manager.get_current_task()
                        if task:
                            self.task_manager.append_cognitive_log(
                                task.task_id,
                                entry_type="pitfall",
                                content=f"子目标「{goal.description[:30]}」执行出错: {str(e)[:200]}",
                                sub_goal_id=goal.id,
                            )

                        result = task_executor.handle_sub_goal_error(
                            self.purpose, goal.id, str(e),
                        )
                        if result["status_msg"]:
                            print(f"\033[33m{result['status_msg']}\033[0m", flush=True)

                self._print_prompt()
            finally:
                self._chatting = False

        run()

    @staticmethod
    def _progress_bar(completed: int, total: int, width: int = 10) -> str:
        """生成进度条：████░░░░░░"""
        if total == 0:
            return ""
        filled = int(width * completed / total)
        return "█" * filled + "░" * (width - filled)

    def _print_sub_goal_progress(self, goal, siblings: list) -> None:
        """打印子目标进度条。"""
        completed = sum(1 for g in siblings if g.is_completed())
        total = len(siblings)
        bar = self._progress_bar(completed, total)
        print(f"[目标] {bar} {completed}/{total}  {goal.description[:40]}", flush=True)

    def _should_auto_advance(self, progress_data: dict | None) -> bool:
        """检查 PurposeEngine 是否已自动推进到新的子目标。

        条件：
        - 当前子目标标记为 completed（而非 in_progress）
        - PurposeEngine 的 get_current() 返回一个活跃的子目标
        - 该子目标尚未开始执行（progress == 0，即新激活的）
        """
        if not progress_data or progress_data.get("status") != "completed":
            return False

        if self._cancel_requested:
            return False

        if not self.purpose:
            return False

        current = self.purpose.get_current()
        if not current:
            return False

        # 必须是子目标（有 parent_id）
        if not current.parent_id:
            return False

        # 必须是活跃状态（刚被 update_goal_progress 激活）
        if not current.is_active():
            return False

        # progress > 0 表示已在执行中（in_progress），应该等待用户输入
        if current.progress > 0:
            return False

        return True

    def _build_intent_context(self, intent_result: Any, chosen_by_user: bool = False, resume_snapshot: str = "") -> str:
        return task_executor.build_intent_context(self.purpose, intent_result, chosen_by_user=chosen_by_user, resume_snapshot=resume_snapshot)

    def _parse_progress_tag(self, content: str) -> dict | None:
        """解析进度标签（XML 格式 <PROGRESS>{...}</PROGRESS>）

        Args:
            content: Agent 输出内容

        Returns:
            {"status": "completed|in_progress", "summary": "..."} | None
        """
        import json
        import re
        match = re.search(
            r'<PROGRESS>\s*(\{.*?\})\s*</PROGRESS>',
            content, re.DOTALL,
        )
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                return None
        return None

    def _remove_progress_tag(self, content: str) -> str:
        """移除进度标签（不显示给用户）

        Args:
            content: Agent 输出内容

        Returns:
            清理后的内容
        """
        import re
        return re.sub(
            r'<PROGRESS>\s*\{.*?\}\s*</PROGRESS>',
            "",
            content, flags=re.DOTALL,
        ).strip()

    def _update_goal_progress(self, status: str) -> None:
        status_msg = task_executor.update_goal_progress(self.purpose, self.drive, status)
        if status_msg:
            print(f"\n{status_msg}", flush=True)

    # ── Task v2: 完成 + 知识提取 ───────────────────────────────

    def _complete_task(self, task: Any) -> None:
        """完成一个 Task，触发知识提取。

        Args:
            task: Task 对象（consciousness.task.Task）
        """
        task_id = task.task_id
        logger.info("[TaskComplete] 所有子目标完成，标记 Task 完成: %s", task_id)

        # 1. 标记完成
        completed = self.task_manager.complete_task(task_id)
        if not completed:
            return

        print(f"\n[任务] 完成: {task.description[:40]}", flush=True)

        # 2. 触发知识提取（从 cognitive_log 总结）
        self._extract_task_knowledge(completed)

    def _extract_task_knowledge(self, task: Any) -> None:
        """Task 完成时：从认知日志提取知识到长期记忆。

        调用 MemoryExtractor.extract_task_completion()，
        LLM 从 cognitive_log 中提取：学到了什么、踩了什么坑、用户偏好、模式。

        Args:
            task: 已完成的 Task 对象
        """
        try:
            # 获取 agent 的 extractor
            extractor = getattr(self.agent, "memory_extractor", None)
            if not extractor:
                logger.warning("[TaskComplete] 无 memory_extractor，跳过知识提取")
                return

            if not hasattr(extractor, "extract_task_completion"):
                logger.warning("[TaskComplete] extractor 版本不支持 task_completion")
                return

            # 执行知识提取
            logger.info("[TaskComplete] 开始知识提取: task=%s", task.task_id)
            ids = extractor.extract_task_completion(task, user_id=self.user_id)

            if ids:
                print(f"[知识] 从任务中提取了 {len(ids)} 条长期记忆", flush=True)
            else:
                logger.info("[TaskComplete] 无值得长期保存的知识")
        except Exception as e:
            logger.error("[TaskComplete] 知识提取失败: %s", e)

    # ── Hooks ────────────────────────────────────────────────────

    def _on_wake(self) -> None:
        """苏醒（根据欲望状态决定行为）

        行为策略：
        - learn_topic: 后台线程执行（不阻塞苏醒）
        - greet_user: 不立即执行（用户可能不在场，等 sleeping 时执行）
        - progress_goal/express_idea: 不立即执行（等 sleeping 时执行）

        如果意识系统未加载，跳过火焰更新（生命存在但无意识）。
        """
        self._last_active = time.time()
        if self._load_consciousness:
            self.consciousness._last_l2_time = time.time()
            # 调用意识系统的 on_wake，生成问候意图（基于梦境报告）
            logger.info("[ConsciousLiving._on_wake] 调用 consciousness.on_wake()")
            self.consciousness.on_wake()
            # 立即检查并执行意图（问候等）
            self._check_intent()

        # 苏醒时能量恢复（睡眠恢复）
        if self.drive:
            self.drive.restore_energy(0.15)
            logger.info("[ConsciousLiving._on_wake] 苏醒能量恢复: %.2f", self.drive.energy.level)

        # 火焰点燃（如果意识系统已加载）
        if self._load_consciousness:
            si = self.consciousness.get_self_image()
            si.last_user_activity_time = time.time()

        # 加载 fresh tail：让 agent "带着最近的记忆醒来"
        # 从 DB 还原完整的消息序列，包括 assistant(tool_calls) + tool 配对
        if self.agent.conversation_db and self.agent.context_assembler:
            agent = self.agent._get_agent()
            recent = self.agent.conversation_db.get_recent(
                self.agent.context_assembler.FRESH_TAIL_COUNT,
                session_id=self.session_id,
            )

            # 第一遍：收集 assistant 的 tool_call_ids（用于过滤孤立 tool 消息）
            assistant_tc_ids: set[str] = set()
            for m in recent:
                if m.get("role") == "assistant":
                    metadata = m.get("metadata", {})
                    if isinstance(metadata, str):
                        import json
                        try:
                            metadata = json.loads(metadata)
                        except Exception:
                            metadata = {}
                    if isinstance(metadata, dict):
                        for tc in metadata.get("tool_calls", []):
                            tc_id = tc.get("id", "")
                            if tc_id:
                                assistant_tc_ids.add(tc_id)

            # 第二遍：重建消息列表，从 DB metadata 恢复 tool_calls / reasoning_content
            restored: list[dict] = []
            for m in recent:
                role = m.get("role", "user")
                if role == "user":
                    restored.append({"role": "user", "content": m.get("content", "")})
                elif role == "assistant":
                    msg: dict[str, Any] = {"role": "assistant", "content": m.get("content", "")}
                    metadata = m.get("metadata", {})
                    if isinstance(metadata, str):
                        import json
                        try:
                            metadata = json.loads(metadata)
                        except Exception:
                            metadata = {}
                    if isinstance(metadata, dict):
                        if metadata.get("tool_calls"):
                            msg["tool_calls"] = metadata["tool_calls"]
                        if metadata.get("reasoning_content"):
                            msg["reasoning_content"] = metadata["reasoning_content"]
                    restored.append(msg)
                elif role == "tool":
                    tc_id = m.get("tool_call_id", "")
                    if tc_id and tc_id in assistant_tc_ids:
                        restored.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": m.get("content", ""),
                        })

            # 第三遍：清理不完整的 tool_calls（防止 DeepSeek 400）
            # 使用公用方法，剥离 assistant 有 tool_calls 但缺少 tool 响应的残缺记录
            from xiaomei_brain.base.message_utils import scrub_tool_calls_incomplete
            before = len(restored)
            restored = scrub_tool_calls_incomplete(restored)
            if len(restored) < before:
                logger.warning(
                    "[ConsciousLiving] 剥离了 %d 条不完整 tool_calls 消息",
                    before - len(restored),
                )

            # 第四遍：清理 ReAct 循环残留的空 assistant 消息
            cleaned = []
            i = 0
            while i < len(restored):
                m = restored[i]
                if (m.get("role") == "assistant"
                    and not m.get("content")
                    and not m.get("reasoning_content")):
                    i += 1
                    continue
                cleaned.append(m)
                i += 1
            if len(cleaned) < len(restored):
                logger.info("[ConsciousLiving] 清理 %d 条 ReAct 残留消息", len(restored) - len(cleaned))

            agent.messages = cleaned
            if agent.messages:
                logger.info("[ConsciousLiving] 苏醒时加载 fresh_tail: %d 条消息", len(agent.messages))

        logger.info("[ConsciousLiving] Good morning! 火焰点燃。")

        # 检查欲望状态
        actions = self.drive.check_desire_actions()

        if actions:
            logger.info(
                "[ConsciousLiving] 苏醒时欲望检查: %d 个候选行为",
                len(actions)
            )
            for a in actions[:3]:
                logger.info("  - %s (优先级 %.2f)", a["type"], a["priority"])

            # 检查是否有学习行为（放后台执行）
            for action in actions:
                if action["type"] == "learn_topic":
                    # 学习放后台线程，不阻塞苏醒
                    def run_learn():
                        try:
                            logger.info("[后台学习] 开始执行...")
                            self.action_executor.execute(action)
                            logger.info("[后台学习] 完成")
                        except Exception as e:
                            logger.warning("[后台学习] 失败: %s", e)

                    thread = threading.Thread(target=run_learn, daemon=True)
                    thread.start()
                    logger.info("[ConsciousLiving] 学习行为已放入后台线程")
                    break  # 只执行一个学习
        else:
            logger.info("[ConsciousLiving] 苏醒时欲望平稳，无主动行为")

    def _on_wake_up(self) -> None:
        """从睡眠/空闲中醒来，收到用户消息时调用"""
        logger.info("[ConsciousLiving] Waking up — message received!")

        # 调用意识系统的 on_wake，生成问候意图（基于梦境报告）
        if self._load_consciousness:
            self.consciousness.on_wake()

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