"""MemoryExtractor: extract long-term memories from conversations.

Three extraction modes:
1. Every-turn: LLM-judged extraction every turn (Mem0 route, default)
2. Periodic: batch extraction every N minutes (background thread)
3. Dream: deep analysis during idle/nighttime
"""

from __future__ import annotations

import datetime
import logging
import time
from typing import Any

from .conversation_db import ConversationDB
from .longterm import LongTermMemory

logger = logging.getLogger(__name__)

# Prompts — memories about user use "用户...", memories about Xiaomei use "我..."

# [废弃] 旧提取 prompt，已被 EVERY_TURN_EXTRACT_PROMPT 替代
IMMEDIATE_EXTRACT_PROMPT = """从以下对话中提取值得长期记住的信息。

规则：
- 关于用户的信息，用"用户..."表述（如：用户叫张三）
- 关于小美自己的信息，用"我..."表述
每条信息一行，格式：类别|内容
类别可以是：偏好、事实、经验、教训

用户输入中没有值得提取的信息时，输出：无

用户：{user_input}
助手：{assistant_response}"""

# [定时批处理用] 提取+决策合并一次完成
PERIODIC_EXTRACT_PROMPT = """从对话片段中提炼值得长期记住的信息，并判断如何处理。

【已有记忆】（供参考）
{recent_memories}

【对话片段】
{messages}

【提炼规则】
- 关于用户用"用户..."，关于小美用"我..."
- 只提取确实重要和有价值的内容
- 对每条记忆判断处理方式：
  * ADD: 全新信息
  * UPDATE: 已有记忆的更新
  * MERGE: 可合并的同类信息
  * NOOP: 无意义/重复，无需存储
- 如果没有值得提炼的内容，输出：无

输出格式（每条一行）：
ACTION|类别|内容

直接输出，无需解释："""

# [实时对话用] 提取+决策合并一次完成
# LLM 输出格式: ACTION|类别|内容  （ACTION = ADD/UPDATE/MERGE/NOOP）
EVERY_TURN_EXTRACT_PROMPT = """你是记忆提取系统。从对话中提炼关于"用户"的重要信息，并判断如何处理。

【已有记忆】（供参考）
{recent_memories}

【对话上下文】
{context}

【当前轮次】
用户：{user_input}
助手：{assistant_response}

【提炼规则】
- 只关注"用户"的相关信息，用"用户..."表述
- 不要复制助手回复
- 忽略临时性闲聊
- 对每条记忆，判断处理方式：
  * ADD: 全新的重要信息
  * UPDATE: 已有记忆的更新版本
  * MERGE: 可合并的同类信息（如两个偏好）
  * NOOP: 无意义/重复，无需存储
- 如果没有值得提炼的内容，输出：无

输出格式（每条一行）：
ACTION|类别|内容
例如：
ADD|事实|用户叫李四
UPDATE|偏好|用户改名叫王五
MERGE|偏好|用户喜欢川菜和湘菜
NOOP|事实|用户今天说了你好

直接输出，无需解释："""

# [梦境用] 提取+决策合并一次完成
DREAM_EXTRACT_PROMPT = """你是小美的内心反思系统。在以下对话中，提炼关于"小美自己"的重要信息，并判断如何处理。

【已有记忆】（供参考）
{recent_memories}

【今日对话】
{messages}

【提炼规则】
- 只关注"小美自己"的内在收获，用"我..."表述
- 包括：经验、教训、洞察、新的自我认知
- 判断处理方式：
  * ADD: 全新体悟
  * UPDATE: 已有认知的更新
  * MERGE: 可合并的同类体悟
  * NOOP: 无意义/重复
- 如果没有值得提炼的内容，输出：无

输出格式（每条一行）：
ACTION|类别|内容

直接输出，无需解释："""


