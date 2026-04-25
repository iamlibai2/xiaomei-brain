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

from .context_assembler import ContextAssembler as ConsciousContextAssembler
from .core import Consciousness, ConsciousnessReport, TickResult
from .intent import Intent
from .storage import ConsciousnessStorage
from .self_image import SelfImage, FlameState
from ..drive import DriveEngine, EventExtractor, DesireActionExecutor
from ..purpose import PurposeEngine, IntentUnderstanding, task_executor, Goal, GoalType, GoalStatus, IntentResult, GoalRelation

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
        self._cancel_requested: bool = False  # Ctrl+C 取消当前动作

        # Drive 系统（边缘系统）
        agent_id = "xiaomei"
        if agent_instance and hasattr(agent_instance, "agent_id"):
            agent_id = agent_instance.agent_id
        self.drive = DriveEngine(agent_id)

        # Purpose 系统（前额叶层）
        llm_client = None
        if agent_instance and hasattr(agent_instance, "llm"):
            llm_client = agent_instance.llm
        self.purpose = PurposeEngine(
            agent_id=agent_id,
            llm_client=llm_client,
            drive=self.drive,
        )

        # 欲望行为执行器
        self.action_executor = DesireActionExecutor(self, agent_id=self.agent.id)

        # 事件提取器
        self.event_extractor = EventExtractor()

        # Intent Understanding
        self.intent_understanding = IntentUnderstanding(llm_client)

        # 意识系统（引用 Drive 和 Purpose）
        self.consciousness = Consciousness(
            agent_instance,
            drive=self.drive,
            purpose=self.purpose,
        )
        self._setup_consciousness()

        # 注入 consciousness 层上下文组装器（替换 agent_manager 创建的旧 assembler）
        self._inject_context_assembler()

        # Intent 测试命令
        self._intent_commands = {
            "intent": self._cmd_show_intent,
            "fuel": self._cmd_manual_fuel,
            "flame": self._cmd_show_flame,
            "tick": self._cmd_tick_count,
            "think": self._cmd_show_inner_thought,
            "identity": self._cmd_show_identity,
            "drive": self._cmd_show_drive,
            "purpose": self._cmd_show_purpose,
            "tool": self._cmd_tool_expand,
        }

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

    def _get_consciousness_state(self) -> dict:
        """Build consciousness state dict for context mode decision."""
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
        """
        old_ca = getattr(self.agent, "context_assembler", None)
        if old_ca is None:
            logger.warning("[ConsciousLiving] No context_assembler to replace")
            return

        self.agent.context_assembler = ConsciousContextAssembler(
            conversation_db=self.agent.conversation_db,
            dag=old_ca.dag,
            self_model=self.agent.self_model,
            longterm_memory=self.agent.longterm_memory,
            drive=self.drive,
            self_image=self.consciousness.self_image,
            purpose=self.purpose,
        )
        logger.info("[ConsciousLiving] context_assembler injected (consciousness-aware)")

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
        identity_name = si.identity.identity if hasattr(si.identity, 'identity') else str(si.identity)
        birth = si.identity.birth_date if hasattr(si.identity, 'birth_date') else "?"
        personality = si.identity.base_personality if hasattr(si.identity, 'base_personality') else ""
        traits = ",".join(si.core_traits) if hasattr(si, 'core_traits') else ""
        values = ",".join(si.values) if hasattr(si, 'values') else ""
        logger.info("========== 初始化完成 ==========")
        logger.info("  identity   : %s", identity_name)
        logger.info("  birth      : %s", birth)
        logger.info("  personality: %s", personality)
        logger.info("  age        : %ds", int(si.consciousness_age))
        logger.info("  traits     : %s", traits)
        logger.info("  values     : %s", values)
        logger.info("==================================")

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
        """字符级输入清洗。

        使用字符遍历而非 encode/decode 往返，避免 surrogatepass
        破坏 CJK 多字节边界导致中文乱码。

        处理：
        - 退格符 (\\x08, \\x7f)：模拟退格删除前一个字符
        - 代理字符 (\\ud800-\\udfff)：直接跳过
        - 替换字符 (\\ufffd)：直接跳过
        - 控制字符 (ord < 0x20)：跳过，保留 \\t \\n \\r
        """
        buf: list[str] = []
        for ch in text:
            if ch in ("\x08", "\x7f"):
                if buf:
                    buf.pop()
            elif ch == "\ufffd" or ("\ud800" <= ch <= "\udfff"):
                continue
            elif ord(ch) < 0x20 and ch not in ("\t", "\n", "\r"):
                continue
            else:
                buf.append(ch)
        return "".join(buf)

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
        old = self.state
        self.state = new_state
        # print 备份：daemon 线程日志容易被 stdin/stdout 干扰，print 总是可见
        print(f"[ConsciousLiving] {old.value} → {new_state.value}", flush=True)
        logger.info("[ConsciousLiving] %s → %s", old.value, new_state.value)

        # 更新意识系统中的 agent_state
        si = self.consciousness.get_self_image()
        si.agent_state = new_state.value

    # ── Loop: AWAKE ──────────────────────────────────────────────

    def _loop_awake(self) -> None:
        """AWAKE 状态：统一 tick + 消息处理"""
        # 统一心跳入口
        result = self.consciousness.tick(agent_state=self.state.value)

        # L2 触发后检查 Intent 和欲望行为
        if result == TickResult.L2_TRIGGERED:
            self._check_intent()
            if self.consciousness.self_image.user_idle_duration > 300:
                self._check_desire_actions()

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
        """SLEEPING 状态：统一 tick + 消息等待 + 触发 DREAMING"""
        dream_start = time.time()

        while True:
            # 统一心跳入口（L0/L1/L2/L3 各自按条件触发，生命状态不限制意识深度）
            result = self.consciousness.tick(
                agent_state=self.state.value,
                in_dream=False,
                dream_start=dream_start,
            )

            # L2 触发后检查 Intent 和欲望行为
            if result == TickResult.L2_TRIGGERED:
                self._check_intent()
                self._check_desire_actions()

            # L3 触发：切换到 DREAMING 状态
            if result == TickResult.L3_TRIGGERED:
                self._transition(LivingState.DREAMING)
                return  # 回到 run() 主循环，进入 _loop_dreaming()

            # 检查 Intent（L2 未触发时也可能有待处理 Intent）
            if result != TickResult.L2_TRIGGERED:
                self._check_intent()

            # 欲望行为周期检查（每 60 秒）
            self._check_desire_actions_periodic()

            # 等待消息
            msg = self._wait_message(timeout=self.tick_interval)

            if msg is not None:
                self._on_wake_up()
                self._transition(LivingState.AWAKE)
                self._handle_message(msg)
                self._last_active = time.time()
                return

    # ── Loop: DREAMING ───────────────────────────────────────────

    def _loop_dreaming(self) -> None:
        """DREAMING 状态：进入 → 调用一次 tick() → 切回 SLEEPING"""
        # 进入时调用一次 tick()
        result = self.consciousness.tick(
            agent_state=self.state.value,
            in_dream=True,
            dream_start=time.time(),
        )

        if result == TickResult.L3_TRIGGERED:
            report = self.consciousness.get_last_report()
            if report:
                logger.info("[ConsciousLiving] L3燃烧: %s", report.summary[:50])

        # 一次 L3 后切回 SLEEPING，继续 sleep 周期
        self._transition(LivingState.SLEEPING)

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
        """
        # 检查间隔（用 consciousness._l0_count，每 60 次 = 60 秒）
        l0 = self.consciousness.l0_count
        logger.debug("[欲望周期] l0_count=%d", l0)
        if l0 != 0:
            return  # 只在 l0_count == 0 时执行（L1 刚触发后）

        # l0_count == 0，执行周期检查
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
        # 忽略空消息（如用户按回车找回输入行）
        if not msg.content or not msg.content.strip():
            logger.debug("[ConsciousLiving] 忽略空消息")
            return

        logger.info("[ConsciousLiving] 收到消息: %s", msg.content[:50])

        # 重置取消标志（新消息来了，之前的取消失效）
        self._cancel_requested = False

        # Intent 测试命令（支持带参数，如 "tool 3"）
        parts = msg.content.strip().split(None, 1)
        cmd = parts[0].lower()
        cmd_args = parts[1] if len(parts) > 1 else ""
        if cmd in self._intent_commands:
            logger.info("[ConsciousLiving] 执行测试命令: %s %s", cmd, cmd_args)
            handler = self._intent_commands[cmd]
            if cmd_args and handler == self._cmd_tool_expand:
                self._cmd_tool_expand(cmd_args)
            else:
                handler()
            return

        # Agent 命令（如 db/memory/dag）
        if self.agent.commands:
            logger.info("[ConsciousLiving] 尝试 Agent 命令: %s", msg.content)
            result = self.agent.commands.execute(
                msg.content,
                user_id=msg.user_id,
                session_id=msg.session_id,
            )
            if result:
                logger.info("[ConsciousLiving] Agent 命令成功")
                print(f"\n{result.output}", flush=True)
                self._print_prompt()
                return
            else:
                logger.info("[ConsciousLiving] Agent 命令无匹配，转为对话")

        # "继续"检测：列出活跃任务让用户选
        if self.purpose and self._is_continue_statement(msg.content):
            goals = self.purpose.get_top_level_goals()
            if len(goals) == 1:
                # 只有一个活跃目标，直接复用
                self.purpose.set_current(goals[0].id)
                print(f"[目标] 延续任务: {goals[0].description[:40]}", flush=True)
                from xiaomei_brain.purpose.intent import IntentResult, IntentType, GoalRelation
                fake_intent = IntentResult(
                    intent_type=IntentType.TASK,
                    goals=[goals[0]],
                    relation=GoalRelation.MODIFIES,
                    target_goal_id=goals[0].id,
                    confidence=1.0,
                    reasoning="延续现有任务",
                )
                self._run_chat(msg, self._build_intent_context(fake_intent, chosen_by_user=True))
                return
            elif len(goals) > 1:
                # 多个活跃目标，让用户选
                confirm_info = {
                    "type": "continue_goal",
                    "question": "要继续哪个任务？",
                    "options": [g.description for g in goals],
                    "goal_ids": [g.id for g in goals],
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

        # 意图分析（每条消息都分析）
        intent_result = self._analyze_intent(msg.content)
        logger.info(
            "[ConsciousLiving] 意图分析: type=%s, goals=%d, confidence=%.2f",
            intent_result.intent_type.value,
            len(intent_result.goals),
            intent_result.confidence,
        )

        # 如果是 TASK 且置信度足够，添加目标
        if intent_result.is_task() and intent_result.has_goal() and intent_result.confidence >= 0.5:
            self._handle_task_intent(intent_result, msg)
            # 如果目标分解后需要用户确认，保存原始消息并暂停
            if self._waiting_confirm:
                self._pending_confirm_msg = msg
                self._pending_confirm_intent = intent_result
                return

        # 构建 intent_context（注入 system prompt）
        intent_context = self._build_intent_context(intent_result)

        # 执行对话
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
        # `/` 前缀 = 明确的任务指令，跳过 LLM 分析直接构造 task
        if user_input.startswith("/"):
            from xiaomei_brain.purpose.intent import IntentType, GoalRelation
            task_text = user_input[1:].strip()
            goal = Goal(
                description=task_text,
                goal_type=GoalType.EXECUTABLE,
                status=GoalStatus.PENDING,
            )
            return IntentResult(
                intent_type=IntentType.TASK,
                goals=[goal],
                sub_goals=[],
                relation=GoalRelation.NEW,
                target_goal_id=None,
                confidence=1.0,
                reasoning=f"指令以 / 开头，明确的任务请求：{task_text[:50]}",
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
        """处理任务意图：添加目标到 PurposeEngine，包含子目标分解

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
                            print(f"[目标] 已放弃: {existing.description[:40]}", flush=True)
                        else:
                            print(f"[目标] 延续任务: {existing.description[:40]}", flush=True)
                        return

            # 确定父目标（如果 relation 是 sub_goal_of）
            parent_id = None
            if intent_result.relation.value == "sub_goal_of" and intent_result.target_goal_id:
                parent_id = intent_result.target_goal_id

            # 添加主目标
            new_goal = self.purpose.add_goal(
                description=goal.description,
                goal_type=goal.goal_type,
                parent_id=parent_id,
            )
            logger.info(
                "[Intent] 新目标添加: id=%s, desc=%s",
                new_goal.id,
                new_goal.description[:50],
            )

            # 如果有子目标（来自 IntentUnderstanding 的分解），直接添加
            if intent_result.has_sub_goals():
                sub_goals = self.purpose.decompose_goal(
                    goal_id=new_goal.id,
                    sub_descriptions=intent_result.sub_goals,
                )
                logger.info(
                    "[Intent] 子目标分解完成: %d 个子目标",
                    len(sub_goals),
                )
                print(f"\n[目标] 已分解为 {len(sub_goals)} 个子目标:", flush=True)
                for i, sg in enumerate(sub_goals):
                    print(f"  {i+1}. {sg.description[:40]}", flush=True)

                # 激活第一个子目标（一个任务一个任务依次进行）
                if sub_goals:
                    self.purpose.set_current(sub_goals[0].id)
                    print(f"[目标] 当前执行: {sub_goals[0].description[:40]}", flush=True)

                    # 检查是否需要用户确认（两 Tier）
                    # Tier 1: LLM 结构化输出（最佳，有具体选项）
                    # Tier 2: 本地关键字回退（第一个子目标含"确定/选择/确认/讨论"等词）
                    confirm_info = self._build_confirm_info(
                        sub_goals[0], intent_result,
                    )
                    if confirm_info:
                        self._pending_confirm = confirm_info
                        self._waiting_confirm = True
                        # 通知上层渲染选择框（TUI/CLI 各自实现）
                        if self.on_confirm_required:
                            self.on_confirm_required(confirm_info)
                        else:
                            # 默认：直接 print 选择框（CLI 场景）
                            print(f"\n[确认] {confirm_info['question']}")
                            for i, opt in enumerate(confirm_info['options']):
                                print(f"  [{i+1}] {opt}")
                            print("  [0] 自定义输入")
                        return  # 暂停，等待用户选择
            else:
                # 无子目标 = 单步任务，直接执行
                self.purpose.set_current(new_goal.id)
                print(f"[目标] 当前执行: {new_goal.description[:40]}", flush=True)
                new_intent = self._build_intent_context_for_goal(new_goal)
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
                    # 都不选，走正常意图分析
                    original_msg = self._pending_confirm_msg
                    self._pending_confirm = None
                    self._waiting_confirm = False
                    self._pending_confirm_msg = None
                    if original_msg:
                        intent_result = self._analyze_intent(original_msg.content)
                        self._run_chat(original_msg, self._build_intent_context(intent_result))
                    return
                if 1 <= idx <= len(confirm["goal_ids"]):
                    goal_id = confirm["goal_ids"][idx - 1]
                    self.purpose.set_current(goal_id)
                    goal = self.purpose.goals.get(goal_id)
                    if goal:
                        print(f"[目标] 延续任务: {goal.description[:40]}", flush=True)

                    # 清理确认状态
                    original_msg = self._pending_confirm_msg
                    self._pending_confirm = None
                    self._waiting_confirm = False
                    self._pending_confirm_msg = None

                    if original_msg:
                        from xiaomei_brain.purpose.intent import IntentResult, IntentType, GoalRelation
                        fake_intent = IntentResult(
                            intent_type=IntentType.TASK,
                            goals=[goal],
                            relation=GoalRelation.MODIFIES,
                            target_goal_id=goal_id,
                            confidence=1.0,
                            reasoning="用户选择延续任务",
                        )
                        self._run_chat(original_msg, self._build_intent_context(fake_intent, chosen_by_user=True))
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

            # 如果下一个子目标是纯确认型（描述以"确认"开头），跳过 LLM 执行
            # 这类子目标只需要输出确认信息，不需要再次调用 LLM
            if next_goal.description.startswith("确认"):
                print(f"小美: {next_goal.description}，等待你的下一步指示。", flush=True)
                return

            # 为新目标构建 intent_context（current 已指向新目标）
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
            intent_type=IntentType.TASK,
            goals=[goal],
            relation=GoalRelation.MODIFIES,
            target_goal_id=goal.id,
            confidence=1.0,
            reasoning=f"目标推进：{goal.description[:50]}",
        )
        return self._build_intent_context(fake_intent, chosen_by_user=True)

    def _run_chat(self, msg: LivingMessage, intent_context: str = "") -> None:
        """执行对话（统一的 chat 入口）"""
        def run():
            try:
                print("\n小美: ", end="", flush=True)
                cs = self._get_consciousness_state()
                content = self.agent.chat(
                    msg.content,
                    session_id=msg.session_id,
                    user_id=msg.user_id,
                    on_chunk=None,
                    intent_context=intent_context,
                    consciousness_state=cs,
                )

                # Ctrl+C 取消：丢弃 LLM 结果
                if self._cancel_requested:
                    logger.info("[ConsciousLiving] LLM 结果已丢弃（取消请求）")
                    print("\n[取消] 已中断", flush=True)
                    self._print_prompt()
                    return

                # 解析进度标签
                progress_status = self._parse_progress_tag(content)
                if progress_status and self.purpose:
                    self._update_goal_progress(progress_status)

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

                logger.info("[ConsciousLiving] 对话完成")
                self._print_prompt()

                # 更新意识系统
                self.consciousness.on_user_interaction(msg.content, display_content)
            except Exception as e:
                logger.error("[ConsciousLiving] Chat failed: %s", e)
                print(f"\n[错误] {e}", flush=True)
                self._print_prompt()

        run()

    def _build_intent_context(self, intent_result: Any, chosen_by_user: bool = False) -> str:
        return task_executor.build_intent_context(self.purpose, intent_result, chosen_by_user=chosen_by_user)

    def _parse_progress_tag(self, content: str) -> str | None:
        """解析进度标签

        Args:
            content: Agent 输出内容

        Returns:
            "completed" | "in_progress" | None
        """
        import re
        match = re.search(r"<PROGRESS>(completed|in_progress)</PROGRESS>", content)
        if match:
            return match.group(1)
        return None

    def _remove_progress_tag(self, content: str) -> str:
        """移除进度标签（不显示给用户）

        Args:
            content: Agent 输出内容

        Returns:
            清理后的内容
        """
        import re
        return re.sub(r"<PROGRESS>(completed|in_progress)</PROGRESS>", "", content).strip()

    def _update_goal_progress(self, status: str) -> None:
        status_msg = task_executor.update_goal_progress(self.purpose, self.drive, status)
        if status_msg:
            print(f"\n{status_msg}", flush=True)

    # ── Intent 测试命令 ──────────────────────────────────────────

    def _cmd_show_intent(self) -> None:
        """显示当前 Intent"""
        logger.info("[CLI] 执行命令: intent")
        intent = self.consciousness.get_pending_intent()
        if intent:
            print(f"\n当前意图: {intent.type.value} (priority={intent.priority})", flush=True)
            print(f"内容: {intent.content}", flush=True)
            self._print_prompt()
        else:
            print("\n无待处理意图", flush=True)
            self._print_prompt()

    def _cmd_manual_fuel(self) -> None:
        """手动触发加柴"""
        logger.info("[CLI] 执行命令: fuel")
        print("\n手动触发 L2 加柴...", flush=True)
        self.consciousness._last_l2_time = time.time()
        report = self.consciousness.tick_L2("manual")
        logger.info("[ConsciousLiving] L2加柴: %s", report.summary[:50])

        intent = self.consciousness.get_pending_intent()
        if intent:
            print(f"生成的意图: {intent.type.value}", flush=True)
            print(f"内容: {intent.content[:50]}", flush=True)
        else:
            print("无意图生成（LLM未返回有效意图）", flush=True)
        self._print_prompt()

    def _cmd_show_flame(self) -> None:
        """显示火焰状态"""
        logger.info("[CLI] 执行命令: flame")
        si = self.consciousness.get_self_image()
        print("\n火焰状态:", flush=True)
        print(f"  燃烧时长: {int(si.consciousness_age)}秒", flush=True)
        print(f"  状态: {si.agent_state}", flush=True)
        print(f"  用户空闲: {int(si.user_idle_duration)}秒", flush=True)
        print(f"  能量: {si.energy_level:.2f}", flush=True)
        print(f"  累积变化: {len(si.accumulated_changes)}条", flush=True)
        print(f"  上次加柴: {int(time.time() - self.consciousness._last_l2_time)}秒前", flush=True)
        self._print_prompt()

    def _cmd_tick_count(self) -> None:
        """显示心跳计数"""
        logger.info("[CLI] 执行命令: tick")
        print(f"\nL0 心跳计数: {self.consciousness._l0_count}", flush=True)
        print(f"状态: {self.state.value}", flush=True)
        self._print_prompt()

    def _cmd_show_inner_thought(self) -> None:
        """显示当前内在想法"""
        logger.info("[CLI] 执行命令: think")
        si = self.consciousness.get_self_image()

        print("\n内在感知:", flush=True)
        print(f"  当前想法: {si.inner_thought[:100] if si.inner_thought else '（无）'}", flush=True)
        print(f"  历史想法: {len(si.inner_thought_history)}条", flush=True)

        # 显示历史
        if si.inner_thought_history:
            print("\n最近想法:", flush=True)
            for i, thought in enumerate(si.inner_thought_history[-3:]):
                print(f"  [{i}] {thought[:80]}", flush=True)

        self._print_prompt()

    def _cmd_show_identity(self) -> None:
        """显示意识全景（完整身份分层）"""
        logger.info("[CLI] 执行命令: identity")
        si = self.consciousness.get_self_image()

        print("\n" + "=" * 50, flush=True)
        print("       意识全景", flush=True)
        print("=" * 50, flush=True)

        # L0: 先天身份
        print("\n【L0: 先天身份】（不可变）", flush=True)
        print(f"  名字: {si.identity}", flush=True)
        print(f"  诞生: {si.birth_date}", flush=True)
        print(f"  基础性格: {si.base_personality}", flush=True)

        # L1: 基础特质
        print("\n【L1: 基础特质】（极难变）", flush=True)
        for trait in si.core_traits:
            print(f"  - {trait}", flush=True)

        # L2: 价值观
        print("\n【L2: 价值观】（缓慢变化）", flush=True)
        for value in si.values:
            print(f"  - {value}", flush=True)

        # L3: 社会身份
        print("\n【L3: 社会身份】（动态变化）", flush=True)
        print(f"  当前角色: {si.role}", flush=True)
        print(f"  关系状态: {si.relationship_status}", flush=True)
        print(f"  关系深度: {si.relationship_depth:.2f}", flush=True)
        print(f"  用户信任: {si.user_trust_level:.2f}", flush=True)

        # L4: 状态身份
        print("\n【L4: 状态身份】（实时变化）", flush=True)
        print(f"  当前心情: {si.current_mood}", flush=True)
        print(f"  能量水平: {si.energy_level:.2f}", flush=True)
        print(f"  注意力: {si.attention_focus}", flush=True)

        # 我在哪
        print("\n【我在哪】", flush=True)
        print(f"  当前环境: {si.environment}", flush=True)

        # 火焰状态
        print("\n【火焰状态】", flush=True)
        print(f"  燃烧时长: {int(si.consciousness_age)}秒 ({int(si.consciousness_age/3600)}小时)", flush=True)
        print(f"  Agent状态: {si.agent_state}", flush=True)
        print(f"  用户空闲: {int(si.user_idle_duration)}秒", flush=True)
        print(f"  记忆数量: {si.memory_count}", flush=True)
        print(f"  累积变化: {len(si.accumulated_changes)}条", flush=True)

        # 内在感知
        print("\n【内在感知】", flush=True)
        if si.inner_thought:
            print(f"  当前想法: {si.inner_thought[:100]}", flush=True)
        else:
            print(f"  当前想法: （无）", flush=True)
        print(f"  历史想法: {len(si.inner_thought_history)}条", flush=True)

        # 梦境
        if si.last_dream_summary:
            print("\n【最近梦境】", flush=True)
            print(f"  {si.last_dream_summary[:150]}", flush=True)

        print("\n" + "-" * 50, flush=True)
        self._print_prompt()

    def _cmd_show_drive(self) -> None:
        """显示 Drive 状态"""
        logger.info("[CLI] 执行命令: drive")

        print("\n" + "=" * 50, flush=True)
        print("       Drive 状态（边缘系统）", flush=True)
        print("=" * 50, flush=True)

        # 情绪
        print("\n【情绪状态】", flush=True)
        print(f"  类型: {self.drive.emotion.type.value}", flush=True)
        print(f"  强度: {self.drive.emotion.intensity:.2f}", flush=True)

        # 激素
        print("\n【激素状态】", flush=True)
        print(f"  多巴胺: {self.drive.hormone.dopamine:.2f}（动力）", flush=True)
        print(f"  血清素: {self.drive.hormone.serotonin:.2f}（满足）", flush=True)
        print(f"  皮质醇: {self.drive.hormone.cortisol:.2f}（压力）", flush=True)
        print(f"  催产素: {self.drive.hormone.oxytocin:.2f}（连接）", flush=True)

        # 欲望
        print("\n【欲望状态】", flush=True)
        print(f"  归属欲: {self.drive.desire.belonging:.2f}（阈值 {self.drive.config.desire.thresholds.belonging:.2f})", flush=True)
        print(f"  认知欲: {self.drive.desire.cognition:.2f}（阈值 {self.drive.config.desire.thresholds.cognition:.2f})", flush=True)
        print(f"  成就欲: {self.drive.desire.achievement:.2f}（阈值 {self.drive.config.desire.thresholds.achievement:.2f})", flush=True)
        print(f"  表达欲: {self.drive.desire.expression:.2f}（阈值 {self.drive.config.desire.thresholds.expression:.2f})", flush=True)

        # 激励
        print("\n【激励状态】", flush=True)
        print(f"  动力水平: {self.drive.motivation.motivation_level:.2f}", flush=True)
        print(f"  预期奖励: {self.drive.motivation.expected_reward:.2f}", flush=True)

        # 欲望驱动行为检查
        print("\n【欲望驱动】", flush=True)
        actions = self.drive.check_desire_actions()
        if actions:
            for a in actions:
                print(f"  {a['type']}: 优先级 {a['priority']:.2f}", flush=True)
                print(f"    原因: {a['reason']}", flush=True)
        else:
            print("  （无触发行为）", flush=True)

        print("\n" + "-" * 50, flush=True)
        self._print_prompt()

    def _cmd_show_purpose(self) -> None:
        """显示 Purpose 状态"""
        logger.info("[CLI] 执行命令: purpose")

        print("\n" + "=" * 50, flush=True)
        print("       Purpose 状态（前额叶层）", flush=True)
        print("=" * 50, flush=True)

        # 存在意义
        print("\n【存在意义】", flush=True)
        print(f"  我是: {self.purpose.meaning.identity}", flush=True)
        print(f"  价值观: {', '.join(self.purpose.meaning.values[:3])}", flush=True)
        print(f"  底线: {', '.join(self.purpose.meaning.constraints[:2])}", flush=True)

        # 当前主目标（如果有）
        current = self.purpose.get_current()
        if current and current.parent_id is None:
            print("\n【当前主目标】", flush=True)
            print(f"  {current.description}", flush=True)
            print(f"  状态: {current.status.value} | 进度: {current.progress:.0%}", flush=True)

            # 子目标详情
            sub_goals = self.purpose.get_sub_goals(current.id)
            if sub_goals:
                completed = [sg for sg in sub_goals if sg.is_completed()]
                print(f"\n  【子目标】({len(completed)}/{len(sub_goals)} 已完成)", flush=True)
                for i, sg in enumerate(sub_goals, 1):
                    if sg.is_completed():
                        status = "✓"
                    elif sg.is_active():
                        status = "→"
                    else:
                        status = "○"
                    print(f"    {status} {i}. {sg.description[:35]}", flush=True)

        # 待执行目标（不含子目标）
        print("\n【待执行目标】", flush=True)
        pending = self.purpose.get_pending_goals()
        # 过滤掉子目标
        main_pending = [g for g in pending if g.parent_id is None and g.id != (current.id if current else None)]
        if main_pending:
            for i, g in enumerate(main_pending[:5], 1):
                priority = self.purpose.calculate_priority(g)
                print(f"  {i}. {g.description[:40]} (优先级 {priority:.2f})", flush=True)
        else:
            print("  （无待执行目标）", flush=True)

        # 已完成目标统计
        completed = self.purpose.get_completed_goals()
        main_completed = [g for g in completed if g.parent_id is None]
        print(f"\n【已完成主目标】 {len(main_completed)}个", flush=True)

        print("\n" + "-" * 50, flush=True)
        self._print_prompt()

    def _cmd_tool_expand(self, args: str = "") -> None:
        """展开工具调用详情: tool [N] 或 tool list"""
        from xiaomei_brain.agent.core import expand_tool_call, list_tool_calls

        logger.info("[CLI] 执行命令: tool %s", args)

        if not args or args.strip() == "list":
            print("\n【最近工具调用】", flush=True)
            list_tool_calls(10)
        else:
            try:
                idx = int(args.strip())
                expand_tool_call(idx)
            except ValueError:
                print(f"  用法: tool <编号> | tool list", flush=True)

        self._print_prompt()

    # ── Hooks ────────────────────────────────────────────────────

    def _on_wake(self) -> None:
        """苏醒（根据欲望状态决定行为）

        行为策略：
        - learn_topic: 后台线程执行（不阻塞苏醒）
        - greet_user: 不立即执行（用户可能不在场，等 sleeping 时执行）
        - progress_goal/express_idea: 不立即执行（等 sleeping 时执行）
        """
        self._last_active = time.time()
        self.consciousness._last_l2_time = time.time()

        # 火焰点燃
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

            # 收集 assistant 的 tool_call_ids（用于过滤孤立 tool 消息）
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

            agent.messages = []
            for m in recent:
                role = m.get("role", "user")
                if role == "user":
                    agent.messages.append({"role": "user", "content": m.get("content", "")})
                elif role == "assistant":
                    # 从 metadata 还原 tool_calls 和 reasoning_content
                    msg = {"role": "assistant", "content": m.get("content", "")}
                    metadata = m.get("metadata", {})
                    if isinstance(metadata, str):
                        import json
                        try:
                            metadata = json.loads(metadata)
                        except Exception:
                            metadata = {}
                    if isinstance(metadata, dict):
                        tool_calls = metadata.get("tool_calls")
                        if tool_calls:
                            msg["tool_calls"] = tool_calls
                        reasoning = metadata.get("reasoning_content")
                        if reasoning:
                            msg["reasoning_content"] = reasoning
                    agent.messages.append(msg)
                elif role == "tool":
                    # 只保留有对应 assistant 的 tool 消息（过滤孤立的）
                    tc_id = m.get("tool_call_id", "")
                    if tc_id and tc_id in assistant_tc_ids:
                        agent.messages.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": m.get("content", ""),
                        })
            loaded = len(agent.messages)
            if loaded > 0:
                logger.info(
                    "[ConsciousLiving] 苏醒时加载 fresh_tail: %d 条消息",
                    loaded,
                )

            # 清理 ReAct 循环残留：删除连续的前导空 assistant 消息
            # ReAct 循环会产生多个 assistant(tool_calls, 空content) 消息，
            # 只保留最后一个（那个有实际 content 或 reasoning_content）
            cleaned = []
            i = 0
            while i < len(agent.messages):
                m = agent.messages[i]
                # 如果是 assistant 且空 content、无 reasoning_content
                if (m.get("role") == "assistant"
                    and not m.get("content")
                    and not m.get("reasoning_content")):
                    # 跳过它（会被后面的有效 assistant 替代）
                    logger.debug(
                        "[ConsciousLiving] 移除 ReAct 残留 assistant at [%d]: tc=%s",
                        i, bool(m.get("tool_calls")),
                    )
                    i += 1
                    continue
                cleaned.append(m)
                i += 1
            if len(cleaned) < len(agent.messages):
                removed = len(agent.messages) - len(cleaned)
                logger.info("[ConsciousLiving] 清理 %d 条 ReAct 残留消息", removed)
                agent.messages = cleaned

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