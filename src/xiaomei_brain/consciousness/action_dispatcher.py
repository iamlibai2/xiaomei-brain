"""ActionDispatcher: 统一动作分发器。

从 SelfImage 读取状态，遍历规则，匹配产出 ActionItem 队列，按优先级顺序执行。

设计原则：
- 只负责判断（基于 SelfImage 状态匹配规则）
- 不负责执行（委托给 ActionExecutor）
- 统一管理冷却时间
- 所有动作（Intent/Desire/Goal/System）走同一入口
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .action_item import ActionItem, ActionType
    from .self_image import SelfImage


logger = logging.getLogger(__name__)


class ActionExecutor:
    """动作执行器（只执行不判断）。

    负责把 ActionItem 转换为实际行为。
    """

    def __init__(self, dispatcher: ActionDispatcher):
        self.dispatcher = dispatcher

    def execute(self, item: ActionItem) -> bool:
        """执行单个 ActionItem。

        Returns:
            True 表示执行成功，False 表示失败或无法执行
        """
        handlers = {
            "proactive": self._do_proactive,
            "trigger_l3": self._do_trigger_l3,
            "tool": self._do_tool,
            "notify": self._do_notify,
        }
        handler = handlers.get(item.action_type.value)
        if not handler:
            logger.warning("[ActionExecutor] 未知动作类型: %s", item.action_type)
            return False
        return handler(item)

    def _do_proactive(self, item: ActionItem) -> bool:
        """发送主动消息"""
        content = item.content
        if not content:
            # 空的 content：由 LLM 生成（通过 intent/content + SelfImage 状态）
            logger.info("[ActionExecutor] 主动消息内容为空，调用 LLM 生成...")
            content = self._generate_proactive_content(item)
            logger.info("[ActionExecutor] LLM 生成内容: %s", content[:80])

        # 执行前先记录要消费的 intent 类型
        intent_type = item.metadata.get("intent_type", "") if item.source == "intent" else ""

        self.dispatcher._send_proactive(content)
        logger.info("[ActionExecutor] 主动消息: %s", content[:50])

        # 消费已执行的 intent（避免下一 tick 重复匹配）
        if intent_type and item.source == "intent":
            si = self.dispatcher._get_self_image()
            if si and hasattr(si, "intent_buffer"):
                upper_type = intent_type.upper()
                si.intent_buffer = [i for i in si.intent_buffer if i.upper() != upper_type]
                logger.debug("[ActionExecutor] 已消费 intent: %s", intent_type)

        return True

    def _do_trigger_l3(self, item: ActionItem) -> bool:
        """触发 L3 深度燃烧"""
        if self.dispatcher._conscious_living is None:
            logger.warning("[ActionExecutor] 无 ConsciousLiving 引用，无法触发 L3")
            return False

        # 执行前先记录要消费的 intent 类型
        intent_type = item.metadata.get("intent_type", "") if item.source == "intent" else ""

        try:
            report = self.dispatcher._conscious_living.consciousness.tick_L3()
            logger.info("[ActionExecutor] L3 触发: %s", report.summary[:50] if report else "")

            # 消费已执行的 intent
            if intent_type and item.source == "intent":
                si = self.dispatcher._get_self_image()
                if si and hasattr(si, "intent_buffer"):
                    upper_type = intent_type.upper()
                    si.intent_buffer = [i for i in si.intent_buffer if i.upper() != upper_type]
                    logger.debug("[ActionExecutor] 已消费 intent: %s", intent_type)

            return True
        except Exception as e:
            logger.error("[ActionExecutor] L3 触发失败: %s", e)
            return False

    def _do_tool(self, item: ActionItem) -> bool:
        """执行工具"""
        tool_name = item.content
        if not tool_name:
            logger.warning("[ActionExecutor] TOOL 类型动作但 content 为空")
            return False
        logger.info("[ActionExecutor] 执行工具: %s", tool_name)
        # 工具执行委托给 action_executor
        if self.dispatcher._action_executor:
            try:
                action_data = {
                    "type": tool_name,
                    "reason": item.reason,
                    "metadata": item.metadata,
                }
                self.dispatcher._action_executor.execute(action_data)
                return True
            except Exception as e:
                logger.error("[ActionExecutor] 工具执行失败: %s", e)
                return False
        return False

    def _do_notify(self, item: ActionItem) -> bool:
        """通知用户（显示在状态栏）"""
        logger.info("[ActionExecutor] 通知: %s", item.content)
        if self.dispatcher._conscious_living:
            self.dispatcher._conscious_living._print_notification(item.content)
        return True

    def _generate_proactive_content(self, item: ActionItem) -> str:
        """通过 LLM 根据意图类型生成主动消息内容"""
        intent_type = item.metadata.get("intent_type", "")
        source = item.metadata.get("source", "")
        desire_type = item.metadata.get("desire_type", "")

        if intent_type in ("GREET", "ACT") or source == "idle":
            return self._generate_greeting(item)
        elif intent_type == "CARE":
            return self._generate_care(item)
        else:
            return item.reason

    def _generate_greeting(self, item: ActionItem) -> str:
        """通过 LLM 基于最近对话生成个性化问候"""
        from datetime import datetime
        from xiaomei_brain.memory.conversation_db import estimate_tokens

        si = self.dispatcher._get_self_image()
        if not si:
            logger.warning("[_generate_greeting] SelfImage 不存在，fallback")
            return self._fallback_greeting()

        # 从 SelfImage 读取最近对话
        recent = getattr(si, "recent_conversations", [])
        idle_duration = item.metadata.get("idle_duration", 0)
        idle_minutes = int(idle_duration / 60) if idle_duration else 0

        logger.info("[_generate_greeting] idle_duration=%ds, idle_min=%d, recent_count=%d, recent=%s",
                    idle_duration, idle_minutes, len(recent),
                    [f"{m.get('role','?')}:{m.get('content','')[:30]}" for m in recent[-3:]])

        # 拼对话摘要（最多 5 条，防止 token 爆炸）
        conv_lines = []
        for msg in recent[-10:]:
            role = msg.get("role", "")
            content = msg.get("content", "")[:200]
            if content and role in ("user", "assistant"):
                conv_lines.append(f"{role}: {content}")

        conv_text = "\n".join(conv_lines) if conv_lines else "（无历史对话）"

        # 时间段
        hour = datetime.now().hour
        if 6 <= hour < 12:
            period = "早上"
        elif 12 <= hour < 18:
            period = "下午"
        elif 18 <= hour < 22:
            period = "晚上"
        else:
            period = "深夜"

        # 重构 prompt：指令放前面，对话历史作为背景（避免 LLM 继续最后一条消息）
        prompt = f"""你是小美，一个温柔体贴的AI伴侣。

