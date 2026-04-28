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

# 集中化提示词
from xiaomei_brain.prompts import (
    IMMEDIATE_EXTRACT_PROMPT,
    PERIODIC_EXTRACT_PROMPT,
    EVERY_TURN_EXTRACT_PROMPT,
    DREAM_EXTRACT_PROMPT,
    TASK_COMPLETION_PROMPT,
    MEMORY_DECISION_PROMPT,
)

logger = logging.getLogger(__name__)

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
                log_level=logging.DEBUG,
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
                recent_memories = "\n".join(f"- [{m['id']}] {m['content']}" for m in existing)
            prompt = PERIODIC_EXTRACT_PROMPT.format(
                messages=formatted,
                recent_memories=recent_memories or "（无已有记忆）",
            )
            result = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
                log_level=logging.DEBUG,
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
                recent_memories = "\n".join(f"- [{m['id']}] {m['content']}" for m in existing)

            prompt = DREAM_EXTRACT_PROMPT.format(
                messages=formatted,
                recent_memories=recent_memories or "（无已有记忆）",
            )
            result = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
                log_level=logging.DEBUG,
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
    ) -> list[int]:
        """每轮对话后调用。一次 LLM 调用完成提取+决策。

        同时从用户输入和助手回复中提取：
        - 用户输入 → 用户的事实/偏好/经历
        - 助手回复 → 小美学到的经验/教训/决策/自我认知

        Args:
            user_input: 当前用户输入
            assistant_response: 当前助手回复
            user_id: 用户标识
            context_turns: 上下文取最近几条消息（帮助理解语境）
        """
        if not self.ltm or not self.llm:
            return []

        try:
            # 获取已有记忆供 LLM 参考（做决策用）
            recent_memories = ""
            if self.ltm:
                existing = self.ltm.get_recent(10, user_id=user_id)
                if existing:
                    recent_memories = "\n".join(
                        f"- [{m['id']}] {m['content']}" for m in existing
                    )

            prompt = EVERY_TURN_EXTRACT_PROMPT.format(
                recent_memories=recent_memories or "（无已有记忆）",
                user_input=user_input[:500],
                assistant_response=assistant_response[:500],
            )
            result = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
                log_level=logging.DEBUG,
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

    @staticmethod
    def _simple_merge(old_content: str, new_content: str) -> str:
        """简单拼接两条记忆。"""
        return f"{old_content}\n{new_content}"

    @staticmethod
    def _simple_update(old_content: str, new_content: str) -> str:
        """直接用新内容覆盖。"""
        return new_content

    def _execute_actions(
        self, llm_output: str, source: str = "manual",
        importance: float = 0.5, user_id: str = "global",
    ) -> list[int]:
        """解析 LLM 输出，直接执行操作。

        支持两种格式：
        1. JSON（优先）: {"relations": [...], "actions": [...]}
        2. 行格式（兼容）: RELATES|...|<--type-->|...  /  ACTION|tag|content

        两阶段：第一阶段处理所有记忆操作，第二阶段处理语义关系。
        """
        if not llm_output or llm_output.strip() in ("无", "无\n", "无\r"):
            return []

        # ── 尝试 JSON 格式 ──────────────────────────────────────────────
        parsed = self._parse_json_actions(llm_output)
        if parsed:
            ids, content_to_id = self._execute_json_actions(parsed, source, importance, user_id)
            for rel in parsed.get("relations", []):
                self._execute_json_relation(rel, content_to_id, user_id)
            return ids

        # ── 回退：行格式 ────────────────────────────────────────────────
        return self._execute_line_actions(llm_output, source, importance, user_id)

    def _parse_json_actions(self, llm_output: str) -> dict | None:
        """从 LLM 输出中解析 JSON 格式的动作列表。

        Returns parsed dict or None if not valid JSON.
        """
        import json, re
        block = llm_output.strip()

        # 尝试直接解析
        try:
            data = json.loads(block)
            if isinstance(data, dict) and ("actions" in data or "relations" in data):
                return data
        except json.JSONDecodeError:
            pass

        # 尝试从 <MEMORY> block 中提取
        m = re.search(r'<MEMORY>\s*(\{.*?\})\s*</MEMORY>', block, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass

        # 尝试从 markdown 代码块中提取
        m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', block, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass

        # ── Truncated JSON salvage ──────────────────────────────────────
        # JSON 被截断时，尝试用正则提取 actions 列表中完整的条目
        salvage = self._salvage_truncated_json(block)
        if salvage:
            return salvage

        return None

    def _salvage_truncated_json(self, block: str) -> dict | None:
        """从被截断的 JSON 中 salvage 尽可能多的 actions。

        处理情况：
        - '{"actions": [{"type": "ADD", "tag": "偏好", "content": "用户喜欢川菜"'  (缺尾 }])
        - '{"actions": [{"type": "ADD", "tag": "事实", "content": "用户去过巴黎"' (缺尾 }])
        """
        import re

        actions = []
        # 匹配完整的 action 条目：type + tag + content 都已闭合（引号内可以有 |）
        # content 值可能在双引号内包含复杂内容，用非贪婪匹配到下一个 "}" 前的 "
        action_pattern = re.compile(
            r'\{"type":\s*"(\w+)"[^}]*?"tag":\s*"([^"]+)"[^}]*?"content":\s*"([^"]*)"',
            re.DOTALL,
        )
        for m in action_pattern.finditer(block):
            actions.append({
                "type": m.group(1).strip(),
                "tag": m.group(2).strip(),
                "content": m.group(3).strip(),
            })

        if not actions:
            return None

        logger.debug("[Memory JSON] Salvaged %d truncated actions", len(actions))
        return {"actions": actions, "relations": []}

    def _execute_json_actions(
        self, parsed: dict, source: str, importance: float, user_id: str,
    ) -> tuple[list[int], dict[str, int]]:
        """执行 JSON 格式的动作列表。

        Returns (memory_ids, content_to_id_map).
        """
        import re

        ids: list[int] = []
        content_to_id: dict[str, int] = {}
        imp = importance
        if source == "dream":
            imp = 0.8

        actions = parsed.get("actions", [])
        if not isinstance(actions, list):
            actions = []

        for action_item in actions:
            if not isinstance(action_item, dict):
                continue

            action_type = action_item.get("type", "").upper()
            tag = action_item.get("tag", "事实")
            content = action_item.get("content", "").strip()

            # 清理 markdown
            content = re.sub(r'\*\*(.*?)\*\*', r'\1', content)
            content = re.sub(r'^\s*>+\s*', '', content, flags=re.MULTILINE)
            content = re.sub(r'^\s*[-*]\s*', '', content)
            content = content.strip()

            if not content or action_type == "NOOP":
                continue

            if action_type == "ADD":
                is_dup = False
                try:
                    existing = self.ltm.recall(content, user_id=user_id, top_k=3)
                    if existing and existing[0].get("score", 0) > 0.85:
                        old = existing[0]
                        logger.info(
                            "[Memory DEDUP JSON] #%d score=%.2f -> UPDATE instead of ADD: %.50s",
                            old["id"], existing[0]["score"], content,
                        )
                        clean = self._simple_update(old["content"], content)
                        self.ltm.save_history(old["id"], old["content"], "UPDATE")
                        self.ltm.update_content(old["id"], clean)
                        ids.append(old["id"])
                        is_dup = True
                except Exception as e:
                    logger.debug("[Memory DEDUP JSON] recall failed: %s", e)

                if not is_dup:
                    memory_id = self.ltm.store(
                        content=content, source=source, tags=[tag],
                        importance=imp, user_id=user_id,
                    )
                    logger.info("[Memory ADD JSON] #%d: %.50s", memory_id, content)
                    ids.append(memory_id)
                    if len(content) >= 5:
                        content_to_id[content[:50]] = memory_id

            elif action_type in ("UPDATE", "MERGE", "DELETE"):
                similar = self.ltm.recall(content, user_id=user_id, top_k=3)
                if not similar:
                    memory_id = self.ltm.store(
                        content=content, source=source, tags=[tag],
                        importance=imp, user_id=user_id,
                    )
                    logger.info("[Memory ADD JSON(fallback)] #%d: %.50s", memory_id, content)
                    ids.append(memory_id)
                    if len(content) >= 5:
                        content_to_id[content[:50]] = memory_id
                    continue

                old = similar[0]

                if action_type == "UPDATE":
                    clean = self._simple_update(old["content"], content)
                    self.ltm.save_history(old["id"], old["content"], "UPDATE")
                    self.ltm.update_content(old["id"], clean)
                    logger.info("[Memory UPDATE JSON] #%d: %.50s", old["id"], clean)
                    ids.append(old["id"])

                elif action_type == "MERGE":
                    merged = self._simple_merge(old["content"], content)
                    self.ltm.save_history(old["id"], old["content"], "MERGE")
                    self.ltm.update_content(old["id"], merged)
                    logger.info("[Memory MERGE JSON] #%d: %.50s", old["id"], merged)
                    ids.append(old["id"])

                else:  # DELETE
                    self.ltm.save_history(old["id"], old["content"], "DELETE")
                    self.ltm.soft_delete(old["id"])
                    logger.info("[Memory DELETE JSON] #%d", old["id"])

        return ids, content_to_id

    def _execute_json_relation(
        self, rel: dict, content_to_id: dict[str, int], user_id: str,
    ) -> None:
        """执行一条 JSON 格式的 relation，建立语义边。"""
        from_content = rel.get("from", "").strip()
        relation_type = rel.get("type", "").strip().lower()
        to_content = rel.get("to", "").strip()

        if not from_content or not to_content or not relation_type:
            return
        if relation_type not in self.ltm.VALID_RELATION_TYPES:
            logger.debug("[Relations JSON] Invalid type: %s", relation_type)
            return

        # 找 from_memory_id（只找最匹配的1个用于建立关系）
        from_memory_id: int | None = None
        for snippet, mid in content_to_id.items():
            if from_content[:30] in snippet or snippet[:30] in from_content[:30]:
                from_memory_id = mid
                break
        if from_memory_id is None:
            similar = self.ltm.recall(from_content, user_id=user_id, top_k=1)
            if similar:
                from_memory_id = similar[0]["id"]

        # 找 to_memory_id（只找最匹配的1个用于建立关系）
        to_memory_id: int | None = None
        similar_to = self.ltm.recall(to_content, user_id=user_id, top_k=1)
        if similar_to:
            to_memory_id = similar_to[0]["id"]

        self._do_add_relation(from_content, relation_type, to_content, user_id, from_memory_id, to_memory_id)

    # ── 回退：行格式处理（保留兼容旧 LLM 输出） ────────────────────────

    def _execute_line_actions(
        self, llm_output: str, source: str = "manual",
        importance: float = 0.5, user_id: str = "global",
    ) -> list[int]:
        """行格式的动作解析（回退路径）。"""
        import re

        ids: list[int] = []
        relates_lines: list[str] = []
        content_to_id: dict[str, int] = {}

        for line in llm_output.strip().split("\n"):
            line = line.strip()
            if not line or line == "无":
                continue
            if line.startswith("**") or line.startswith("#"):
                continue
            if line.upper().startswith("RELATES"):
                relates_lines.append(line)
                continue

            all_parts = line.split("|")
            if len(all_parts) >= 3 and all_parts[0].strip().upper() in ("ADD", "UPDATE", "MERGE", "DELETE", "NOOP"):
                action = all_parts[0].strip().upper()
                tag = all_parts[1].strip()
                content = "|".join(all_parts[2:]).strip()
            elif len(all_parts) < 3:
                tag = "事实"
                content = all_parts[1].strip() if len(all_parts) == 2 else all_parts[0].strip()
                action = "ADD"
            else:
                tag = "事实"
                content = "|".join(all_parts[1:]).strip()
                action = "ADD"

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
                is_dup = False
                try:
                    existing = self.ltm.recall(content, user_id=user_id, top_k=3)
                    if existing and existing[0].get("score", 0) > 0.85:
                        old = existing[0]
                        logger.info(
                            "[Memory DEDUP] #%d score=%.2f -> UPDATE instead of ADD: %.50s",
                            old["id"], existing[0]["score"], content,
                        )
                        clean = self._simple_update(old["content"], content)
                        self.ltm.save_history(old["id"], old["content"], "UPDATE")
                        self.ltm.update_content(old["id"], clean)
                        ids.append(old["id"])
                        is_dup = True
                except Exception as e:
                    logger.debug("[Memory DEDUP] recall failed, fallback to ADD: %s", e)

                if not is_dup:
                    memory_id = self.ltm.store(
                        content=content, source=source, tags=[tag],
                        importance=imp, user_id=user_id,
                    )
                    logger.info("[Memory ADD] #%d: %.50s", memory_id, content)
                    ids.append(memory_id)
                    if len(content) >= 5:
                        content_to_id[content[:50]] = memory_id

            elif action in ("UPDATE", "MERGE", "DELETE"):
                similar = self.ltm.recall(content, user_id=user_id, top_k=3)
                if not similar:
                    memory_id = self.ltm.store(
                        content=content, source=source, tags=[tag],
                        importance=imp, user_id=user_id,
                    )
                    logger.info("[Memory ADD(fallback)] #%d: %.50s", memory_id, content)
                    ids.append(memory_id)
                    if len(content) >= 5:
                        content_to_id[content[:50]] = memory_id
                    continue

                old = similar[0]

                if action == "UPDATE":
                    clean = self._simple_update(old["content"], content)
                    self.ltm.save_history(old["id"], old["content"], "UPDATE")
                    self.ltm.update_content(old["id"], clean)
                    logger.info("[Memory UPDATE] #%d: %.50s", old["id"], clean)
                    ids.append(old["id"])

                elif action == "MERGE":
                    merged = self._simple_merge(old["content"], content)
                    self.ltm.save_history(old["id"], old["content"], "MERGE")
                    self.ltm.update_content(old["id"], merged)
                    logger.info("[Memory MERGE] #%d: %.50s", old["id"], merged)
                    ids.append(old["id"])

                else:
                    self.ltm.save_history(old["id"], old["content"], "DELETE")
                    self.ltm.soft_delete(old["id"])
                    logger.info("[Memory DELETE] #%d", old["id"])

        for rel_line in relates_lines:
            self._execute_line_relate(rel_line, content_to_id, user_id)

        if ids:
            logger.debug(
                "Extracted %d memories [%s] for user=%s",
                len(ids), source, user_id,
            )
        return ids

    def _execute_line_relate(
        self,
        rel_line: str,
        content_to_id: dict[str, int],
        user_id: str,
    ) -> None:
        """解析并执行一条 RELATES 行，在记忆之间建立语义边。

        格式: RELATES|<from_content>|--<type-->|<to_content>
        例: RELATES|用户喜欢吃川菜|--causal-->|用户出差去成都
        """
        import re

        # 解析 RELATES|<from>|--<type-->|<to>
        # 支持两种分隔符格式：--type--> 和 <--type-->
        m = re.match(
            r'^RELATES\s*\|\s*(.+?)\s*\|--([a-zA-Z_]+)-->+\s*\|\s*(.+)$',
            rel_line,
            re.IGNORECASE,
        )
        if not m:
            # 尝试 <--type--> 格式（你改的格式）
            m = re.match(
                r'^RELATES\s*\|\s*(.+?)\s*\|<--([a-zA-Z_]+)-->+\s*\|\s*(.+)$',
                rel_line,
                re.IGNORECASE,
            )
        if not m:
            # 容错：截断的 RELATES 行（如 "RELATES|...|cont'" 末尾被截断）
            # 尝试从已知的 relation_type 前缀猜测
            truncated = re.match(
                r'^RELATES\s*\|\s*(.+?)\s*\|--([a-zA-Z_]+)\s*\|?\s*$',
                rel_line,
                re.IGNORECASE,
            )
            if truncated:
                from_content = truncated.group(1).strip()
                partial_type = truncated.group(2).strip().lower()
                # 从 partial_type 补全为完整的 relation_type
                candidates = [t for t in self.ltm.VALID_RELATION_TYPES if t.startswith(partial_type)]
                if len(candidates) == 1:
                    relation_type = candidates[0]
                    logger.info("[Relations] Recovered truncated RELATES with type=%s: %s", relation_type, from_content)
                    # 此时缺少 to_content，无法建立完整关系，跳过
                    logger.debug("[Relations] Skip: truncated RELATES has no to_content")
                    return
            # 容错：缺尾部 | 的情况，如 "RELATES|用户去过巴黎|<--causal-->|用户去过巴黎"
            missing_pipe = re.match(
                r'^RELATES\s*\|\s*(.+?)\s*\|<--([a-zA-Z_]+)-->\s*\|\s*(.+)$',
                rel_line,
                re.IGNORECASE,
            )
            if missing_pipe:
                from_content = missing_pipe.group(1).strip()
                relation_type = missing_pipe.group(2).strip().lower()
                to_content = missing_pipe.group(3).strip()
                if relation_type in self.ltm.VALID_RELATION_TYPES and from_content and to_content:
                    logger.info("[Relations] Missing trailing pipe, recovered: from=%s type=%s to=%s",
                                 from_content, relation_type, to_content)
                    # to_content 可能残缺，但交给 _do_add_relation 内部的 recall 处理
                    self._do_add_relation(from_content, relation_type, to_content, user_id)
                    return
            logger.debug("[Relations] Failed to parse RELATES line: %s", rel_line)
            return

        from_content = m.group(1).strip()
        relation_type = m.group(2).strip().lower()
        to_content = m.group(3).strip()

        if not from_content or not to_content or not relation_type:
            return

        if relation_type not in self.ltm.VALID_RELATION_TYPES:
            logger.debug("[Relations] Invalid relation_type: %s", relation_type)
            return

        # 找 from_memory_id：优先从刚创建的记忆匹配，否则 recall
        from_memory_id: int | None = None
        for snippet, mid in content_to_id.items():
            if from_content[:30] in snippet or snippet[:30] in from_content[:30]:
                from_memory_id = mid
                break

        if from_memory_id is None:
            # 降级：从 to_content 的相似记忆反推，或直接 recall from_content
            similar = self.ltm.recall(from_content, user_id=user_id, top_k=1)
            if similar:
                from_memory_id = similar[0]["id"]

        # 找 to_memory_id：recall（只找最匹配的1个用于建立关系）
        to_memory_id: int | None = None
        similar_to = self.ltm.recall(to_content, user_id=user_id, top_k=1)
        if similar_to:
            to_memory_id = similar_to[0]["id"]

        self._do_add_relation(from_content, relation_type, to_content, user_id, from_memory_id, to_memory_id)

    def _do_add_relation(
        self,
        from_content: str,
        relation_type: str,
        to_content: str,
        user_id: str,
        from_memory_id: int | None = None,
        to_memory_id: int | None = None,
    ) -> None:
        """实际执行建立关系（供外部调用或内部重试）"""
        if from_memory_id is None or to_memory_id is None:
            logger.debug(
                "[Relations] Skip: from_id=%s to_id=%s",
                from_memory_id, to_memory_id,
            )
            return

        if from_memory_id == to_memory_id:
            logger.debug("[Relations] Skip: self-loop #%d", from_memory_id)
            return

        rel_id = self.ltm.add_relation(
            from_memory_id=from_memory_id,
            to_memory_id=to_memory_id,
            relation_type=relation_type,
            context=f"from:{from_content[:40]} to:{to_content[:40]}",
        )
        if rel_id:
            logger.info(
                "[Relations] Linked #%d --%s--> #%d (rel=#%d)",
                from_memory_id, relation_type, to_memory_id, rel_id,
            )

    # ── 合并模式：解析 MEMORY block ─────────────────────────────────────

    @staticmethod
    def extract_memory_block(content: str) -> tuple[str, str]:
        """从 LLM 回复内容中提取 MEMORY block。

        Returns:
            (memory_block, clean_content) — block 为空则表示无有效决策
        """
        if not content:
            return "", ""
        m_start = content.rfind("<MEMORY>")
        if m_start == -1:
            return "", content
        m_end = content.rfind("</MEMORY>")
        if m_end == -1:
            return "", content
        block = content[m_start + 8:m_end].strip()
        # Remove MEMORY block from content (handle case where MEMORY is at start)
        clean = (content[:m_start] + content[m_end + 9:]).strip()
        return block, clean

    def execute_block(self, memory_block: str, user_id: str = "global") -> list[int]:
        """执行 MEMORY block（合并模式，无需调 LLM）。

        判断是否有有效 ACTION，有则执行，无则跳过。
        支持：行格式（ADD|UPDATE|MERGE|DELETE）和 JSON 格式（{"actions": [...]})。
        """
        block_clean = memory_block.strip()
        if not block_clean:
            return []

        # ── JSON 格式检测 ─────────────────────────────────────────────
        try:
            import json
            data = json.loads(block_clean)
            if isinstance(data, dict) and ("actions" in data or "relations" in data):
                return self._execute_actions(memory_block, source="merged", user_id=user_id)
        except json.JSONDecodeError:
            pass

        # ── 截断 JSON salvage（直接从 block 提取，不走 _execute_actions） ─
        parsed = self._parse_json_actions(memory_block)
        if parsed and parsed.get("actions"):
            ids, content_to_id = self._execute_json_actions(parsed, source="merged", importance=0.5, user_id=user_id)
            for rel in parsed.get("relations", []):
                self._execute_json_relation(rel, content_to_id, user_id)
            return ids

        # ── 行格式检测 ────────────────────────────────────────────────
        valid_actions = ("ADD|", "UPDATE|", "MERGE|", "DELETE|")
        has_valid = False
        has_relates = False
        for line in block_clean.split("\n"):
            stripped = line.strip().upper()
            if any(stripped.startswith(action) for action in valid_actions):
                has_valid = True
            if stripped.startswith("RELATES"):
                has_relates = True

        if not has_valid and not has_relates:
            return []

        return self._execute_actions(memory_block, source="merged", user_id=user_id)

    # ── Task 完成提取 ─────────────────────────────────────────────

    def extract_task_completion(
        self,
        task: Any,  # Task from consciousness.task
        user_id: str = "global",
    ) -> list[int]:
        """Task 完成时：从认知日志中提取经验/模式/用户洞察。

        调用 LLM 总结 cognitive_log + artifacts，提取值得长期保存的知识：
        1. 学到的技术/经验 → tag=经验
        2. 踩了什么坑 → tag=教训
        3. 对用户的新发现 → tag=用户洞察
        4. 可复用的模式 → tag=模式
        5. 自我的变化/成长 → tag=自我认知

        Args:
            task: Task 对象（consciousness.task.Task）
            user_id: 用户标识

        Returns:
            新创建的记忆 ID 列表
        """
        if not self.ltm or not self.llm:
            return []

        try:
            # 格式化认知日志
            log_text = self._format_cognitive_log(task.cognitive_log)
            if not log_text:
                logger.info("[TaskComplete] 无认知日志，跳过知识提取")
                return []

            # 格式化产出物
            artifact_text = self._format_artifacts(task.artifacts)

            # 获取已有记忆供参考
            recent_memories = ""
            existing = self.ltm.get_recent(15, user_id=user_id)
            if existing:
                recent_memories = "\n".join(
                    f"- [{m['id']}] {m['content']}" for m in existing
                )

            prompt = TASK_COMPLETION_PROMPT.format(
                task_description=task.description,
                task_type=task.type.value,
                cognitive_log=log_text,
                artifacts=artifact_text,
                recent_memories=recent_memories or "（无已有记忆）",
            )

            result = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
                log_level=logging.DEBUG,
            )

            ids = self._execute_actions(
                result.content or "", source="task_completion", user_id=user_id,
            )

            if ids:
                logger.info(
                    "[TaskComplete] 从 Task「%s」提取了 %d 条记忆",
                    task.description[:40], len(ids),
                )
            else:
                logger.info(
                    "[TaskComplete] Task「%s」无值得长期保存的知识",
                    task.description[:40],
                )
            return ids
        except Exception as e:
            logger.error("[TaskComplete] 知识提取失败: %s", e)
            return []

    @staticmethod
    def _format_cognitive_log(log: list) -> str:
        """格式化认知日志为文本"""
        if not log:
            return ""
        lines = []
        type_labels = {
            "decision":  "决策",
            "discovery": "发现",
            "pitfall":   "踩坑",
            "output":    "产出",
            "note":      "备注",
        }
        for entry in log:
            label = type_labels.get(entry.entry_type, entry.entry_type)
            lines.append(f"[{label}] {entry.content}")
        return "\n".join(lines)

    @staticmethod
    def _format_artifacts(artifacts: list[dict]) -> str:
        """格式化产出物列表为文本"""
        if not artifacts:
            return "（无产出物）"
        lines = []
        for a in artifacts:
            lines.append(f"  - {a.get('path', '?')} ({a.get('role', 'output')})")
        return "\n".join(lines)
