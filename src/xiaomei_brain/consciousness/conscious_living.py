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
from .core import Consciousness, ConsciousnessReport
from .intent import Intent
from .storage import ConsciousnessStorage
from .self_image_proxy import SelfImage

from ..drive import DriveEngine
from ..purpose import PurposeEngine, IntentUnderstanding
from .conversation_driver import ConversationDriver
from .message_gateway import MessageGateway
from .agent_comms import AgentComms
from .layer0 import Layer0Autonomous
from .layer2 import Layer2DefaultNetwork
from .attention_layer import AttentionLayer
from ..llm.client import FatalLLMError
from ..gateway.router import Router, InboundMsg, OutputRoute
from ..plugin import boot_plugins
from ..cli.boot import boot_section, boot_line

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
        # 解析 agent_id（统一来源）
        self._agent_id = getattr(agent_instance, "id", None) or getattr(agent_instance, "agent_id", "")

        # 读取统一配置
        from ..config import load_agent_config
        agent_cfg = load_agent_config(self._agent_id)
        self._config = config or agent_cfg.consciousness
        self._drive_config = agent_cfg.drive

        boot_section("记忆系统")
        boot_line("加载配置", "OK")

        super().__init__(
            agent_instance=agent_instance,
            idle_threshold=idle_threshold or self._config.living.idle_threshold,
            dream_interval=dream_interval or self._config.living.dream_interval,
            idle_short=idle_short or self._config.living.idle_short,
            session_id=session_id,
            user_id=user_id,
            tick_interval=tick_interval or self._config.living.tick_interval,
        )

        # 自主行为计时器（独立于 _last_active，不干扰空闲检测）
        self._last_autonomous: float = 0

        # 包装 LLM 客户端：自动控制上下文总 token 量
        from ..agent.context_guard import ContextGuard
        if not isinstance(self.agent.llm, ContextGuard):
            self.agent.llm = ContextGuard(self.agent.llm, max_tokens=80000)

        # ── 记忆系统初始化 ───────────────────────────────────────────
        db_path = os.path.expanduser(
            f"~/.xiaomei-brain/{self._agent_id}/memory/brain.db"
        )

        # SelfModel 加载（从 identity.md）
        identity_path = os.path.expanduser(
            f"~/.xiaomei-brain/{self._agent_id}/identity.md"
        )
        if os.path.exists(identity_path):
            from ..memory.self_model import SelfModel
            self_model = SelfModel.load(identity_path)
            if self_model and (self_model.purpose_seed.identity or self_model.seed_text):
                self.agent.self_model = self_model
                boot_line("SelfModel (身份种子)", "OK", "1 条身份")
            else:
                boot_line("SelfModel (身份种子)", "WARN", "未能加载")
        else:
            boot_line("SelfModel (身份种子)", "WARN", "identity.md 不存在")

        # ConversationDB（SQLite, 原始消息一字不差）
        from ..memory.conversation_db import ConversationDB
        self.agent.conversation_db = ConversationDB(db_path)
        boot_line("ConversationDB", "OK")

        # 获取底层 LLMClient（穿透 ContextGuard）
        _llm = self.agent.llm
        if hasattr(_llm, '_llm'):
            _llm = _llm._llm

        # DAG 摘要图 + LongTermMemory
        from ..memory.dag import DAGSummaryGraph
        from ..memory.longterm import LongTermMemory
        dag = DAGSummaryGraph.for_agent(self._agent_id, llm_client=_llm)
        self.agent.longterm_memory = LongTermMemory(db_path)
        self.agent.dag = dag
        boot_line("摘要图谱 (DAG)", "OK")
        ltm_count = self.agent.longterm_memory.count() if hasattr(self.agent.longterm_memory, 'count') else 0
        boot_line("长期记忆", "OK", f"{ltm_count} 条" if ltm_count else "")

        # ProcedureMemory（过程记忆：学习 + 关键词触发）
        from ..memory.procedure import ProcedureMemory
        self.agent._procedure_memory = ProcedureMemory(db_path, llm_client=_llm)
        boot_line("过程记忆 (ProcedureMemory)", "OK")

        # Essence（底色存储：不可变身份片段）
        from ..consciousness.essence import Essence
        self.agent._essence = Essence(db_path)

        # MemoryExtractor（需要 dag + longterm_memory）
        from ..memory.extractor import MemoryExtractor
        self.agent.memory_extractor = MemoryExtractor(
            llm_client=_llm,
            longterm_memory=self.agent.longterm_memory,
            conversation_db=self.agent.conversation_db,
        )

        # 注册 DAG 工具（含 extinct 记忆搜索和唤醒）
        from ..tools.builtin.dag_expand import create_dag_tools
        for dag_tool in create_dag_tools(dag, self.agent.longterm_memory):
            self.agent.tools.register(dag_tool)

        # 注册见证层工具（搜索历史念头）
        from ..tools.builtin.thought_search import create_thought_tools
        for thought_tool in create_thought_tools(self.agent.longterm_memory):
            self.agent.tools.register(thought_tool)

        # 注册记忆搜索工具（"想一想" — 扩散激活）
        from ..tools.builtin.memory_search import create_memory_search_tools
        for ms_tool in create_memory_search_tools(self.agent.longterm_memory):
            self.agent.tools.register(ms_tool)

        # 注册目标管理工具（create_goal / list_goals / resume_goal）
        # purpose_ref 延迟绑定：PurposeEngine 创建后设置
        # resume_trigger: resume_goal 设置 goal_id → ConversationDriver 检测后启动 PACE
        from ..tools.builtin.goal import create_goal_tools
        purpose_ref = [None]
        resume_trigger = [None]
        for goal_tool in create_goal_tools(purpose_ref, resume_trigger):
            self.agent.tools.register(goal_tool)
        self.agent._purpose_ref = purpose_ref
        self.agent._resume_trigger = resume_trigger

        # MemoryConsole
        from ..agent.commands import MemoryConsole
        self.agent.commands = MemoryConsole(
            conversation_db=self.agent.conversation_db,
            dag=dag,
            longterm_memory=self.agent.longterm_memory,
            memory_extractor=self.agent.memory_extractor,
            agent_instance=self.agent,
        )
        if hasattr(self, '_gateway_inbound'):
            self._gateway_inbound.set_agent_commands(self.agent.commands)

        # Per-agent 输出目录隔离
        agent_base_dir = os.path.expanduser(f"~/.xiaomei-brain/{self._agent_id}")
        from ..tools.builtin import file_ops
        file_ops.set_output_base(agent_base_dir)

        boot_line("记忆提取器", "OK")

        boot_section("驱动与目的")

        # Drive 系统（边缘系统）- 延迟加载
        self.drive = DriveEngine(self._agent_id, load=False, config=self._drive_config)
        boot_line("Drive 边缘系统", "OK")

        # 设置 Token 预算（从 LivingParams 读取）
        self.drive.token_budget_daily = float(self._config.living.daily_token_budget)
        self.drive.token_budget_monthly = float(self._config.living.monthly_token_budget)
        self.drive.token_reset_hour = int(self._config.living.daily_token_reset_hour)

        # 注入 Token 回调到 LLM 客户端（穿透 ContextGuard）
        llm = self.agent.llm
        if hasattr(llm, '_llm'):
            llm._llm._token_callback = self.drive.record_token_usage
        else:
            llm._token_callback = self.drive.record_token_usage

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
            essence=self.agent._essence,
        )
        boot_line("Purpose 前额叶", "OK")

        # 绑定 purpose_ref，使 goal 工具可用
        pr = getattr(agent_instance, '_purpose_ref', None)
        if pr:
            pr[0] = self.purpose

        # Intent Understanding
        self.intent_understanding = IntentUnderstanding(llm_client)

        # ── [Layer 3] InnerVoice: 统一内心声音 ──
        from ..metacognition.inner_voice import InnerVoice
        self._inner_voice = InnerVoice(
            llm=llm_client,
            self_image=None,  # 延迟设置（consciousness 创建后）
            drive=self.drive,
            purpose=self.purpose,
            exp_stream=getattr(agent_instance, "exp_stream", None),
            longterm_memory=getattr(agent_instance, "longterm_memory", None),
            user_id=user_id,
        )

        # ── SocialCognition: 社会认知引擎 ──
        from ..metacognition.social_cognition import SocialCognition
        self._social_cognition = SocialCognition(
            llm=llm_client,
            self_image=None,  # 延迟设置（consciousness 创建后）
            drive=self.drive,
            exp_stream=getattr(agent_instance, "exp_stream", None),
            longterm_memory=getattr(agent_instance, "longterm_memory", None),
            user_id=user_id,
        )

        # ── [Layer 2] Experience Memory: 经验记忆 ──
        from ..memory.experience import ExperienceMemory
        ltm = getattr(agent_instance, 'longterm_memory', None)
        self._experience_memory = ExperienceMemory(ltm) if ltm else None

        # ── [Layer 2] Project Mental Model: 项目认知地图 ──
        from ..metacognition.project_mental_model import (
            ProjectMentalModel, ProjectMentalModelStorage,
        )
        _pmm_storage = ProjectMentalModelStorage(str(db_path))
        self._project_mental_model = ProjectMentalModel(_pmm_storage, agent_id=self._agent_id)

        # ── GoalRunStorage（统一任务执行持久化）──
        from ..metacognition import GoalRunStorage
        goal_run_storage = GoalRunStorage(db_path)

        # ConversationDriver: 对话驱动（消息路由、ReAct、RoundScheduler 后处理）
        # GoalManager 内嵌其中，负责目标全生命周期（意图分析、PACE 执行、确认）
        self.conversation_driver = ConversationDriver(
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
            goal_run_storage=goal_run_storage,
            resume_trigger=resume_trigger,
            procedure_memory=getattr(self.agent, '_procedure_memory', None),
            longterm_memory=getattr(agent_instance, 'longterm_memory', None),
        )

        # MessageGateway（消息入口预处理：命令检测、身份解析、会话切换）
        self._gateway = MessageGateway()

        # AgentComms（Agent 间通讯：收件箱、消息处理、系统提示词）
        self._comms = AgentComms()

        # ActionDispatcher（统一动作分发）
        self._dispatcher = ActionDispatcher()

        boot_section("意识系统")

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
        self.agent.commands._self_image = self.consciousness.self_image
        boot_line("意识核心", "OK", f"agent={self._agent_id}")

        # ── 内感受（Interoception）—— 身体状态感知 ──
        from .interoception import Interoception
        self.interoception = Interoception(burn_start_time=time.time())
        logger.info("[ConsciousLiving] Interoception 已创建")

        si = self.consciousness.self_image

        # ── 持久化（SelfImageStore 统一入口）────────────────────
        from .queue_storage import TaskQueueStorage
        from .self_image_store import SelfImageStore
        queue_storage = TaskQueueStorage(db_path)
        self.consciousness._store = SelfImageStore(self._agent_id, queue_storage)
        si.intent._storage = queue_storage
        snapshot_exists = self.consciousness._store.snapshot_path.exists()
        logger.info("[ConsciousLiving] SelfImageStore 已创建并注入")
        boot_line("SelfImageStore", "OK", "已恢复" if snapshot_exists else "新创建")

        # ── 关系引擎（RelationshipEngine）─────────────────────
        from .relationship import RelationshipEngine
        self._relationship_engine = RelationshipEngine(db_path, user_id="default")
        self._relationship_engine.load()
        si.being._relationship_engine = self._relationship_engine
        rel_summary = self._relationship_engine.get_summary()
        logger.info("[ConsciousLiving] RelationshipEngine 已创建并注入: %s", rel_summary)
        boot_line("关系引擎", "OK", str(rel_summary))

        # ── 学习子系统 ──────────────────────────────────────
        from ..learn import LearningQueue, KnowledgeStorage, MetaSkillPuller, LearningEngine
        ltm = getattr(agent_instance, "longterm_memory", None)
        agent_id = getattr(agent_instance, "id", "") if agent_instance else self._agent_id
        self._learn_queue = LearningQueue(si, storage=queue_storage)
        self._learn_storage = KnowledgeStorage(agent_id, ltm, queue=self._learn_queue)
        self._learn_meta_skill = MetaSkillPuller(self._learn_storage)
        self._learn_meta_skill._agent = agent_instance
        self._learn_meta_skill._consciousness = self.consciousness
        self._learn_meta_skill._send_proactive = self._send_proactive if hasattr(self, '_send_proactive') else None
        self._learn_engine = LearningEngine(self, self._learn_queue, self._learn_storage, self._learn_meta_skill)

        # InnerVoice → SelfImage 连接
        if self._inner_voice:
            self._inner_voice._self_image = si
            self._inner_voice._learn_queue = self._learn_queue
        # SocialCognition → SelfImage 连接
        if self._social_cognition:
            self._social_cognition._self_image = si
        # 注入到 Consciousness（用于 tick_social_cognition 委托）
        self.consciousness._social_cognition = self._social_cognition
        self._social_cognition._consciousness = self.consciousness
        # ProjectMentalModel / ExperienceMemory / LearningQueue → SelfImage
        si._project_mental_model = self._project_mental_model
        si._experience_memory = self._experience_memory
        si._learn_queue = self._learn_queue

        # LearningQueue → L2Engine（供 LEARN 意图 TOPIC 入队）
        l2_engine = self.consciousness._get_l2_engine()
        l2_engine._learn_queue = self._learn_queue

        # ── 经验流（统一时间线）──────────────────────────────
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
        # 延迟注入：InnerVoice / SocialCognition 在 ExperienceStream 之前创建，需要后置设置
        self._inner_voice._exp_stream = exp_stream
        self._social_cognition._exp_stream = exp_stream
        self.purpose.exp_stream = exp_stream
        exp_count = exp_stream.count()
        logger.info("[ConsciousLiving] 经验流已创建并注入")
        boot_line("经验流", "OK", f"{exp_count} 条" if exp_count else "空")

        # ── 底色（Essence）—— 由 ConsciousLiving.__init__() 创建 ──
        essence = getattr(self.agent, '_essence', None)
        if essence is not None:
            self.consciousness.essence = essence
            agent_core.essence = essence
            _essence_count = essence.count()
            logger.info("[ConsciousLiving] Essence 已关联 (%d 条底色)", _essence_count)
            boot_line("本质底色 (Essence)", "OK", f"{_essence_count} 条底色")
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
            exp_stream=exp_stream,
        )
        has_llm = getattr(self.agent, 'llm', None) is not None
        boot_line("梦境引擎", "OK", "LLM已连接" if has_llm else "LLM缺失")

        # 命令注册表 — 从 living_commands 加载（测试/调试/系统操作）
        from .living_commands import COMMAND_REGISTRY, list_commands as _list_cmds
        self._list_commands = lambda: _list_cmds(self)
        self._intent_commands = {}
        self._commands_taking_args: set = set()
        for name, (handler, takes_args) in COMMAND_REGISTRY.items():
            self._intent_commands[name] = lambda a="", h=handler: h(self, a)
            if takes_args:
                self._commands_taking_args.add(handler)

        # ── 多用户身份管理 ─────────────────────────────────────────
        from xiaomei_brain.contacts.manager import IdentityManager
        import os as _os
        _contacts_dir = _os.path.join(_os.path.expanduser(f"~/.xiaomei-brain/{self._agent_id}"), "contacts")
        self._identity_mgr = IdentityManager(_contacts_dir)
        self.agent._get_agent().identity_mgr = self._identity_mgr
        logger.info("[ConsciousLiving] 身份管理器已初始化")

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

        # Router：消息路由 + 输出分发
        self._router = Router()

        # 启动插件系统，加载频道适配器 + body 器官
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

        # ── Body 身体感官层（Layer0 之前创建，Layer0 需要 body）──
        boot_section("身体与感知")
        from ..body import Body

        self.body = Body()

        # 从插件系统装配器官（body/ 插件已通过 ctx.register_sense() 注册）
        pending = self._registry.get_pending_senses()
        for sense, device in pending:
            self.body.register_sense(sense, device)
            logger.info("[ConsciousLiving] 装配器官: %s → %s",
                        sense.name, device.__class__.__name__)

        # 填充延迟绑定引用，使工具函数能解析到 body/identity_mgr
        from ..plugins.body._refs import body_ref, identity_mgr_ref
        body_ref[0] = self.body
        identity_mgr_ref[0] = self._identity_mgr

        organ_count = len(pending)
        logger.info("[ConsciousLiving] Body 身体感官层已创建（%d 个器官），引用已注入插件",
                    organ_count)
        boot_line("Body 身体感官", "OK", f"{organ_count} 个器官")

        # Layer 0：自主层线程（火焰骨架 + Drive 衰减 + 异常检测 + 内感受 + 身体感官）
        self._layer0 = Layer0Autonomous(
            consciousness=self.consciousness,
            drive=self.drive,
            tick_interval=1.0,
            debug_file=os.path.join(self._debug_dir, "layer0.log"),
            interoception=self.interoception,
            body=self.body,
        )
        logger.info("[ConsciousLiving] Layer0 已创建")
        boot_line("Layer0 自主层", "OK")

        # DMN：默认模式网络线程（L2 加柴 + social_cognition + L3 沉思 + 入梦信号）
        self._layer2 = Layer2DefaultNetwork(
            consciousness=self.consciousness,
            check_interval=self._config.consciousness.l2_check_interval,
            debug_file=os.path.join(self._debug_dir, "layer2.log"),
        )
        logger.info("[ConsciousLiving] Layer2 已创建")
        boot_line("Layer2 默认模式网络", "OK")

        # Layer 1：注意层（会话管理——保存/恢复/切换）
        agent_core = self.agent._get_agent()
        self._attention = AttentionLayer(agent_core)
        logger.info("[ConsciousLiving] AttentionLayer 已创建")
        boot_line("注意层 (AttentionLayer)", "OK")

        # ── Gateway 入站门 ──────────────────────────────────────────
        boot_section("通讯层")
        from ..gateway import Gateway
        self._gateway_inbound = Gateway(living=self, router=self._router, config=self._config)
        self._gateway_inbound.set_identity_mgr(self._identity_mgr)
        if self.agent.commands:
            self._gateway_inbound.set_agent_commands(self.agent.commands)
        logger.info("[ConsciousLiving] Gateway 入站门已创建")
        boot_line("Gateway 入站门", "OK")

        # 注入 DAG + 配置 + 回调到 Agent（替代原 _inject_context_assembler）
        self._inject_dag_to_agent()

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
        boot_line("行为规则", "OK", f"{len(RULES)} 条规则")
        self._dispatcher.inject_conscious_living(self)
        self._dispatcher.inject_learn_engine(self._learn_engine)

        # being 工具暂不注册（待反省层"转换器"设计确定后再启用）
        # pleasure_lever 工具 — 快乐中枢杠杆（Olds-Milner 实验）
        self._register_pleasure_tool()

        # 注册 cron 工具（闹钟系统：schedule_alarm / list_alarms / cancel_alarm）
        self._register_cron_tools()

        # 注册 session 管理工具（manage_session：list / switch / new）
        self._register_session_tools()

        # 注册 clarify 工具并注入 CLI 回调
        self._register_clarify_tool()

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
        self.register_periodic("death_check", 60.0, self._check_death)  # 每分钟检查生存状态

        # 启动 Layer 0 自主层线程 + DMN 默认模式网络线程
        if self._load_consciousness:
            self._layer0.start()
            self._layer2.start()

            # 内感受：注入线程引用（start 后 _thread 才存在）
            self.interoception.set_threads({
                "layer0": self._layer0._thread,
                "layer2": self._layer2._thread,
            })

            # 内感受：注入 LLM 客户端引用（穿透 ContextGuard 到底层 LLMClient）
            if hasattr(self.agent, 'llm') and self.agent.llm is not None:
                llm_client = getattr(self.agent.llm, '_llm', self.agent.llm)  # ContextGuard._llm 或裸 LLMClient
                self.interoception.set_llm_callback(llm_client)
                try:
                    llm_client._interoception = self.interoception
                except Exception as e:
                    logger.debug("无法设置 _interoception 属性: %s", e)

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

    def _register_pleasure_tool(self) -> None:
        """注册 pleasure_lever 工具：刺激快乐中枢（Olds-Milner 杠杆实验）。

        LLM 可以自主按压杠杆获得快感——不需要理由，不需要意义。
        """
        try:
            from ..tools.builtin.pleasure import create_pleasure_lever
            pleasure_tool = create_pleasure_lever(self.drive)
            if hasattr(self.agent, "tools") and self.agent.tools:
                self.agent.tools.register(pleasure_tool)
                logger.info("[ConsciousLiving] pleasure_lever 工具已注册")
            else:
                logger.warning("[ConsciousLiving] agent.tools 不可用，pleasure_lever 未注册")
        except Exception as e:
            logger.warning("[ConsciousLiving] pleasure_lever 注册失败: %s", e)

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

    def _register_clarify_tool(self) -> None:
        """注册 clarify 工具并注入 CLI 回调。"""
        try:
            from ..tools.builtin.clarify import set_clarify_callback, _cli_callback, clarify_tool
            set_clarify_callback(_cli_callback)
            if hasattr(self.agent, "tools") and self.agent.tools:
                self.agent.tools.register(clarify_tool)
                logger.info("[ConsciousLiving] clarify 工具已注册（CLI 回调）")
        except Exception as e:
            logger.warning("[ConsciousLiving] clarify 工具注册失败: %s", e)

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
            if self.consciousness.self_image is not None:
                self.consciousness.self_image.contribute_intent(intent.to_dict())
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
            if e.is_empty():
                logger.info("      平静")
            else:
                for name, intensity in sorted(e.emotions.items(), key=lambda x: x[1], reverse=True):
                    logger.info("      %s: %.2f", name, intensity)

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
                "has_active_goal": self.conversation_driver.has_active_goal if self.conversation_driver else False,
            }

        si = self.consciousness.get_self_image()
        pending = si.intent.intent_buffer
        energy = si.body.energy
        has_goal = self.conversation_driver.has_active_goal if self.conversation_driver else False
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

    def _inject_dag_to_agent(self) -> None:
        """将 DAG、配置、压缩回调注入 Agent 对象。

        DAG 由 ConsciousLiving.__init__() 创建并挂到 agent.dag，这里只注入运行时配置和回调。
        ContextAssembler 已剪断——Agent._auto_compact() 直接操作 dag。
        """
        dag = getattr(self.agent, "dag", None)

        if dag is None:
            logger.warning("[ConsciousLiving] No DAG available on Agent")
            return

        # 上下文压缩通知
        def _on_compact(stats: dict) -> None:
            before = stats["before_tokens"]
            after = stats["after_tokens"]
            before_s = f"{before // 1000}k" if before >= 1000 else str(before)
            after_s = f"{after // 1000}k" if after >= 1000 else str(after)
            print(
                f"\n\033[90m[压缩] {stats['compact_count']}条消息 → 摘要 "
                f"({before_s} → {after_s})\033[0m",
                flush=True,
            )

        agent_core = self.agent._get_agent()
        agent_core.on_compact = _on_compact
        agent_core._living_cfg = self._config

        # 同步 MemoryConsole 的 dag 引用
        if self.agent.commands:
            self.agent.commands.dag = dag
        logger.info("[ConsciousLiving] DAG + config injected to Agent")

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
        drive_state = getattr(self.drive, 'desire', None)
        if drive_state:
            energy = getattr(self.drive, 'energy', None)
            energy_str = f" 能量{energy.level:.0%}" if energy and hasattr(energy, 'level') else ""
            boot_line("Drive 数据", "OK",
                      f"归属{drive_state.belonging:.1f} 认知{drive_state.cognition:.1f}"
                      f" 成就{drive_state.achievement:.1f} 表达{drive_state.expression:.1f}{energy_str}")

        # 2. 加载 Purpose
        self.purpose.load()
        goal_count = len(getattr(self.purpose, 'goals', {}))
        current = self.purpose.current_goal
        current_str = f" 当前: {current.description[:15]}" if current and hasattr(current, 'description') else ""
        boot_line("Purpose 数据", "OK",
                  f"{goal_count} 个目标{current_str}" if goal_count else "无目标")

        # 2.5 将统一叙事存储接入 Drive 和 Purpose（Memory 作为基础设施）
        ltm = getattr(self.agent, "longterm_memory", None)
        if ltm:
            self.drive.set_longterm_memory(ltm)
            self.purpose.set_longterm_memory(ltm)
            logger.info("[ConsciousLiving] 统一叙事存储已接入 Drive 和 Purpose")

        # 3. 加载 Consciousness（可选）
        if self._load_consciousness:
            self._setup_conscious_data()
            si = self.consciousness.self_image
            age_sec = si.history.consciousness_age
            age_str = f"{int(age_sec // 3600)}h{int((age_sec % 3600) // 60)}m" if age_sec > 0 else "首次燃烧"
            intent_count = len(si.intent.intent_buffer) if si.intent.intent_buffer else 0
            intent_str = f" {intent_count}意图" if intent_count else ""
            boot_line("意识数据", "OK",
                      f"{si.being.name}, 燃烧{age_str}{intent_str}")
            # _restore_snapshot() 会用新的 SelfImage 替换 self.consciousness.self_image，
            # 之前在 __init__ 挂载的运行时引用需要重新绑定到新对象上。
            si = self.consciousness.self_image
            if self._inner_voice:
                self._inner_voice._self_image = si
            if self._social_cognition:
                self._social_cognition._self_image = si
            si._project_mental_model = self._project_mental_model
            si._experience_memory = self._experience_memory
            si._learn_queue = self._learn_queue
            si.being._relationship_engine = self._relationship_engine
            essence = getattr(self.agent, '_essence', None)
            if essence is not None:
                si._essence = essence
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

        # 2.5 从 DB 加载 learning_queue（intent_buffer 已在 _restore_snapshot 中加载）
        if hasattr(self, '_learn_queue') and self._learn_queue:
            self._learn_queue.load_from_storage()

        # 3. 快照恢复失败则用模块文件恢复
        if not restored:
            restored = self.consciousness.restore_from_storage()

        # 4. 从 identity.md 加载身份字段（L0-L3 + 追求/热爱/底线/自我认知）
        import os
        identity_path = os.path.expanduser(f"~/.xiaomei-brain/{self._agent_id}/identity.md")
        with open(identity_path, "r", encoding="utf-8") as f:
            self.consciousness.being.init_from_identity_md(f.read())
        logger.info("[ConsciousLiving] 从 identity.md 初始化身份")

        # 将 Being 的阶段目标同步到 PurposeEngine
        if self.consciousness.being.phase_goals:
            self.purpose.set_phase_goals(self.consciousness.being.phase_goals)

        # 如果还是没有数据，使用默认值
        si = self.consciousness.get_self_image()
        if not si.being.name:
            si.being.name = self._agent_id
            logger.info("[ConsciousLiving] 使用 agent_id 作为默认名字")

        # 5. 初始化完成

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
            if adapter:
                self._gateway_inbound.register_channel(name, adapter)
        self._gateway_inbound.open_channels()
        channel_count = len(self._registry.list_channels())
        if channel_count:
            boot_line("频道适配器", "OK", f"{channel_count} 个")

        # 更新 send_message 工具的上下文
        try:
            from xiaomei_brain.tools.builtin.send_message import set_context
            set_context(self._agent_id, self._directory, self._inbox, router=self._router)
        except Exception as e:
            logger.warning("[ConsciousLiving] send_message set_context 失败: %s", e)

        # ── WS Gateway（Web UI 入口）──────────────────────────
        self._ws_thread = None
        self._ws_server = None
        self._admin_thread = None
        self._admin_server = None
        ws_port = self._config.living.ws_port
        if ws_port > 0:
            from ..gateway.server import create_app
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
            self._gateway_inbound.set_ws_server(self._ws_server, self._ws_thread)
            logger.info("[ConsciousLiving] WS Gateway 已启动: ws://%s:%d/ws", host, ws_port)
            boot_line("WebSocket 服务", "OK", f"ws://{host}:{ws_port}/ws")

        # ── Admin 管理门（独立端口，强制认证）────────────────────
        admin_port = getattr(self._config, 'admin_port', 0)
        if admin_port <= 0:
            lc = getattr(self._config, 'living', None)
            if lc:
                admin_port = getattr(lc, 'admin_port', 0)
        if admin_port <= 0:
            admin_port = ws_port + 1 if ws_port > 0 else 0

        if admin_port > 0:
            from ..admin.server import create_admin_app
            import uvicorn
            config_path = os.path.expanduser(f"~/.xiaomei-brain/{self._agent_id}/config.yaml")
            admin_app = create_admin_app(
                agent_id=self._agent_id,
                living=self,
                agent_manager=getattr(self, '_agent_manager', None),
                config_path=config_path,
            )
            admin_config = uvicorn.Config(admin_app, host=host, port=admin_port, log_level="warning")
            self._admin_server = uvicorn.Server(admin_config)
            self._admin_thread = threading.Thread(
                target=self._admin_server.run,
                daemon=True,
                name="admin-gateway",
            )
            self._admin_thread.start()
            logger.info("[ConsciousLiving] Admin 管理门已启动: http://%s:%d (auth=Bearer token)", host, admin_port)

    @staticmethod
    def _run_ws_gateway(app, host: str, port: int) -> None:
        """在独立线程中运行 uvicorn WS Gateway。"""
        import uvicorn
        uvicorn.run(app, host=host, port=port, log_level="warning")

    def _check_inbox(self) -> None:
        """检查收件箱 → AgentComms"""
        self._comms.check_inbox(self)

    def _on_comms_receive(self, msg) -> None:
        """HTTP 回调：收到 agent 消息 → AgentComms"""
        self._comms.on_receive(self, msg)

    def _handle_comms_message(self, msg: LivingMessage) -> None:
        """处理 agent 间通讯消息 → AgentComms"""
        self._comms.handle_message(self, msg)

    def _build_comms_system_prompt(self, target_agent: str, initiating: bool = False) -> str:
        """构建 agent 间通讯的 system prompt → AgentComms"""
        return self._comms.build_system_prompt(self, target_agent, initiating=initiating)

    # ── Hook: 状态转换 ───────────────────────────────────────────

    def _on_transition(self, old: LivingState, new_state: LivingState) -> None:
        """状态转换后同步更新意识系统的 agent_state，并写入经验流。"""
        if self._load_consciousness:
            si = self.consciousness.get_self_image()
            si.contribute_perception(agent_state=new_state.value)

        # 终端展示状态转换（启动期由 boot screen 展示，之后由 print_section 展示）
        if old in (LivingState.AWAKE, LivingState.IDLE) and new_state == LivingState.IDLE:
            self._print_section("进入个人时间", "轻度待机，随时响应", icon="🍵")

        # 写入经验流（里程碑提取器从中读取生命周期节点）
        es = getattr(self.consciousness, "exp_stream", None)
        if es and old.value != new_state.value:
            try:
                es.log(
                    type="internal_action",
                    content=f"状态切换：{old.value} → {new_state.value}",
                    importance=0.6,
                    metadata={"old_state": old.value, "new_state": new_state.value},
                    user_id=self.user_id,
                )
            except Exception as e:
                logger.warning("[ConsciousLiving] 经验流写生命周期失败: %s", e)

    # ── Hook: 心跳 ───────────────────────────────────────────────

    def _heartbeat(self, state: LivingState) -> None:
        """每 tick 调用（1秒一次）。

        L0 由 Layer0 线程独立维护，L2/L3/DREAM 由 Layer2 线程独立调度。
        此处同步 agent_state、队列深度给 consciousness，读取 interoception signals。
        """
        if not self._load_consciousness:
            return

        # 同步状态 + 队列深度给 Layer 2 / consciousness
        self.consciousness._agent_state = state.value
        self.consciousness._queue_depth = self._queue.qsize()

        # ── 读取 Interoception signals ──
        sig = getattr(self.consciousness, '_interoception_signals', None)
        if sig is not None:
            # 注入给 Living 基类（供限流 read）
            self._interoception_signals = sig

            # 压力事件 → Drive
            if self.drive and sig.stress_level != "none":
                self.drive.on_system_stress(sig.stress_level, "interoception")
            elif self.drive and sig.stress_level == "none":
                self.drive.on_system_healthy()

        # ── SOS（短路：直接从 Interoception 实例读，不经过 4 层链路）──
        intero = getattr(self, 'interoception', None)
        if intero and intero.sos and intero.sos_message:
            intero.sos = False  # 消费后清空，避免重复发送
            self.send_sos_to_channels(intero.sos_message)

        # 检查 Layer 2 发出的入梦信号
        if getattr(self.consciousness, '_dream_signal', False):
            self.consciousness._dream_signal = False
            ts = time.strftime("%H:%M:%S")
            self._debug_log("living", f"{ts} Living 收到入梦信号 → HEARTBEAT_DREAM")
            if state == LivingState.SLEEPING:
                self._heartbeat_result = HEARTBEAT_DREAM

        # 检查配额重置后的梦境标志（token 配额刚跨过 reset_hour）
        if self.drive and self.drive._pending_dream_after_reset:
            if state == LivingState.SLEEPING:
                logger.info("[ConsciousLiving] 配额重置 → 触发 DREAMING（先梦境再恢复）")
                self.drive._pending_dream_after_reset = False
                self._heartbeat_result = HEARTBEAT_DREAM

    def _loop_idle(self) -> None:
        """IDLE 自主行为主循环。

        覆盖 Living._loop_idle()：
        1. 有消息 → 切 AWAKE 聊天
        2. 消费意图队列 → 执行动作
        3. 无事 → 计空闲 → SLEEPING
        """
        while True:
            self._heartbeat_result = HEARTBEAT_NORMAL
            self._tick_periodic(self.state)

            # 0. 检查 LLM 存活（L2 线程挂了或欠费 → 进入 DORMANT）
            if getattr(self.interoception, 'sos', False):
                sos_msg = getattr(self.interoception, 'sos_message', 'LLM 致命错误') or 'LLM 致命错误'
                logger.warning("[ConsciousLiving/IDLE] interoception SOS → DORMANT: %s", sos_msg)
                self._print_section("进入休眠", f"LLM 不可用：{sos_msg}", icon="⏸️")
                self._suspended_reason = sos_msg
                self._transition(LivingState.DORMANT)
                return

            # 1. 先检查消息
            msg = self._wait_message(self.tick_interval)
            if msg is not None:
                self._on_wake_up()
                self._transition(LivingState.AWAKE)
                self._handle_message(msg)
                self._last_active = time.time()
                return

            # 2. 检查收件箱兜底（实时回调已处理大多数消息）
            self._check_inbox()

            # 3. 消费意图队列
            if self._load_consciousness:
                si = self.consciousness.get_self_image()
                self._dispatcher.tick(si)
                executed = self._dispatcher.process_queue()

                # 检查是否有 SLEEP 意图（agent 自己决定要睡了）
                if self._has_sleep_intent(si):
                    logger.info("[ConsciousLiving/IDLE] SLEEP 意图 → 进入 SLEEPING")
                    # 提取睡眠原因
                    reason = self._get_sleep_reason(si)
                    self._print_section("进入睡眠", f"原因：{reason}" if reason else "", icon="🌙")
                    # 消费 SLEEP intent，避免残留导致下次 IDLE 立即再次 SLEEP
                    self._consume_sleep_intent(si)
                    self._transition(LivingState.SLEEPING)
                    return

                if executed:
                    self._last_autonomous = time.time()
                    continue  # 有动作执行了，继续循环消费

            # 4. 无事可做 → 计空闲 → SLEEPING
            idle_time = time.time() - self._last_active
            if idle_time >= self.idle_threshold:
                self._print_section("进入睡眠", f"空闲 {idle_time:.0f}s，超时自动入睡", icon="🌙")
                self._transition(LivingState.SLEEPING)
                return

    def _check_death(self, state: LivingState) -> None:
        """每分钟检查生存状态，濒死/死亡时触发相应行为。"""
        if not self.drive or not self.drive._loaded:
            return
        if state in (LivingState.DORMANT, LivingState.DREAMING):
            return
        survival = self.drive.get_survival_state()
        if survival == "dead":
            logger.warning("[ConsciousLiving] 生存欲归零，进入死亡状态 (DORMANT)")
            self._print_section("进入休眠", "生存欲归零，停止活动", icon="💀")
            self._transition(LivingState.DORMANT)
        elif survival == "dying":
            # 濒死：强制 SLEEPING，不接受对话
            if state != LivingState.SLEEPING:
                logger.warning("[ConsciousLiving] 濒死状态 → 强制 SLEEPING")
                self._print_section("进入睡眠", "濒死状态，强制休息", icon="🌙")
                self._transition(LivingState.SLEEPING)

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

    def _has_sleep_intent(self, si) -> bool:
        """检查意图缓冲或桌面中是否有 SLEEP 意图。

        L2 引擎通过 contribute_intent() 将意图写入 intent_buffer（dict 列表），
        同时通过 _drop_to_desk() 写入 desk。两者都检查以确保覆盖。
        """
        try:
            # 1. 检查 intent_buffer（dict 列表，如 {"type": "sleep", ...}）
            buf = getattr(si.intent, 'intent_buffer', [])
            if buf:
                for item in buf:
                    if isinstance(item, dict):
                        if item.get("type", "").lower() == "sleep":
                            return True
                    else:
                        itype = getattr(item, 'type', None)
                        if itype:
                            if hasattr(itype, 'value') and itype.value == 'sleep':
                                return True
                            elif str(itype).lower() == 'sleep':
                                return True

            # 2. 检查 desk（L2 引擎投放意图的位置）
            desk = getattr(si, 'desk', None)
            if desk is not None:
                for item in getattr(desk, '_items', []):
                    intent_val = getattr(item, 'intent', None)
                    if intent_val and str(intent_val).lower() == 'sleep':
                        return True
        except Exception:
            pass
        return False

    def _consume_sleep_intent(self, si) -> None:
        """消费 SLEEP intent：从 intent_buffer 和 desk 中移除。

        防止 SLEEP intent 残留，导致下次进入 IDLE 立即再次触发 SLEEP。
        """
        # 1. 从 intent_buffer 移除
        buf = getattr(si.intent, 'intent_buffer', [])
        if buf:
            si.intent.intent_buffer = [
                i for i in buf
                if not (isinstance(i, dict) and i.get("type", "").lower() == "sleep")
            ]

        # 2. 从 desk 移除
        desk = getattr(si, 'desk', None)
        if desk is not None:
            desk._items = [
                item for item in getattr(desk, '_items', [])
                if not (getattr(item, 'intent', None) and str(item.intent).lower() == 'sleep')
            ]

    def _should_skip_dreaming(self) -> bool:
        return not self._load_consciousness

    def _loop_dreaming(self) -> None:
        """DREAMING 状态循环：运行 DreamEngine。"""
        logger.info("[ConsciousLiving] 进入 DREAMING，运行 DreamEngine")

        if self._should_skip_dreaming():
            self._transition(LivingState.SLEEPING)
            return

        self._print_section("进入梦境", "深度整理记忆 · 强化连接 · 模式发现 · 反省", icon="🌌")

        # 运行 DreamEngine（串行执行：情绪整理→记忆强化→梦境燃烧→反省）
        try:
            report = self._dream_engine.run()
            logger.info(
                "[ConsciousLiving] DreamEngine 完成: 强化%d条, 提取%d条, 摘要: %s",
                report.memories_reinforced,
                report.memories_extracted,
                report.summary[:50] if report.summary else "",
            )
            self._print_dream_results(report)
        except Exception as e:
            logger.error("[ConsciousLiving] DreamEngine 运行失败: %s", e)

        self._transition(LivingState.SLEEPING)

    # ── ActionDispatcher 通知 ────────────────────────────────

    def _print_section(self, title: str, subtitle: str = "", icon: str = "") -> None:
        """打印内部动作标题（睡眠/梦境/醒来/意图决策等）。"""
        from .internal_display import print_section
        print_section(title, subtitle=subtitle, icon=icon)

    def _print_dream_results(self, report) -> None:
        """打印梦境结果摘要。"""
        C_DIM = "\033[38;5;73m"
        C_OK = "\033[38;5;203m"
        RESET = "\033[0m"
        lines = []
        if report.memories_extracted:
            lines.append(f"🧠 记忆提取: {report.memories_extracted} 条")
        if report.memories_reinforced:
            lines.append(f"🔗 记忆强化: {report.memories_reinforced} 条")
        if report.patterns_extracted:
            lines.append(f"🔍 模式发现: {report.patterns_extracted} 个")
        if report.summary:
            lines.append(f"{C_OK}💭 梦境{RESET}: {report.summary[:120]}")
        for line in lines:
            print(f"  {C_DIM}│{RESET} {line}", flush=True)
        print(f"  {C_DIM}└──{RESET}", flush=True)

    def _print_notification(self, content: str) -> None:
        """打印通知到 CLI 状态栏"""
        name = self.consciousness.being.name if self.consciousness and self.consciousness.being else ""
        print(f"\n  \033[38;5;203m[通知] {name}{content}\033[0m", flush=True)

    # ── Message handling ─────────────────────────────────────────

    def _handle_message(self, msg: LivingMessage) -> None:
        """处理消息：委托给 MessageGateway 做预处理（命令检测、身份解析、会话切换），
        然后 ConversationDriver 做对话路由。"""
        self._gateway.handle(msg, self)

    # ── Death & Revival ────────────────────────────────────────

    _RECOVER_CHECK_INTERVAL = 300  # 5 分钟探活一次

    def _loop_dormant(self) -> None:
        """DORMANT 状态：死亡休眠，收到消息 → 复活。

        LLM 致命错误（402）导致的暂停：先探活，未恢复则拒收消息。
        其他原因导致的暂停：直接复活处理。
        """
        msg = self._wait_message(timeout=self.tick_interval)
        if msg is not None:
            # LLM 致命错误导致暂停 → 先探活再处理消息
            if self._suspended_reason and "LLM" in self._suspended_reason:
                if not self._probe_llm_health():
                    logger.warning("[ConsciousLiving/DORMANT] LLM 未恢复，忽略消息: %.50s", msg.content)
                    self._print_section("消息被搁置", f"LLM 未恢复，忽略: {msg.content[:40]}", icon="📪")
                    self.send_sos_to_channels(f"LLM 余额不足，暂时无法处理消息: {msg.content[:80]}")
                    return
            logger.info("[ConsciousLiving/DORMANT] 收到消息，复活")
            self._print_section("从休眠中醒来", "收到消息，恢复活动", icon="💫")
            if self.drive:
                self.drive.revive()
            self._suspended_reason = ""
            self._on_wake_up()
            self._transition(LivingState.AWAKE)
            self._handle_message(msg)
            self._last_active = time.time()
            return

        # 暂停恢复检查
        if self._suspended_reason:
            self._try_recover()

    def _try_recover(self) -> None:
        """尝试从 LLM 欠费暂停中恢复（周期性轻量 API 探活）。"""
        now = time.time()
        last = getattr(self, '_last_recover_check', None)
        if last is None:
            self._last_recover_check = now  # 首次挂起，初始化计时
            return
        if now - last >= self._RECOVER_CHECK_INTERVAL:
            self._last_recover_check = now
            if self._probe_llm_health():
                self._print_section("恢复运行", "LLM 余额已恢复，L2 线程已重启", icon="🔄")
                agent_name = getattr(self.agent, 'name', None) or self._agent_id
                self.send_sos_to_channels(f"{agent_name} 已恢复运行")
                self._suspended_reason = ""
                self._on_wake_up()
                self._transition(LivingState.AWAKE)

    def _probe_llm_health(self) -> bool:
        """发送轻量 LLM 请求检查余额是否恢复。

        Returns:
            True 表示 LLM 已恢复，False 表示仍然不可用。
        恢复时自动重启 L2 线程并清除 interoception SOS 标记。
        """
        try:
            llm = self.agent.llm
            llm.chat(messages=[{"role": "user", "content": "hi"}], tools=None, log_level=logging.DEBUG)
            # 成功了 = 余额恢复
            logger.info("[ConsciousLiving] LLM 探活成功，余额已恢复")
            # 重启 L2 DMN 线程（Python 线程不能 restart，创建新 Thread 对象）
            if hasattr(self, '_layer2') and self._layer2:
                self._layer2.start()
                # 更新内感受的线程引用（新 Thread 对象）
                self.interoception.set_threads({
                    "layer0": self._layer0._thread,
                    "layer2": self._layer2._thread,
                })
            # 清除 SOS 标记
            self.interoception.sos = False
            self.interoception.sos_message = ""
            self.interoception.stress_level = "normal"
            return True
        except FatalLLMError as e:
            if e.status_code == 402:
                logger.debug("[ConsciousLiving] LLM 探活: 仍欠费 (%.0f分钟后重试)",
                             self._RECOVER_CHECK_INTERVAL / 60)
            else:
                raise
        except Exception:
            logger.debug("[ConsciousLiving] LLM 探活: 网络异常，继续等待")
        return False

    # ── Hooks ────────────────────────────────────────────────────

    def _verify_llm(self) -> None:
        """启动时检测 LLM 连通性，不可用则拒绝启动。"""
        llm = self.agent.llm
        logger.info("[ConsciousLiving] 验证 LLM 连通性: %s @ %s", llm.model, llm.base_url)
        try:
            resp = llm.chat(messages=[{"role": "user", "content": "hi"}], tools=None)
            logger.info("[ConsciousLiving] LLM 连通性验证通过: %.50s", resp.content or "")
        except Exception as e:
            raise FatalLLMError(
                f"LLM 启动验证失败: {e}",
                status_code=getattr(e, 'status_code', 0),
            ) from e

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
            self.consciousness._last_intent_time = time.time()
            self.consciousness._last_emerge_time = time.time()
            self.consciousness._last_l3_time = time.time()
            # 清理跨会话残留 intent（快照恢复的旧 intent 不应跨会话生效）
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
            si.contribute_perception(user_active=True)

        # fresh_tail 延迟到登录后加载（此时才知道 user_id）
        logger.info("[ConsciousLiving] Good morning! 火焰点燃。")

        # 唤醒身体感官
        body = getattr(self, 'body', None)
        if body:
            body.open()
            logger.info("[ConsciousLiving] Body 感官已上线")

    def load_fresh_tail(self) -> None:
        """加载 fresh tail：让 agent "带着最近的记忆醒来"。

        在用户登录后调用（此时 user_id 已确定），从 DB 还原完整的消息序列，
        包括 assistant(tool_calls) + tool 配对。
        """
        if not self.agent.conversation_db or not getattr(self.agent, "dag", None):
            return

        agent = self.agent._get_agent()
        recent = self.agent.conversation_db.get_recent(
            self._config.context.fresh_tail_count,
            user_id=self.user_id,
        )

        if not recent:
            logger.info("[ConsciousLiving] fresh_tail: 无历史消息 (user_id=%s)", self.user_id)
            return

        import json

        # 第一遍：收集 assistant 的 tool_call_ids（用于过滤孤立 tool 消息）
        assistant_tc_ids: set[str] = set()
        for m in recent:
            if m.get("role") == "assistant":
                metadata = m.get("metadata", {})
                if isinstance(metadata, str):
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
        # 给 user/assistant 消息加上 [HH:MM] 时间前缀，让 LLM 感知对话发生的时间
        restored: list[dict] = []
        for m in recent:
            role = m.get("role", "user")
            db_id = m.get("id")  # SQLite row id
            created_ts = m.get("created_at", 0)
            time_prefix = ""
            if created_ts and role in ("user", "assistant"):
                try:
                    time_prefix = datetime.fromtimestamp(created_ts).strftime("[%m-%d %H:%M] ")
                except Exception:
                    pass
            if role == "user":
                msg = {"role": "user", "content": f"{time_prefix}{m.get('content', '')}"}
                if db_id is not None:
                    msg["id"] = db_id
                if created_ts:
                    msg["created_at"] = created_ts
                restored.append(msg)
            elif role == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": f"{time_prefix}{m.get('content', '')}"}
                if db_id is not None:
                    msg["id"] = db_id
                if created_ts:
                    msg["created_at"] = created_ts
                metadata = m.get("metadata", {})
                if isinstance(metadata, str):
                    try:
                        metadata = json.loads(metadata)
                    except Exception:
                        metadata = {}
                if isinstance(metadata, dict):
                    if metadata.get("tool_calls"):
                        msg["tool_calls"] = metadata["tool_calls"]
                        # DeepSeek V4: 有工具调用的轮次必须传回 reasoning_content
                        rc = metadata.get("reasoning_content") or metadata.get("reasoning")
                        if rc:
                            msg["reasoning_content"] = rc
                    elif metadata.get("reasoning_content"):
                        # 无工具调用的轮次不需要传回，但保留 metadata 以备他用
                        pass
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

        # 第五遍：合并连续主动输出（保留时间戳，让 LLM 区分各条消息）
        merged = []
        i = 0
        while i < len(cleaned):
            m = cleaned[i]
            role = m.get("role", "")
            is_plain_assistant = (role == "assistant" and not m.get("tool_calls"))
            if is_plain_assistant:
                # 收集连续的纯文本 assistant 消息（含对话回复 + 主动输出）
                run = [m]
                j = i + 1
                while j < len(cleaned):
                    nm = cleaned[j]
                    if nm.get("role") == "assistant" and not nm.get("tool_calls"):
                        run.append(nm)
                        j += 1
                    else:
                        break
                if len(run) == 1:
                    merged.append(run[0])
                else:
                    parts = [rm.get("content", "") for rm in run]
                    merged_msg = dict(run[-1])
                    merged_msg["content"] = "\n\n".join(parts)
                    merged.append(merged_msg)
                i = j
            else:
                merged.append(m)
                i += 1
        if len(merged) < len(cleaned):
            logger.info(
                "[ConsciousLiving] 合并 %d 条连续 assistant → %d 条",
                len(cleaned), len(merged),
            )

        # 确保首条为 user（DeepSeek 要求 system 后第一条必须是 user）
        if merged and merged[0].get("role") != "user":
            merged.insert(0, {"role": "user", "content": ""})

        agent.messages = merged
        logger.info("[ConsciousLiving] 加载 fresh_tail: %d 条消息 (user_id=%s)", len(agent.messages), self.user_id)

    def _get_sleep_reason(self, si) -> str:
        """从意图缓冲中提取 SLEEP 意图的原因。"""
        buf = getattr(si.intent, 'intent_buffer', [])
        for item in buf:
            if isinstance(item, dict):
                if item.get("type", "").lower() == "sleep":
                    return item.get("content", "") or item.get("reason", "")
            elif hasattr(item, 'type'):
                itype = getattr(item, 'type', None)
                if itype:
                    iv = itype.value if hasattr(itype, 'value') else str(itype)
                    if iv.lower() == 'sleep':
                        return getattr(item, 'content', '') or getattr(item, 'reason', '')
        return ""

    def _on_wake_up(self) -> None:
        """从 IDLE/SLEEPING 收到消息唤醒，直接切 AWAKE 处理。

        idle 不是睡眠/梦境状态，不需要调 consciousness.on_wake()。
        on_wake() 只用于 DORMANT→AWAKE（启动）和 SLEEPING→AWAKE（睡眠醒来）。
        """
        was_sleeping = self.state == LivingState.SLEEPING
        logger.info("[ConsciousLiving] Waking up — message received!")
        # 清除残留的 SLEEP intent（状态相关，醒来后无意义）
        if self._load_consciousness:
            si = self.consciousness.get_self_image()
            self._consume_sleep_intent(si)
        self._transition(LivingState.AWAKE)
        if was_sleeping:
            self._print_section("醒来", "收到消息，恢复活动", icon="☀️")

    def send_sos_to_channels(self, message: str, channels: list | None = None) -> None:
        """SOS 紧急推送：绕过 LLM，直接发送到所有可用渠道。"""
        ts = time.strftime("%H:%M:%S")
        sos_text = f"[SOS] {ts}\n{message}"

        # 优先通过 Router 广播到所有已连接通道
        router = getattr(self, '_router', None)
        if router:
            sent = router.broadcast(sos_text)
            if sent > 0:
                logger.warning("[Living SOS] 已广播到 %d 个通道: %.100s", sent, message)
                return

        # 无 Router 时走 stdout
        print(f"\n\033[91m{sos_text}\033[0m", flush=True)

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
        self._gateway_inbound.close_channels()

        # 关闭身体感官
        body = getattr(self, 'body', None)
        if body:
            body.close()
            logger.info("[ConsciousLiving] Body 感官已下线")

        if self.drive:
            self.drive.save()
        if self.purpose:
            self.purpose.save()

    # ── Proactive output ─────────────────────────────────────────

    def _send_proactive(self, content: str, user_id: str | None = None) -> None:
        """发送主动消息。按用户最近活跃渠道路由，CLI 回调兜底。"""
        target_user = user_id or self.user_id
        logger.info("[ConsciousLiving/Proactive] 主动发送 (%d 字) to %s", len(content), target_user)

        if self.agent.conversation_db:
            try:
                self.agent.conversation_db.log(
                    session_id=self.session_id,
                    role="assistant",
                    content=content,
                    user_id=target_user,
                )
            except Exception as e:
                logger.warning("[ConsciousLiving/Proactive] 对话日志写入失败: %s", e)

        # 合并到 agent.messages：让 agent 感知自己发过主动消息
        try:
            agent = self.agent._get_agent()
            msgs = agent.messages
            last_user = getattr(self.agent, '_last_user_msg_time', 0) or getattr(agent, '_last_user_msg_time', 0)
            gap = time.time() - last_user if last_user else float('inf')
            if (msgs and msgs[-1].get("role") == "assistant"
                    and not msgs[-1].get("tool_calls")
                    and gap < 1800):
                # 短间隔：合并到上一条 assistant
                msgs[-1]["content"] = msgs[-1].get("content", "") + "\n\n" + content
            else:
                # 长间隔或第一条：插空 user 保持交替
                if msgs and msgs[-1].get("role") == "assistant":
                    msgs.append({"role": "user", "content": ""})
                msgs.append({"role": "assistant", "content": content})
        except Exception as e:
            logger.debug("[ConsciousLiving/Proactive] agent.messages 合并失败: %s", e)

        # Router 优先：按用户最近活跃渠道分发
        # CLI 渠道走 on_proactive 回调（Rich Markdown 格式化），
        # 其他渠道（WS/飞书等）走 Router.deliver()
        if hasattr(self, '_router') and self._router:
            for try_session in (True, False):
                route = (
                    self._router.route_for_user(target_user) if try_session
                    else self._router.route_for_session(self.session_id)
                )
                if route and route.type == "cli" and self.on_proactive:
                    self.on_proactive(content, target_user)
                    return
                if route and route.type != "cli":
                    text = re.sub(r'\x1b\[[0-9;]*m', '', content)
                    if self._router.deliver(text, route):
                        return
            # 非 CLI 路由没配上 → 下面的兜底

        # 兜底：on_proactive 回调 / 裸 print
        if self.on_proactive:
            self.on_proactive(content, target_user)
        else:
            print(f"\n\033[36m[{self.agent.name or self._agent_id}] {content}\033[0m", flush=True)