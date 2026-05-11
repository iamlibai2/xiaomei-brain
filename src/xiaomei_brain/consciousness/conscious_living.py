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
import os
from datetime import datetime
import threading
import time
from typing import Any

from .action_dispatcher import ActionDispatcher
from .living import Living, LivingState, LivingMessage, HEARTBEAT_NORMAL, HEARTBEAT_DREAM
from .context_assembler import ContextAssembler as ConsciousContextAssembler
from .core import Consciousness, ConsciousnessReport, TickResult
from .intent import Intent
from .storage import ConsciousnessStorage
from .self_image_proxy import SelfImage
from .identity import IdentityConfig
from .perception import PerceptionConfig
from ..drive import DriveEngine
from ..purpose import PurposeEngine, IntentUnderstanding
from .task_orchestrator import TaskOrchestrator

logger = logging.getLogger(__name__)


# ── Re-exports（向后兼容）───────────────────────────────────────────────
# LivingState, LivingMessage 移动到 living.py，此处保持导入路径兼容

# ── ConsciousLiving ─────────────────────────────────────────────────────

class ConsciousLiving(Living):
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
        idle_threshold: float = 0,
        dream_interval: float = 0,
        idle_short: float = 0,
        session_id: str = "main",
        user_id: str = "global",
        tick_interval: float = 0,  # L0 心跳间隔（秒）
        load_consciousness: bool = True,  # 是否加载意识系统
        config: Any | None = None,  # LivingConfig
    ) -> None:
        # 读取 LivingConfig
        if config is None:
            from .config import LivingConfig
            config = LivingConfig()
        self._config = config

                # 解析 agent_id（统一来源）
        self._agent_id = getattr(agent_instance, "id", None) or getattr(agent_instance, "agent_id", "xiaomei")

        super().__init__(
            agent_instance=agent_instance,
            idle_threshold=idle_threshold or config.living.idle_threshold,
            dream_interval=dream_interval or config.living.dream_interval,
            idle_short=idle_short or config.living.idle_short,
            session_id=session_id,
            user_id=user_id,
            tick_interval=tick_interval or config.living.tick_interval,
        )

        # 包装 LLM 客户端：自动控制上下文总 token 量
        from ..agent.context_guard import ContextGuard
        if not isinstance(self.agent.llm, ContextGuard):
            self.agent.llm = ContextGuard(self.agent.llm, max_tokens=80000)

        # Drive 系统（边缘系统）- 延迟加载
        self.drive = DriveEngine(self._agent_id, load=False)

        # Purpose 系统（前额叶层）- 延迟加载
        llm_client = None
        if agent_instance and hasattr(agent_instance, "llm"):
            llm_client = agent_instance.llm
        self.purpose = PurposeEngine(
            agent_id=self._agent_id,
            llm_client=llm_client,
            drive=self.drive,
            load=False,
        )

        # Intent Understanding
        self.intent_understanding = IntentUnderstanding(llm_client)

        # TaskOrchestrator: 任务 orchestration（意图分析、任务创建/路由、确认、chat）
        self.task_orchestrator = TaskOrchestrator(
            parent=self,
            purpose=self.purpose,
            drive=self.drive,
            agent=agent_instance,
            intent_understanding=self.intent_understanding,
            config=self._config,
            on_confirm_required=self.on_confirm_required,
        )

        # ActionDispatcher（统一动作分发）
        self._dispatcher = ActionDispatcher()

        # 意识系统（引用 Drive 和 Purpose）- 只创建结构
        cc = self._config.consciousness if self._config else None
        self.consciousness = Consciousness(
            agent_instance,
            drive=self.drive,
            purpose=self.purpose,
            consciousness_config=cc,
        )
        self._load_consciousness = load_consciousness

        # DreamEngine（梦境总控）- 在 consciousness 创建之后
        from .dream import DreamEngine
        self._dream_engine = DreamEngine(
            consciousness=self.consciousness,
            drive=self.drive,
            ltm=getattr(self.agent, 'longterm_memory', None),
            extractor=getattr(self.agent, 'memory_extractor', None),
            llm=getattr(self.agent, 'llm', None),
            procedure_memory=getattr(self.agent, '_procedure_memory', None),
        )

        # 命令注册表 — 从 living_commands 加载（测试/调试/系统操作）
        from .living_commands import COMMAND_REGISTRY, list_commands as _list_cmds
        self._list_commands = lambda: _list_cmds(self)
        self._intent_commands = {}
        self._commands_taking_args: set = set()
        for name, (handler, takes_args) in COMMAND_REGISTRY.items():
            self._intent_commands[name] = lambda a="", h=handler: h(self, a)
            if takes_args:
                self._commands_taking_args.add(handler)

        # 统一加载所有子系统（先加载数据，确保 drive/purpose/self_image 已就绪）
        self._setup_all()

        # 注入 consciousness 层上下文组装器（子系统加载后再替换旧 assembler）
        self._inject_context_assembler()

        # 初始化过程记忆（ProcedureMemory — LLM学习 + 关键词触发）
        db_path = getattr(self.agent, "db_path", None)
        if db_path is None:
            db_path = os.path.expanduser(f"~/.xiaomei-brain/agents/{self._agent_id}/memory/brain.db")
        self.consciousness.init_procedure_memory(db_path)

        # ActionDispatcher 初始化（接入外部引用）
        from .rules import _init_rules, RULES
        drive_config = getattr(self.drive, 'config', None)
        _init_rules(drive_config=drive_config, living_config=self._config)
        self._dispatcher.load_rules(RULES)
        self._dispatcher.inject_conscious_living(self)

        # 记录初始化摘要
        self._log_initialization()

        # 注册周期任务
        self.register_periodic("heartbeat", self._config.living.tick_interval, self._heartbeat)
        self.register_periodic("surge", self._config.living.surge_interval, self._surge)

    def _log_initialization(self) -> None:
        """记录 ConsciousLiving 初始化摘要"""
        logger.info("=" * 50)
        logger.info("[ConsciousLiving] 初始化摘要")
        logger.info("=" * 50)

        # 基本信息
        logger.info("  agent_id          : %s", self._agent_id)
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
            logger.info("      agent_state   : %s", si.perception.agent_state)
            logger.info("      energy_level  : %.2f", si.body.energy)
            logger.info("      age           : %ds", int(si.growth.consciousness_age))
            logger.info("      idle_duration : %ds", int(si.perception.user_idle_duration))
            logger.info("")
            logger.info("    身份信息:")
            identity_name = si.identity.identity
            logger.info("      identity      : %s", identity_name)
            logger.info("      birth_date    : %s", si.identity.birth_date)
            logger.info("      personality   : %s", si.identity.base_personality)
            traits = ",".join(si.identity.core_traits)
            logger.info("      traits        : %s", traits if traits else "未设置")
            values = ",".join(si.identity.values)
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
                "intent_buffer": [],
                "has_active_goal": self.task_orchestrator.has_active_goal if self.task_orchestrator else False,
            }

        si = self.consciousness.get_self_image()
        pending = si.intent.intent_buffer
        energy = si.body.energy
        has_goal = self.task_orchestrator.has_active_goal if self.task_orchestrator else False
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
            "intent_buffer": pending,
            "has_active_goal": has_goal,
        }

    def _inject_context_assembler(self) -> None:
        """创建 consciousness-aware 的 ContextAssembler 并注入 agent。

        agent_manager 不再创建 ContextAssembler，由本方法统一创建。
        """
        old_ca = getattr(self.agent, "context_assembler", None)
        dag = getattr(self.agent, "_dag", None) or (old_ca.dag if old_ca else None)

        if dag is None:
            logger.warning("[ConsciousLiving] No DAG available, skip context_assembler injection")
            return

        assembler = ConsciousContextAssembler(
            conversation_db=self.agent.conversation_db,
            dag=dag,
            self_model=self.agent.self_model,
            longterm_memory=self.agent.longterm_memory,
            drive=self.drive,
            self_image=self.consciousness.self_image if self._load_consciousness else None,
            purpose=self.purpose,
            config=self._config,
            procedure_memory=getattr(self.agent, "_procedure_memory", None),
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
        # 同步 CommandRegistry 的 assembler 引用
        # CommandRegistry.__init__ 存储 context_assembler 参数为 self.assembler
        if self.agent.commands:
            self.agent.commands.assembler = assembler
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

        # 2.5 将统一叙事存储接入 Drive 和 Purpose（Memory 作为基础设施）
        ltm = getattr(self.agent, "longterm_memory", None)
        if ltm:
            self.drive.set_longterm_memory(ltm)
            self.purpose.set_longterm_memory(ltm)
            logger.info("[ConsciousLiving] 统一叙事存储已接入 Drive 和 Purpose")

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
        storage = ConsciousnessStorage(base_dir, agent_id=self._agent_id)
        self.consciousness.set_storage(storage)

        # 2. 尝试从快照恢复（latest.json，最完整）
        restored = self.consciousness._restore_snapshot()

        # 3. 快照恢复失败则用模块文件恢复
        if not restored:
            restored = self.consciousness.restore_from_storage()

        # 4. 模块恢复也失败，从 identity.md 加载
        if not restored:
            config = IdentityConfig.load(self._agent_id)
            self.consciousness._identity_config = config
            self.consciousness.identity.init_from_identity_config(config)
            logger.info("[ConsciousLiving] 从 IdentityConfig 初始化完成")

            # 如果还是没有数据，使用默认值
            si = self.consciousness.get_self_image()
            if not si.identity.identity or si.identity.identity == "小美":
                si.identity.identity = "小美"
                si.relation.role = "情感陪伴"
                logger.info("[ConsciousLiving] 使用默认值初始化")

        # 4. 加载感知规则（非运行时数据，始终从配置加载）
        self.consciousness._perception_config = PerceptionConfig.load(self._agent_id)
        logger.info("[ConsciousLiving] 从 PerceptionConfig 初始化完成: %d 条规则", len(self.consciousness._perception_config.rules))

    # ── Hook: 状态转换 ───────────────────────────────────────────

    def _on_transition(self, old: LivingState, new_state: LivingState) -> None:
        """状态转换后同步更新意识系统的 agent_state。"""
        if self._load_consciousness:
            si = self.consciousness.get_self_image()
            si.perception.agent_state = new_state.value

    # ── Hook: 心跳 ───────────────────────────────────────────────

    def _heartbeat(self, state: LivingState) -> None:
        """每 tick 调用（1秒一次）。处理意识 L0-L3 tick。

        设置 self._heartbeat_result 供基类读取。

        注意：DREAMING 状态由 _loop_dreaming() 全权处理，不经过此 heartbeat。
        """
        if not self._load_consciousness:
            return

        result = self.consciousness.tick(agent_state=state.value)

        # L3 深度沉思：任何状态都可以发生，不改变生命状态
        # （像人类沉思，发生在清醒/空闲/睡眠中）
        if result == TickResult.L3_TRIGGERED:
            logger.info("[ConsciousLiving] L3 深度沉思完成（%s 状态）", state.value)

        # DREAM 入梦信号：只在 SLEEPING 时触发状态转换
        if result == TickResult.DREAM_TRIGGERED and state == LivingState.SLEEPING:
            self._heartbeat_result = HEARTBEAT_DREAM

    def _surge(self, state: LivingState) -> None:
        """每分钟调用。ActionDispatcher 统一检查主动行为。"""
        self._update_recent_conversations()
        if self._load_consciousness:
            si = self.consciousness.get_self_image()
            self._dispatcher.tick(si)
            self._dispatcher.process_queue()

    def _should_skip_dreaming(self) -> bool:
        return not self._load_consciousness

    def _loop_dreaming(self) -> None:
        """DREAMING 状态循环：运行 DreamEngine。"""
        logger.info("[ConsciousLiving] 进入 DREAMING，运行 DreamEngine")

        if self._should_skip_dreaming():
            self._transition(LivingState.SLEEPING)
            return

        # 运行 DreamEngine（串行执行：情绪整理→记忆强化→L3燃烧→反省）
        try:
            report = self._dream_engine.run()
            logger.info(
                "[ConsciousLiving] DreamEngine 完成: 强化%d条, 提取%d条, 摘要: %s",
                report.memories_reinforced,
                report.memories_extracted,
                report.summary[:50] if report.summary else "",
            )
        except Exception as e:
            logger.error("[ConsciousLiving] DreamEngine 运行失败: %s", e)

        # DreamEngine 完成后生成后续意图（已在 run() 内部写入 intent_buffer）
        # 这里不做额外处理

        self._transition(LivingState.SLEEPING)

    # ── SelfImage 同步 ───────────────────────────────────────

    def _update_recent_conversations(self) -> None:
        """对话结束后更新 SelfImage 的最近对话记录（供主动消息生成）。"""
        si = self.consciousness.self_image if self._load_consciousness else None
        if not si:
            logger.warning("[_update_recent_conversations] self_image 不存在")
            return

        recent = []
        if self.agent.conversation_db:
            rows = self.agent.conversation_db.get_recent(10, session_id=self.session_id)
            recent = [{"role": r.get("role", ""), "content": r.get("content", "")} for r in rows]

        si.perception.recent_conversations = recent[-10:] if len(recent) > 10 else recent


    # ── ActionDispatcher 通知 ────────────────────────────────

    def _print_notification(self, content: str) -> None:
        """打印通知到 CLI 状态栏"""
        print(f"\n\033[33m[通知] {content}\033[0m", flush=True)

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

        # /intask /inchat 委托给 TaskOrchestrator
        if cmd in ("intask", "inchat"):
            if self.task_orchestrator.handle_command(cmd, cmd_args):
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

        # 用户活跃：满足连接感，归属欲 -0.1，催产素 +0.1
        if self.drive:
            self.drive.on_user_active()

        # 委托给 TaskOrchestrator（"继续"、确认、意图分析、chat）
        self.task_orchestrator.handle_message(msg, self._get_consciousness_state())
        self._print_prompt()

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
            self.consciousness._last_l3_time = time.time()
            # 清理跨会话残留 intent（快照恢复的旧 intent 不应跨会话生效）
            self.consciousness.intent_buffer.clear()
            self.consciousness.intent_slot.intent_buffer.clear()
            self.consciousness.intent_slot.urgent_intents.clear()
            # 调用意识系统的 on_wake，生成问候意图（基于梦境报告）
            logger.info("[ConsciousLiving._on_wake] 调用 consciousness.on_wake()")
            self.consciousness.on_wake()
            # 先更新最近对话（供 ActionDispatcher 生成个性化问候）
            self._update_recent_conversations()
            # 同步状态后，由 ActionDispatcher 统一分发意图
            # Drive/Purpose 已在 SelfImage 构造时连接，无需手动同步
            si = self.consciousness.get_self_image()
            self._dispatcher.tick(si)
            self._dispatcher.process_queue()

        # 苏醒时能量恢复（睡眠恢复）
        if self.drive:
            self.drive.restore_energy(0.15)
            logger.info("[ConsciousLiving._on_wake] 苏醒能量恢复: %.2f", self.drive.energy.level)

        # 火焰点燃（如果意识系统已加载）
        if self._load_consciousness:
            si = self.consciousness.get_self_image()
            si.perception.last_user_activity_time = time.time()

        # 加载 fresh tail：让 agent "带着最近的记忆醒来"
        # 从 DB 还原完整的消息序列，包括 assistant(tool_calls) + tool 配对
        if self.agent.conversation_db and self.agent.context_assembler:
            agent = self.agent._get_agent()
            recent = self.agent.conversation_db.get_recent(
                self._config.context.fresh_tail_count,
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
            # 同时复制 DB id（DAG 压缩需要，用于 filter_compressed_messages 匹配）
            restored: list[dict] = []
            for m in recent:
                role = m.get("role", "user")
                db_id = m.get("id")  # SQLite row id
                if role == "user":
                    msg = {"role": "user", "content": m.get("content", "")}
                    if db_id is not None:
                        msg["id"] = db_id
                    restored.append(msg)
                elif role == "assistant":
                    msg: dict[str, Any] = {"role": "assistant", "content": m.get("content", "")}
                    if db_id is not None:
                        msg["id"] = db_id
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
                        msg = {
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": m.get("content", ""),
                        }
                        if db_id is not None:
                            msg["id"] = db_id
                        restored.append(msg)

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

    def _on_wake_up(self) -> None:
        """从 IDLE 收到消息唤醒，直接切 AWAKE 处理。

        idle 不是睡眠/梦境状态，不需要调 consciousness.on_wake()。
        on_wake() 只用于 DORMANT→AWAKE（启动）和 SLEEPING→AWAKE（睡眠醒来）。
        """
        logger.info("[ConsciousLiving] Waking up — message received!")
        self._transition(LivingState.AWAKE)

    def _on_stop(self) -> None:
        """停止时保存 Drive 和 Purpose 状态。"""
        if self.drive:
            self.drive.save()
        if self.purpose:
            self.purpose.save()

    # ── Proactive output ─────────────────────────────────────────

    def _send_proactive(self, content: str) -> None:
        """发送主动消息"""
        logger.info("[ConsciousLiving/Proactive] %s", content)

        if self.agent.conversation_db:
            try:
                self.agent.conversation_db.log(
                    session_id=self.session_id,
                    role="assistant",
                    content=content,
                )
            except Exception:
                pass

        if self.on_proactive:
            self.on_proactive(content)
        else:
            # CLI 模式：直接打印
            print(f"\n\033[36m[小美] {content}\033[0m", flush=True)
            self._print_prompt()