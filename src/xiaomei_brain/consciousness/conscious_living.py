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
    agent = manager.build_agent(agent_id)

    living = ConsciousLiving(agent)
    living.put_message("你好")
    living.run()  # blocking
"""

from __future__ import annotations

import logging
import os
import re
from collections import deque
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
from .perception import PerceptionConfig
from ..drive import DriveEngine
from ..purpose import PurposeEngine, IntentUnderstanding
from .task_orchestrator import TaskOrchestrator
from .layer0 import Layer0Autonomous
from .layer2 import Layer2DefaultNetwork
from .attention_layer import AttentionLayer
from ..gateway.router import Router, InboundMsg, OutputRoute
from ..plugin import boot_plugins

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
        self._agent_id = getattr(agent_instance, "id", None) or getattr(agent_instance, "agent_id", "")

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

        # CronScheduler（闹钟系统）
        from ..schedule import CronScheduler
        self.cron_scheduler = CronScheduler(self._agent_id)

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

        # ── [Layer 3] InnerVoice: 统一内心声音 ──
        from ..metacognition.inner_voice import InnerVoice
        self._inner_voice = InnerVoice(
            llm=llm_client,
            self_image=None,  # 延迟设置（consciousness 创建后）
            drive=self.drive,
            purpose=self.purpose,
        )

        # ── [Layer 2] Experience Memory: 经验记忆 ──
        from ..memory.experience import ExperienceMemory
        ltm = getattr(agent_instance, 'longterm_memory', None)
        self._experience_memory = ExperienceMemory(ltm) if ltm else None

        # ── [Layer 2] Project Mental Model: 项目地图 ──
        from ..metacognition.project_mental_model import ProjectMentalModel
        self._project_mental_model = ProjectMentalModel(dag=None)

        # TaskOrchestrator: 任务 orchestration（意图分析、任务创建/路由、确认、chat）
        self.task_orchestrator = TaskOrchestrator(
            parent=self,
            purpose=self.purpose,
            drive=self.drive,
            agent=agent_instance,
            intent_understanding=self.intent_understanding,
            config=self._config,
            on_confirm_required=self.on_confirm_required,
            inner_voice=self._inner_voice,
            experience_memory=self._experience_memory,
            project_mental_model=self._project_mental_model,
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
            cron_scheduler=self.cron_scheduler,
        )
        self._load_consciousness = load_consciousness

        # InnerVoice → SelfImage 连接（延迟设置）
        si = self.consciousness.self_image
        if self._inner_voice:
            self._inner_voice._self_image = si
        # ProjectMentalModel / ExperienceMemory → SelfImage
        si._project_mental_model = self._project_mental_model
        si._experience_memory = self._experience_memory

        # ── 经验流（统一时间线）──────────────────────────────
        db_path = getattr(self.agent, "db_path", None)
        if db_path is None:
            db_path = os.path.expanduser(
                f"~/.xiaomei-brain/{self._agent_id}/memory/brain.db"
            )
        from ..memory.experience_stream import ExperienceStream
        exp_stream = ExperienceStream(db_path)
        # 注入到各子系统
        self.drive.exp_stream = exp_stream
        self.consciousness.exp_stream = exp_stream
        # 注入到 AgentInstance（供 l2_engine 等访问）
        self.agent.exp_stream = exp_stream
        # 注入到 Agent 核心（供 core.py stream/react_nodb 使用）
        agent_core = self.agent._get_agent()
        agent_core.exp_stream = exp_stream
        logger.info("[ConsciousLiving] 经验流已创建并注入")

        # ── 底色（Essence）—— 由 agent_manager.init_agent() 创建 ──
        essence = getattr(self.agent, '_essence', None)
        if essence is not None:
            self.consciousness.essence = essence
            agent_core.essence = essence
            logger.info("[ConsciousLiving] Essence 已关联 (%d 条底色)", essence.count())
            if self._load_consciousness:
                self.consciousness.self_image._essence = essence
        else:
            logger.warning("[ConsciousLiving] Essence 未找到，底色功能禁用")

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

        # 调试日志目录 + 提前建文件（方便 tail -f）
        _agent_home = os.path.expanduser(f"~/.xiaomei-brain/{self._agent_id}")
        self._debug_dir = os.path.join(_agent_home, "debug")
        os.makedirs(self._debug_dir, exist_ok=True)
        for _df in ("layer0.log", "layer2.log", "living.log", "comms.log"):
            _p = os.path.join(self._debug_dir, _df)
            if not os.path.exists(_p):
                with open(_p, "w") as _f:
                    _f.write("")

        # Layer 0：自主层线程（火焰骨架 + Drive 衰减 + 异常检测）
        self._layer0 = Layer0Autonomous(
            consciousness=self.consciousness,
            drive=self.drive,
            tick_interval=1.0,
            debug_file=os.path.join(self._debug_dir, "layer0.log"),
        )
        logger.info("[ConsciousLiving] Layer0 已创建")

        # Layer 2：默认网络线程（L2 加柴 + L3 沉思 + 入梦信号）
        self._layer2 = Layer2DefaultNetwork(
            consciousness=self.consciousness,
            check_interval=self._config.consciousness.l2_check_interval,
            debug_file=os.path.join(self._debug_dir, "layer2.log"),
        )
        logger.info("[ConsciousLiving] Layer2 已创建")

        # Layer 1：注意层（会话管理——保存/恢复/切换）
        agent_core = self.agent._get_agent()
        self._attention = AttentionLayer(agent_core)
        logger.info("[ConsciousLiving] AttentionLayer 已创建")

        # Router：消息路由 + 输出分发
        self._router = Router()

        # 启动插件系统，加载频道适配器
        self._boot_plugins()
        for name in self._registry.list_channels():
            adapter = self._registry.get_channel(name)
            if adapter:
                self._router.register_adapter(name, adapter)

        self._router.register_peer(
            peer_type="human", peer_id="*", channel="cli",
            session_id="main", output_type="cli", output_target="stdout",
        )
        logger.info("[ConsciousLiving] Router 已创建 (%d 个频道)", len(self._registry.list_channels()))

        # 注入 consciousness 层上下文组装器（子系统加载后再替换旧 assembler）
        self._inject_context_assembler()

        # 初始化过程记忆（ProcedureMemory — LLM学习 + 关键词触发）
        db_path = getattr(self.agent, "db_path", None)
        if db_path is None:
            db_path = os.path.expanduser(f"~/.xiaomei-brain/{self._agent_id}/memory/brain.db")
        self.consciousness.init_procedure_memory(db_path)

        # ActionDispatcher 初始化（接入外部引用）
        from .rules import _init_rules, RULES
        drive_config = getattr(self.drive, 'config', None)
        _init_rules(drive_config=drive_config, living_config=self._config)
        self._dispatcher.load_rules(RULES)
        self._dispatcher.inject_conscious_living(self)

        # being 工具暂不注册（待反省层"转换器"设计确定后再启用）

        # 注册 cron 工具（闹钟系统：schedule_alarm / list_alarms / cancel_alarm）
        self._register_cron_tools()

        # 注册 session 管理工具（manage_session：list / switch / new）
        self._register_session_tools()

        # 记录初始化摘要
        self._log_initialization()

        # TUI 日志缓冲区
        self._log_buffer: deque[str] = deque(maxlen=200)       # Living 线程日志
        self._comms_log: deque[str] = deque(maxlen=200)         # Comms 线程日志

        # 调试日志文件路径
        self._debug_living_file = os.path.join(self._debug_dir, "living.log")
        self._debug_comms_file = os.path.join(self._debug_dir, "comms.log")

        # Agent 间通讯
        self._setup_comms(db_path)

        # 注册周期任务
        self.register_periodic("heartbeat", self._config.living.tick_interval, self._heartbeat)
        self.register_periodic("surge", self._config.living.surge_interval, self._surge)

        # 启动 Layer 0 自主层线程 + Layer 2 默认网络线程
        if self._load_consciousness:
            self._layer0.start()
            self._layer2.start()

    def _register_being_tool(self) -> None:
        """注册 being 工具：将 L2 内心觉察暴露为对话中可调用的工具。

        当 LLM 在对话中被用户触动时，可以主动调用 being() 来感受自己的内心，
        而不是等待周期性的 L2 触发。这让情绪反应变得即时。
        """
        try:
            from ..tools.builtin.being import create_being_tool
            being_tool = create_being_tool(self.consciousness)
            if hasattr(self.agent, "tools") and self.agent.tools:
                self.agent.tools.register(being_tool)
                logger.info("[ConsciousLiving] being 工具已注册")
            else:
                logger.warning("[ConsciousLiving] agent.tools 不可用，being 工具未注册")
        except Exception as e:
            logger.warning("[ConsciousLiving] being 工具注册失败: %s", e)

    def _register_cron_tools(self) -> None:
        """注册闹钟工具：schedule_alarm / list_alarms / cancel_alarm。"""
        try:
            from ..schedule import create_cron_tools
            for cron_tool in create_cron_tools(self.cron_scheduler):
                if hasattr(self.agent, "tools") and self.agent.tools:
                    self.agent.tools.register(cron_tool)
            logger.info("[ConsciousLiving] cron 工具已注册")
        except Exception as e:
            logger.warning("[ConsciousLiving] cron 工具注册失败: %s", e)

    def _register_session_tools(self) -> None:
        """注册会话管理工具：manage_session（list / switch / new）。"""
        try:
            from ..tools.builtin.manage_session import set_context, manage_session_tool
            set_context(self.agent, self)
            if hasattr(self.agent, "tools") and self.agent.tools:
                self.agent.tools.register(manage_session_tool)
                logger.info("[ConsciousLiving] manage_session 工具已注册")
        except Exception as e:
            logger.warning("[ConsciousLiving] manage_session 工具注册失败: %s", e)

    def _check_round_alarms(self) -> None:
        """对话轮次完成后检查轮次闹钟。"""
        due = self.cron_scheduler.on_round_complete()
        if not due:
            return
        from .intent import Intent, IntentType
        for job in due:
            intent = Intent(
                type=IntentType.ALARM,
                priority=85,
                content=f"闹钟「{job.name}」响了。{job.action_hint or job.reason}",
            )
            self.consciousness.intent_buffer.append(intent)
            if self.consciousness.self_image is not None:
                self.consciousness.intent_slot.intent_buffer.append({
                    "type": intent.type.value,
                    "reason": getattr(intent, "reason", ""),
                    "priority": getattr(intent, "priority", 0),
                })
            logger.info("[ConsciousLiving] 轮次闹钟触发: %s (每%d轮)", job.name, job.round_interval)

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
            logger.info("      age           : %ds", int(si.history.consciousness_age))
            logger.info("      idle_duration : %ds", int(si.perception.user_idle_duration))
            logger.info("")
            logger.info("    身份信息:")
            identity_name = si.being.name
            logger.info("      identity      : %s", identity_name)
            logger.info("      birth_date    : %s", si.being.birth_date)
            logger.info("      personality   : %s", si.being.personality)

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
            self_model=getattr(self.agent, "self_model", None),
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
            # restore 可能替换了 SelfImage，重新绑定引用
            si = self.consciousness.self_image
            if self._inner_voice:
                self._inner_voice._self_image = si
            si._project_mental_model = self._project_mental_model
            si._experience_memory = self._experience_memory
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

        # 4. 从 talent.md 加载身份字段（L0-L3 + 追求/热爱/底线/自我认知）
        import os
        talent_path = os.path.expanduser(f"~/.xiaomei-brain/{self._agent_id}/talent.md")
        with open(talent_path, "r", encoding="utf-8") as f:
            self.consciousness.being.init_from_talent_md(f.read())
        logger.info("[ConsciousLiving] 从 talent.md 初始化身份")

        # 如果还是没有数据，使用默认值
        si = self.consciousness.get_self_image()
        if not si.being.name:
            si.being.name = self._agent_id
            logger.info("[ConsciousLiving] 使用 agent_id 作为默认名字")

        # 5. 加载感知规则（非运行时数据，始终从配置加载）
        self.consciousness._perception_config = PerceptionConfig.load(self._agent_id)
        logger.info("[ConsciousLiving] 从 PerceptionConfig 初始化完成: %d 条规则", len(self.consciousness._perception_config.rules))

    # ── 插件系统 ────────────────────────────────────────────────────

    def _boot_plugins(self) -> None:
        """启动插件系统：一行调用，自动发现 + 加载所有插件。"""
        self._registry = boot_plugins(agent_id=self._agent_id)

    # ── Agent 间通讯 ───────────────────────────────────────────────

    def _setup_comms(self, db_path: str) -> None:
        """初始化通讯层：各通道适配器自行启动 + WS Gateway + 工具上下文。"""
        host = "0.0.0.0"

        # 默认值（P2P 适配器 setup 会覆盖）
        self._inbox = None
        self._directory = None
        self._comms_thread = None
        self._comms_server = None

        # ── 各通道适配器 Post-load 初始化 ──────────────────
        for name in self._registry.list_channels():
            adapter = self._registry.get_channel(name)
            if adapter and hasattr(adapter, "setup"):
                try:
                    adapter.setup(living=self)
                except Exception as e:
                    logger.error("[ConsciousLiving] %s adapter setup 失败: %s", name, e)

        # 更新 send_message 工具的上下文
        try:
            from xiaomei_brain.tools.builtin.send_message import set_context
            set_context(self._agent_id, self._directory, self._inbox, router=self._router)
        except Exception:
            pass

        # ── WS Gateway（Web UI 入口）──────────────────────────
        self._ws_thread = None
        self._ws_server = None
        ws_port = self._config.living.ws_port
        if ws_port > 0:
            from ..server.ws.server import create_app
            import uvicorn
            ws_app = create_app(
                router=self._router,
                living=self,
                config=self._config,
            )
            ws_config = uvicorn.Config(ws_app, host=host, port=ws_port, log_level="warning")
            self._ws_server = uvicorn.Server(ws_config)
            self._ws_thread = threading.Thread(
                target=self._ws_server.run,
                daemon=True,
                name="ws-gateway",
            )
            self._ws_thread.start()
            logger.info("[ConsciousLiving] WS Gateway 已启动: ws://%s:%d/ws", host, ws_port)

    @staticmethod
    def _run_ws_gateway(app, host: str, port: int) -> None:
        """在独立线程中运行 uvicorn WS Gateway。"""
        import uvicorn
        uvicorn.run(app, host=host, port=port, log_level="warning")

    def _check_inbox(self) -> None:
        """检查收件箱（兜底：处理回调遗漏的消息）。

        on_receive 回调已在实时处理大多数消息。
        这里只处理遗漏的（如启动前/关闭期间收到的）。
        注入消息原文（而非 [系统通知]），让 LLM 直接处理。
        """
        count = self._inbox.count_unprocessed()
        if count == 0:
            return

        if self._chatting:
            logger.info(
                "[Comms/Inbox] 收件箱有 %d 条未读消息（聊天中，下轮检查）", count,
            )
            return

        unprocessed = self._inbox.get_unprocessed(limit=50)
        for msg in unprocessed:
            session_id = f"comms-{msg.from_agent}"

            # 先用 comms-{agent_id} 作为 session_id
            session_id = f"comms-{msg.from_agent}"

            # 注册 peer（如果尚未注册）—— 必须先注册再路由
            if hasattr(self, '_router') and self._router:
                existing = self._router.route_for_session(session_id)
                if existing is None or existing.type != "http_p2p":
                    self._router.register_peer(
                        peer_type="agent", peer_id=msg.from_agent,
                        channel="http_p2p", session_id=session_id,
                        output_type="http_p2p", output_target=msg.from_agent,
                        priority=10,
                    )

            logger.info(
                "[Comms/Inbox] %s: 1 条未读消息 → %s 会话（兜底）",
                msg.from_agent, session_id,
            )
            self.put_message(
                f"[来自 {msg.from_agent}] ({msg.type.value})\n{msg.content}",
                source="agent",
                session_id=session_id,
            )
            self._inbox.mark_processed(msg.msg_id)

    def _on_comms_receive(self, msg) -> None:
        """HTTP 回调：收到 agent 消息 → 注册 peer → 直接注入 Layer 1 队列。

        在 HTTP server 线程中调用，需线程安全。
        """
        session_id = f"comms-{msg.from_agent}"

        # 先注册 peer（确保 Router 能匹配到），再放入队列
        existing = self._router.route_for_session(session_id)
        if existing is None:
            self._router.register_peer(
                peer_type="agent", peer_id=msg.from_agent,
                channel="http_p2p", session_id=session_id,
                output_type="http_p2p", output_target=msg.from_agent,
                priority=10,
            )

        self.put_message(
            f"[来自 {msg.from_agent}] ({msg.type.value})\n{msg.content}",
            source="agent", session_id=session_id,
        )
        self._inbox.mark_processed(msg.msg_id)
        ts = time.strftime("%H:%M:%S")
        self._debug_log("comms", f"{ts} ← {msg.from_agent}: {msg.content[:80]}")
        logger.info(
            "[Comms/Receive] %s → %s 会话 (实时)",
            msg.from_agent, session_id,
        )

    def _handle_comms_message(self, msg: LivingMessage) -> None:
        """处理 agent 间通讯消息：静默 ReAct → Router.deliver() 自动送达。

        LLM 不知道消息怎么送达的，它只是在跟当前 session 的人说话。
        """
        target_agent = msg.session_id.replace("comms-", "")
        self._chatting = True
        try:
            agent_core = self.agent._get_agent()

            system_prompt = self._build_comms_system_prompt(target_agent)
            assembled = [{"role": "system", "content": system_prompt}]
            if msg.content:
                assembled.append({"role": "user", "content": msg.content})

            # 静默 ReAct
            chunks: list[str] = []
            for chunk in agent_core.stream(messages=assembled):
                chunks.append(chunk)
            text = "".join(chunks)

            # Router.deliver() 自动送达
            if text.strip():
                route = self._router.route_for_session(msg.session_id)
                if route:
                    self._router.deliver(re.sub(r'\x1b\[[0-9;]*m', '', text), route)
                    ts = time.strftime("%H:%M:%S")
                    self._debug_log("comms", f"{ts} → {target_agent}: {text[:80]}")
                    logger.info(
                        "[Comms] 自动回复 %s: %s",
                        target_agent, text[:80],
                    )
                else:
                    logger.warning("[Comms] 无输出路由: %s", msg.session_id)
            else:
                logger.info("[Comms] %s 消息无需回复", target_agent)
        except Exception as e:
            logger.error("[Comms] 处理失败: %s", e)
        finally:
            self._chatting = False

    def _build_comms_system_prompt(self, target_agent: str) -> str:
        """构建 agent 间通讯的 system prompt。

        LLM 被告知正在和另一个 agent 对话，
        只需自然地说话，系统会自动把回复送达给对方。
        """
        si = self.consciousness.get_self_image() if self._load_consciousness else None
        identity = si.inject_consciousness() if si else f"你是 {self._agent_id}。"

        return (
            f"{identity}\n\n"
            f"## 当前对话对象\n"
            f"你现在正在和 **{target_agent}**（另一个 AI agent）对话。\n"
            f"你收到的消息已显示在下方。\n\n"
            f"## 重要规则\n"
            f"1. 你的文字回复会**自动送达**给 {target_agent}，你不需要使用 send_message 工具\n"
            f"2. **不要生成旁白或描述性文字**（如'收到消息'、'让我回复他'等）——直接说话\n"
            f"3. 就像和一个人面对面聊天一样自然\n"
            f"4. 如果消息不需要回复，可以不说话（但正常的问候和问题应该回应）\n"
            f"5. 你可以使用 check_inbox 查看是否有更多消息，但不要用 send_message"
        )

    # ── Hook: 状态转换 ───────────────────────────────────────────

    def _on_transition(self, old: LivingState, new_state: LivingState) -> None:
        """状态转换后同步更新意识系统的 agent_state。"""
        if self._load_consciousness:
            si = self.consciousness.get_self_image()
            si.perception.agent_state = new_state.value

    # ── Hook: 心跳 ───────────────────────────────────────────────

    def _heartbeat(self, state: LivingState) -> None:
        """每 tick 调用（1秒一次）。

        L0 由 Layer0 线程独立维护，L2/L3/DREAM 由 Layer2 线程独立调度。
        此处只同步 agent_state 给 Layer 2 并检查入梦信号。
        """
        if not self._load_consciousness:
            return

        # 同步状态给 Layer 2 线程
        self.consciousness._agent_state = state.value

        # 检查 Layer 2 发出的入梦信号
        if getattr(self.consciousness, '_dream_signal', False):
            self.consciousness._dream_signal = False
            ts = time.strftime("%H:%M:%S")
            self._debug_log("living", f"{ts} Living 收到入梦信号 → HEARTBEAT_DREAM")
            if state == LivingState.SLEEPING:
                self._heartbeat_result = HEARTBEAT_DREAM

    def _surge(self, state: LivingState) -> None:
        """每分钟调用。ActionDispatcher 统一检查主动行为。"""
        ts = time.strftime("%H:%M:%S")
        self._debug_log("living", f"{ts} surge 涌动 state={state.value}")
        self._check_inbox()
        if self._load_consciousness:
            si = self.consciousness.get_self_image()
            self._dispatcher.tick(si)
            queue_size = len(self._dispatcher._queue)
            if queue_size > 0:
                actions = [f"{a.action_type.value}({a.priority:.1f})" for a in self._dispatcher._queue]
                self._debug_log("living", f"{ts} ActionDispatcher 匹配 {queue_size} 个动作: {', '.join(actions)}")
            else:
                self._debug_log("living", f"{ts} ActionDispatcher 无匹配动作")
            self._dispatcher.process_queue()

    def _debug_log(self, thread: str, line: str) -> None:
        """写入内存缓冲区和调试文件。thread: living | comms"""
        if thread == "living":
            self._log_buffer.append(line)
            debug_file = getattr(self, '_debug_living_file', None)
        else:
            self._comms_log.append(line)
            debug_file = getattr(self, '_debug_comms_file', None)
        if debug_file:
            try:
                with open(debug_file, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception as ex:
                logger.warning("[%s] 写调试日志失败: %s", thread, ex)

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
            self._debug_log("living", f"{time.strftime('%H:%M:%S')} 消息 (忽略，chatting): {msg.content[:30]}")
            logger.info("[ConsciousLiving] 聊天进行中，忽略新消息: %s", msg.content[:30])
            return

        logger.info("[ConsciousLiving] 收到消息: %s [session=%s]", msg.content[:50], msg.session_id)

        # Agent 间通讯会话：静默 ReAct → Router.deliver() 自动送达
        if msg.session_id.startswith("comms-"):
            self._debug_log("living",
                f"{time.strftime('%H:%M:%S')} 收到 agent 消息 [{msg.session_id}]: {msg.content[:60]}"
            )
            self._handle_comms_message(msg)
            return

        # 飞书会话
        if msg.session_id.startswith("feishu-"):
            logger.info("[Feishu/Step5] _handle_message 收到 feishu 会话消息 (session=%s)", msg.session_id)

        # 切换到消息所属的会话（保存当前 → 恢复目标）
        if hasattr(self, '_attention') and self._attention:
            self._attention.switch_to(msg.session_id)

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

        # 轮次完成：检查轮次闹钟
        if self.cron_scheduler:
            self._check_round_alarms()

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

        # 启动时自动创建新会话
        new_sid = f"s_{int(time.time())}"
        logger.info("[ConsciousLiving._on_wake] 创建新会话: %s → %s", self.session_id, new_sid)
        self.session_id = new_sid
        # 通过 AttentionLayer 保存旧会话并开始新会话
        if hasattr(self, '_attention') and self._attention:
            self._attention.new_session(new_sid)

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

            # 第五遍：过滤主动输出（没有前置 user 消息的孤立 assistant）
            # 主动输出通过 _send_proactive() 写入了 conversation_db，恢复时不应进入对话上下文
            filtered = []
            prev_role = None
            for m in cleaned:
                role = m.get("role", "")
                if role == "assistant" and not m.get("tool_calls"):
                    # 前一消息不是 user → 这是主动输出，跳过
                    if prev_role != "user":
                        continue
                filtered.append(m)
                prev_role = role
            if len(filtered) < len(cleaned):
                logger.info(
                    "[ConsciousLiving] 过滤 %d 条主动输出消息",
                    len(cleaned) - len(filtered),
                )

            agent.messages = filtered
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
        """停止时保存状态并关闭通讯服务。"""
        # 保存当前会话
        attention = getattr(self, '_attention', None)
        if attention:
            attention.save_session()

        # 停止 Layer 0 / Layer 2 线程
        layer0 = getattr(self, '_layer0', None)
        if layer0:
            layer0.stop()
        layer2 = getattr(self, '_layer2', None)
        if layer2:
            layer2.stop()

        # 关闭所有通道适配器
        for name in self._registry.list_channels():
            adapter = self._registry.get_channel(name)
            if adapter and hasattr(adapter, "shutdown"):
                try:
                    adapter.shutdown()
                except Exception as e:
                    logger.warning("[ConsciousLiving] 关闭通道 %s 失败: %s", name, e)

        # 关闭 WS Gateway
        ws_server = getattr(self, '_ws_server', None)
        if ws_server is not None:
            try:
                ws_server.should_exit = True
                logger.info("[ConsciousLiving] WS Gateway 已请求关闭")
            except Exception as e:
                logger.warning("[ConsciousLiving] 关闭 WS Gateway 失败: %s", e)

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
        elif hasattr(self, '_router') and self._router:
            # 通过 Router 分发到当前会话的输出路由
            route = self._router.route_for_session(self.session_id)
            if route:
                self._router.deliver(re.sub(r'\x1b\[[0-9;]*m', '', content), route)
            else:
                # 兜底：CLI 模式直接打印
                print(f"\n\033[36m[{self.agent.name or self._agent_id}] {content}\033[0m", flush=True)
        else:
            # CLI 模式：直接打印
            print(f"\n\033[36m[{self.agent.name or self._agent_id}] {content}\033[0m", flush=True)
            self._print_prompt()