class MemoryExtractor:
    """Memory extractor — extracts memories from conversations.

    Extraction modes:
    1. Every-turn: LLM-judged extraction every turn (Mem0 route, default)
    2. Periodic: batch extraction every N minutes (background thread)
    3. Dream: deep analysis at night / idle
    """

    # [废弃] 关键词触发方式，已被 extract_every_turn 替代。
    # 旧方式依赖硬编码关键词（如"记住"、"我讨厌"），会漏掉"我是李白"等重要信息。
    # 新方式每轮调 LLM 自己判断，Mem0 路线，无需关键词过滤。
    IMMEDIATE_KEYWORDS = [
        "记住", "我以前", "我喜欢", "我要", "我不要",
        "帮我记", "别忘了", "我讨厌",
    ]

    def __init__(
        self,
        llm_client: Any = None,
        longterm_memory: LongTermMemory | None = None,
        conversation_db: ConversationDB | None = None,
    ) -> None:
        self.llm = llm_client
        self.ltm = longterm_memory
        self.db = conversation_db
        self._last_extract_time = time.time()

    # [废弃] 已由 extract_every_turn 替代，保留仅供兼容。
    def check_immediate(self, user_input: str) -> bool:
        """[废弃] 关键词匹配方式判断是否提取，已被 extract_every_turn 替代。"""
        return any(kw in user_input for kw in self.IMMEDIATE_KEYWORDS)

    # [废弃] 已由 extract_every_turn 替代，保留仅供兼容。
    def extract_immediate(
        self, user_input: str, assistant_response: str,
        user_id: str = "global",
    ) -> list[int]:
        """[废弃] 关键词触发提取，已被 extract_every_turn 替代。"""
        if not self.ltm or not self.llm:
            return []

        try:
            prompt = IMMEDIATE_EXTRACT_PROMPT.format(
                user_input=user_input[:500],
                assistant_response=assistant_response[:500],
            )
            result = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
            )
            return self._execute_actions(
                result.content or "", source="immediate", user_id=user_id,
            )
        except Exception as e:
            logger.error("Immediate extraction failed: %s", e)
            return []

    def extract_periodic(
        self, interval_minutes: int = 10, user_id: str = "global",
    ) -> list[int]:
        """Periodic extraction of recent conversations."""
        if not self.ltm or not self.db:
            return []

        since = self._last_extract_time
        messages = self.db.query(since=since, limit=50)

        if len(messages) < 3:
            return []

        if not self.llm:
            return []

        try:
            formatted = self._format_messages(messages)
            recent_memories = ""
            existing = self.ltm.get_recent(10, user_id=user_id)
            if existing:
                recent_memories = "\n".join(f"- {m['content']}" for m in existing)
            prompt = PERIODIC_EXTRACT_PROMPT.format(
                messages=formatted,
                recent_memories=recent_memories or "（无已有记忆）",
            )
            result = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
            )
            ids = self._execute_actions(
                result.content or "", source="periodic", user_id=user_id,
            )
            self._last_extract_time = time.time()
            return ids
        except Exception as e:
            logger.error("Periodic extraction failed: %s", e)
            return []

    def extract_dream(self, user_id: str = "global") -> list[int]:
        """Deep dream-mode extraction of today's conversations."""
        if not self.ltm or not self.db:
            return []

        today_start = datetime.datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()

        messages = self.db.query(since=today_start, limit=500)
        if len(messages) < 3:
            return []

        if not self.llm:
            return []

        try:
            formatted = self._format_messages(messages)

            # 获取已有记忆供 LLM 参考
            recent_memories = ""
            existing = self.ltm.get_recent(10, user_id=user_id)
            if existing:
                recent_memories = "\n".join(f"- {m['content']}" for m in existing)

            prompt = DREAM_EXTRACT_PROMPT.format(
                messages=formatted,
                recent_memories=recent_memories or "（无已有记忆）",
            )
            result = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
            )
            ids = self._execute_actions(
                result.content or "", source="dream", importance=0.8, user_id=user_id,
            )
            return ids
        except Exception as e:
            logger.error("Dream extraction failed: %s", e)
            return []

    def extract_every_turn(
        self,
        user_input: str,
        assistant_response: str,
        user_id: str = "global",
        context_turns: int = 6,
    ) -> list[int]:
        """每轮对话后调用。一次 LLM 调用完成提取+决策。

        Args:
            user_input: 当前用户输入
            assistant_response: 当前助手回复
            user_id: 用户标识
            context_turns: 上下文取最近几条消息（帮助理解语境）
        """
        if not self.ltm or not self.llm:
            return []

        try:
            # 获取最近 context_turns 条消息作为上下文
            recent = self.db.get_recent(context_turns, session_id=None) if self.db else []
            context_text = self._format_messages(recent) if recent else "（无历史上下文）"

            # 获取已有记忆供 LLM 参考（做决策用）
            recent_memories = ""
            if self.ltm:
                existing = self.ltm.get_recent(10, user_id=user_id)
                if existing:
                    recent_memories = "\n".join(
                        f"- {m['content']}" for m in existing
                    )

            prompt = EVERY_TURN_EXTRACT_PROMPT.format(
                context=context_text,
                recent_memories=recent_memories or "（无已有记忆）",
                user_input=user_input[:500],
                assistant_response=assistant_response[:500],
            )
            result = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
            )
            ids = self._execute_actions(
                result.content or "", source="every_turn", user_id=user_id,
            )
            if ids:
                logger.info(
                    "[EveryTurn] Extracted %d memories for user=%s",
                    len(ids), user_id,
                )
            return ids
        except Exception as e:
            logger.error("Every-turn extraction failed: %s", e)
            return []

    def _format_messages(self, messages: list[dict]) -> str:
        """Format messages for LLM prompt."""
        lines = []
        for m in messages[-30:]:
            role = m.get("role", "unknown")
            content = m.get("content", "")
            if role == "tool":
                lines.append(f"[tool:{m.get('tool_name','')}] {content[:100]}")
            else:
                lines.append(f"[{role}] {content[:200]}")
        return "\n".join(lines)

    def _llm_merge(self, old_content: str, new_content: str) -> str:
        """Merge two memories using LLM. Returns plain text, no markdown."""
        prompt = (
            f"合并以下两条记忆为一条，输出纯文本（无markdown、无标记）：\n"
            f"旧: {old_content}\n新: {new_content}"
        )
        resp = self.llm.chat(messages=[{"role": "user", "content": prompt}])
        raw = (resp.content or new_content).strip()
        # 去掉残留 markdown
        import re
        raw = re.sub(r'\*\*(.*?)\*\*', r'\1', raw)
        raw = re.sub(r'^\s*>+\s*', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'^#+\s*', '', raw, flags=re.MULTILINE)
        return raw

    def _llm_update_content(self, old_content: str, new_content: str) -> str:
        """UPDATE 时提炼核心事实，丢弃确认/纠正类元信息，输出简洁陈述。

        例：
        旧: 用户名叫张三
        新: 用户名字确认是李白，之前误记为张三
        → 输出: 用户名叫李白
        """
        prompt = (
            "以下是新记忆对旧记忆的更新。请提炼出最简洁的核心事实，丢弃确认、纠正、备注等元信息。\n"
            "旧: " + old_content + "\n"
            "新: " + new_content + "\n"
            "要求：输出一句简洁的事实陈述，不含'确认''纠正''之前误记'等词语。\n"
            "直接输出结果："
        )
        resp = self.llm.chat(messages=[{"role": "user", "content": prompt}])
        raw = (resp.content or new_content).strip()
        import re
        raw = re.sub(r'\*\*(.*?)\*\*', r'\1', raw)
        raw = re.sub(r'^\s*>+\s*', '', raw, flags=re.MULTILINE)
        return raw

    def _execute_actions(
        self, llm_output: str, source: str = "manual",
        importance: float = 0.5, user_id: str = "global",
    ) -> list[int]:
        """解析 LLM 输出（ACTION|tag|content），直接执行操作。

        新格式：一次 LLM 调用输出所有记忆及其决策，无需逐条 resolve。
        - ADD: 直接 store
        - UPDATE/MERGE/DELETE: 先 recall 找目标，再执行
        """
        if not llm_output or llm_output.strip() in ("无", "无\n", "无\r"):
            return []

        import re

        ids = []
        for line in llm_output.strip().split("\n"):
            line = line.strip()
            if not line or line == "无":
                continue

            # 跳过 markdown 残留
            if line.startswith("**") or line.startswith("#"):
                continue

            # 解析 ACTION|tag|content 格式
            parts = line.split("|", 2)  # split at most 2 times
            if len(parts) < 3:
                # 兼容旧格式（无 ACTION 前缀）
                tag = "事实"
                content = parts[1].strip() if len(parts) == 2 else parts[0].strip()
                action = "ADD"
            else:
                action = parts[0].strip().upper()
                tag = parts[1].strip()
                content = parts[2].strip()

            # 清理 markdown
            content = re.sub(r'\*\*(.*?)\*\*', r'\1', content)
            content = re.sub(r'^\s*>+\s*', '', content, flags=re.MULTILINE)
            content = re.sub(r'^\s*[-*]\s*', '', content)
            content = content.strip()

            if not content or action == "NOOP":
                continue

            imp = importance
            if source == "dream":
                imp = 0.8

            if action == "ADD":
                memory_id = self.ltm.store(
                    content=content, source=source, tags=[tag],
                    importance=imp, user_id=user_id,
                )
                logger.info("[Memory ADD] #%d: %.50s", memory_id, content)
                ids.append(memory_id)

            elif action in ("UPDATE", "MERGE", "DELETE"):
                # 找目标记忆（只做一次 recall）
                similar = self.ltm.recall(content, user_id=user_id, top_k=3)
                if not similar:
                    # 没找到类似记忆，降级为 ADD
                    memory_id = self.ltm.store(
                        content=content, source=source, tags=[tag],
                        importance=imp, user_id=user_id,
                    )
                    logger.info("[Memory ADD(fallback)] #%d: %.50s", memory_id, content)
                    ids.append(memory_id)
                    continue

                old = similar[0]

                if action == "UPDATE":
                    # UPDATE 时提炼核心事实，丢弃确认/纠正类元信息
                    clean = self._llm_update_content(old["content"], content)
                    self.ltm.save_history(old["id"], old["content"], "UPDATE")
                    self.ltm.update_content(old["id"], clean)
                    logger.info("[Memory UPDATE] #%d: %.50s", old["id"], clean)
                    ids.append(old["id"])

                elif action == "MERGE":
                    merged = self._llm_merge(old["content"], content)
                    self.ltm.save_history(old["id"], old["content"], "MERGE")
                    self.ltm.update_content(old["id"], merged)
                    logger.info("[Memory MERGE] #%d: %.50s", old["id"], merged)
                    ids.append(old["id"])

                else:  # DELETE
                    self.ltm.save_history(old["id"], old["content"], "DELETE")
                    self.ltm.soft_delete(old["id"])
                    logger.info("[Memory DELETE] #%d", old["id"])

        if ids:
            logger.info(
                "Extracted %d memories [%s] for user=%s",
                len(ids), source, user_id,
            )
        return ids