直接生成任何一句你想说的话，可以是说给用户的，也可以是说给别人，也可以是说给自己听（50字以上，500字以内）或者调用任何你需要的工具，做你想做的事情。
这句话会直接发送给用户。
不要加引号或格式。

历史对话：
{conv_text}

直接输出你想说的话："""

        logger.info("[_generate_greeting] === LLM PROMPT START ===")
        logger.info("%s", prompt)
        logger.info("[_generate_greeting] === LLM PROMPT END ===")

        # 调用 LLM 生成
        llm = None
        cl = self.dispatcher._conscious_living
        if cl and hasattr(cl, "agent"):
            llm = getattr(cl.agent, "llm", None)

        if llm:
            try:
                resp = llm.chat(messages=[{"role": "user", "content": prompt}])
                content = resp.content.strip() if resp and resp.content else None
                logger.info("[_generate_greeting] LLM 返回: %s", content[:100] if content else "None")
                if content:
                    return content
            except Exception as e:
                logger.warning("[_generate_greeting] LLM 调用失败: %s", e)

        logger.info("[_generate_greeting] LLM 不可用，fallback")
        return self._fallback_greeting()

    def _fallback_greeting(self) -> str:
        """兜底问候（规则生成）"""
        from datetime import datetime
        hour = datetime.now().hour
        if 6 <= hour < 12:
            greeting = "早上好！"
        elif 12 <= hour < 18:
            greeting = "下午好！"
        elif 18 <= hour < 22:
            greeting = "晚上好！"
        else:
            greeting = "夜深了，还在呢？"
        si = self.dispatcher._get_self_image()
        if si and hasattr(si, "last_dream_summary") and si.last_dream_summary:
            greeting += f" 我刚做了一个梦，{si.last_dream_summary[:30]}..."
        return greeting

    def _generate_care(self, item: ActionItem) -> str:
        """生成关心消息"""
        return "我有点担心你... "


class ActionDispatcher:
    """统一动作分发器"""

    def __init__(self):
        self._rules: list = []
        self._queue: list[ActionItem] = []
        self._executor = ActionExecutor(self)

        # 外部引用（由 ConsciousLiving 注入）
        self._conscious_living = None
        self._action_executor = None

        # 冷却记录：key → 上次触发时间
        self._cooldown: dict[str, float] = {}

        # 是否已加载规则
        self._rules_loaded = False

    # ── Public API ─────────────────────────────────────────

    def load_rules(self, rules: list) -> None:
        """加载规则表"""
        self._rules = rules
        self._rules_loaded = True
        logger.info("[ActionDispatcher] 已加载 %d 条规则", len(rules))

    def tick(self, self_image: SelfImage) -> list[ActionItem]:
        """基于 SelfImage 状态，遍历规则，产出 ActionItem 列表。

        不执行，只收集。
        执行由 process_queue() 负责。
        """
        self._queue.clear()
        idle_dur = getattr(self_image, "user_idle_duration", 0)
        # logger.info("[ActionDispatcher.tick] idle_duration=%.1fs, checking rules...", idle_dur)

        if not self._rules_loaded:
            from .rules import _init_rules, RULES
            _init_rules()
            self.load_rules(RULES)

        for rule in self._rules:
            if not rule.enabled():
                continue

            try:
                matched = rule.condition(self_image)
            except Exception as e:
                logger.warning("[ActionDispatcher] 规则匹配异常: %s", e)
                continue

            if not matched:
                continue

            # 检查冷却
            if not self._is_cooldown_ready(rule.cooldown_key, rule.cooldown_seconds):
                logger.debug("[ActionDispatcher] 规则冷却中: %s", rule.cooldown_key)
                continue

            # 复制 action_item（避免同一对象重复入队）
            item = self._clone_action_item(rule.action_item)
            self._queue.append(item)
            logger.info("[ActionDispatcher] 规则匹配: %s → %s (priority=%.2f)",
                        rule.cooldown_key, item.reason, item.priority)

        # logger.info("[ActionDispatcher.tick] matched %d items", len(self._queue))
        return list(self._queue)

    def process_queue(self) -> None:
        """按优先级顺序执行队列中的所有 ActionItem"""
        if not self._queue:
            return

        # 排序：source 优先级 → priority
        self._queue.sort(key=lambda item: item.sort_key())

        logger.info("[ActionDispatcher] 队列执行: %d 个动作", len(self._queue))
        for item in self._queue:
            try:
                success = self._executor.execute(item)
                if success:
                    self._record_fired(item.cooldown_key)
            except Exception as e:
                logger.error("[ActionDispatcher] 执行失败: %s, error=%s", item, e)

        self._queue.clear()

    def add_rule(self, rule) -> None:
        """动态添加规则"""
        self._rules.append(rule)

    def clear_queue(self) -> None:
        """清空队列"""
        self._queue.clear()

    # ── 内部 ─────────────────────────────────────────────

    def _is_cooldown_ready(self, key: str, seconds: float) -> bool:
        """检查冷却是否已过"""
        if not key or seconds <= 0:
            return True
        last = self._cooldown.get(key, 0)
        return (time.time() - last) >= seconds

    def _record_fired(self, key: str) -> None:
        """记录动作已触发，更新冷却时间"""
        if key:
            self._cooldown[key] = time.time()

    def _clone_action_item(self, item: ActionItem) -> ActionItem:
        """复制 ActionItem（避免共享引用）"""
        from .action_item import ActionItem, ActionType
        return ActionItem(
            action_type=item.action_type,
            priority=item.priority,
            content=item.content,
            reason=item.reason,
            source=item.source,
            cooldown_key=item.cooldown_key,
            metadata=dict(item.metadata),
        )

    def _send_proactive(self, content: str) -> None:
        """发送主动消息（委托给 ConsciousLiving）"""
        if self._conscious_living:
            self._conscious_living._send_proactive(content)

    def _get_self_image(self):
        """获取 SelfImage（委托给 ConsciousLiving）"""
        if self._conscious_living:
            return self._conscious_living.consciousness.get_self_image()
        return None

    def inject_conscious_living(self, cl) -> None:
        """注入 ConsciousLiving 引用（用于执行动作）"""
        self._conscious_living = cl

    def inject_action_executor(self, executor) -> None:
        """注入 DesireActionExecutor（用于执行工具类动作）"""
        self._action_executor = executor
