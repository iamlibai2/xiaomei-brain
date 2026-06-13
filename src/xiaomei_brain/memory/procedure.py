"""ProcedureMemory: procedural memory — learn and execute standard workflows.

Architecture:
- SQLite (brain.db): procedures table — name, description, trigger_config, steps, etc.
- Learn from: conversation history + LLM generation (via RoundScheduler, every 15 turns)
- Trigger: keyword matching (O(N) scan, no vector needed)
- Execute: inject top-3 procedures into context, LLM decides whether to use

Design principles:
1. Simulate human learning: learn after process completes, not during
2. No confirmation activation: LLM generates and activates directly
3. Trigger by keywords only: no vector, semantic generalization not core value
4. Dream module focuses on consolidation: extraction via L2 tick, not dream
"""

from __future__ import annotations

import json
import logging
import random
import re
import sqlite3
import time
from typing import Any

from xiaomei_brain.base.sqlite_store import SQLiteStore

logger = logging.getLogger("xiaomei_brain.procedure")

_P_LOG = "\033[91m[Procedure]\033[0m"  # 红色标签


def _plog(msg: str, *args) -> str:
    """Format log message with red Procedure tag."""
    return f"{_P_LOG} {msg}" % (args if args else ())

from ..prompts import (
    PROCEDURE_LEARN_PROMPT as _PROCEDURE_LEARN_PROMPT,
    PROCEDURE_GENERATE_PROMPT as _PROCEDURE_GENERATE_PROMPT,
)

# ── Response parsing ──────────────────────────────────────────

_PROC_TAG_RE = re.compile(r"<PROC>([^<]+)</PROC>", re.IGNORECASE)


def extract_procedure_block(response: str) -> str | None:
    """Extract first <PROC>xxx</PROC> tag from LLM response.

    Returns the procedure id (e.g. "PROC-123") if found, else None.
    """
    if not response:
        return None
    m = _PROC_TAG_RE.search(response)
    if m:
        logger.info("%s extracted tag: %s", _P_LOG, m.group(1))
        return m.group(1).strip()
    return None


# ── Condition matching ───────────────────────────────────────────

_OPERATORS = {
    "contains": lambda v, text: v in text,
    "startswith": lambda v, text: text.startswith(v),
    "endswith": lambda v, text: text.endswith(v),
    "regex": lambda v, text: bool(re.search(v, text)),
}


def _match_condition(condition: dict, user_message: str) -> bool:
    """Match a single condition against user_message."""
    field = condition.get("field", "user_message")
    if field != "user_message":
        return False
    operator = condition.get("operator", "contains")
    value = condition.get("value", "")
    if operator not in _OPERATORS:
        return False
    return _OPERATORS[operator](value, user_message)


def _match_trigger_config(config: dict, user_message: str) -> bool:
    """Match trigger_config against user_message. Returns True if matched."""
    conditions = config.get("conditions", [])
    if not conditions:
        return False
    match_type = config.get("type", "any")
    results = [_match_condition(c, user_message) for c in conditions]
    if match_type == "all":
        return all(results)
    else:  # any
        return any(results)


# ── Trigger keyword validation ──────────────────────────────────

# Keywords that are too generic to be useful triggers (high-frequency daily words)
_BANNED_TRIGGER_WORDS = {
    "今天", "明天", "昨天", "心情", "分享", "试试", "喜欢", "想要",
    "觉得", "知道", "记得", "看一下", "看看", "你好", "晚安", "早安",
    "在吗", "怎么", "什么", "为什么", "真的", "可能", "应该",
    "帮忙", "帮我", "需要", "感觉", "一直", "还是", "一点",
    "最近", "好像", "现在", "下次", "以后", "每次", "一起",
    "想", "累", "梦", "茶", "歌", "爱", "怕", "忘", "困", "饿",
}


def _validate_trigger_keywords(conditions: list[dict], proc_name: str) -> list[dict]:
    """Validate and filter trigger keywords.

    Removes single-character keywords and known high-frequency words.
    Logs warnings for removed keywords.
    """
    if not conditions:
        return conditions

    filtered = []
    for c in conditions:
        value = c.get("value", "")
        if not value:
            continue
        # Single CJK character
        if len(value) < 2:
            logger.warning(
                "%s '%s' keyword '%s' removed: single character is too generic",
                _P_LOG, proc_name, value,
            )
            continue
        # Known high-frequency word
        if value in _BANNED_TRIGGER_WORDS:
            logger.warning(
                "%s '%s' keyword '%s' removed: high-frequency generic word",
                _P_LOG, proc_name, value,
            )
            continue
        filtered.append(c)

    if len(filtered) < len(conditions):
        logger.info(
            "%s '%s' keywords filtered: %d → %d",
            _P_LOG, proc_name, len(conditions), len(filtered),
        )

    # If all keywords were filtered, log error but still return the last 2
    # (better to have suboptimal triggers than skip the procedure entirely)
    if not filtered:
        logger.error(
            "%s '%s' ALL keywords filtered out, keeping original (needs manual review)",
            _P_LOG, proc_name,
        )
        return conditions

    return filtered


# ── ProcedureStore ────────────────────────────────────────────────


class ProcedureStore(SQLiteStore):
    """CRUD operations for procedures table."""

    def __init__(self, db_path: str) -> None:
        super().__init__(db_path)

    def _init_table(self) -> None:
        conn = self._get_conn()

        # 迁移：procedures → procedure_memories
        existing = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='procedures'"
        ).fetchone()
        if existing:
            conn.execute("ALTER TABLE procedures RENAME TO procedure_memories")

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS procedure_memories (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                trigger_config TEXT DEFAULT '{}',
                steps TEXT NOT NULL DEFAULT '[]',
                scope TEXT DEFAULT 'agent',
                execution_count INTEGER DEFAULT 0,
                execution_success_rate REAL DEFAULT 0.0,
                weight REAL DEFAULT 0.5,
                status TEXT DEFAULT 'active',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                last_executed REAL,
                version INTEGER DEFAULT 1,
                version_history TEXT DEFAULT '[]',
                execution_log TEXT DEFAULT '[]'
            );
            CREATE INDEX IF NOT EXISTS idx_procedure_memories_status ON procedure_memories(status);
            CREATE INDEX IF NOT EXISTS idx_procedure_memories_weight ON procedure_memories(weight);
            CREATE INDEX IF NOT EXISTS idx_procedure_memories_updated ON procedure_memories(updated_at);
        """)
        conn.commit()

    # ── CRUD ──────────────────────────────────────────────────────

    def store(self, procedure: dict) -> str:
        """Store a procedure. Returns procedure id."""
        conn = self._get_conn()
        now = time.time()
        proc_id = procedure.get("id")
        if not proc_id:
            proc_id = f"PROC-{int(now * 1000)}"

        trigger_config = procedure.get("trigger_config", {})
        steps = procedure.get("steps", [])
        version_history = procedure.get("version_history", [])

        conn.execute("""
            INSERT OR REPLACE INTO procedure_memories
            (id, name, description, trigger_config, steps, scope,
             execution_count, execution_success_rate, weight, status,
             created_at, updated_at, last_executed, version, version_history, execution_log)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            proc_id,
            procedure.get("name", ""),
            procedure.get("description", ""),
            json.dumps(trigger_config, ensure_ascii=False),
            json.dumps(steps, ensure_ascii=False),
            procedure.get("scope", "agent"),
            procedure.get("execution_count", 0),
            procedure.get("execution_success_rate", 0.0),
            procedure.get("weight", 0.5),
            procedure.get("status", "active"),
            now,
            now,
            procedure.get("last_executed"),
            procedure.get("version", 1),
            json.dumps(version_history, ensure_ascii=False),
            json.dumps(procedure.get("execution_log", []), ensure_ascii=False),
        ))
        conn.commit()
        logger.info("%s Stored %s: %s", _P_LOG, proc_id, procedure.get("name", ""))
        return proc_id

    def get(self, proc_id: str) -> dict | None:
        """Get a procedure by id."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM procedure_memories WHERE id = ?", (proc_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def get_all_active(self) -> list[dict]:
        """Get all active procedures."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM procedure_memories WHERE status = 'active' ORDER BY weight DESC"
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def update_execution(
        self,
        proc_id: str,
        result: str,  # success | failed | interrupted
        notes: str = "",
    ) -> None:
        """Update execution stats: count, success_rate, weight, log, last_executed."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT execution_count, execution_success_rate, weight, execution_log FROM procedure_memories WHERE id = ?",
            (proc_id,)
        ).fetchone()
        if not row:
            return

        count = row["execution_count"] + 1
        old_rate = row["execution_success_rate"] or 0.0
        weight = row["weight"] or 0.5

        # Recalculate success_rate
        if result == "success":
            new_rate = (old_rate * (count - 1) + 1.0) / count
            new_weight = min(0.95, weight + 0.05)
        elif result == "failed":
            new_rate = (old_rate * (count - 1) + 0.0) / count
            new_weight = max(0.05, weight - 0.10)
        else:  # interrupted
            new_rate = old_rate
            new_weight = weight

        # Append to execution_log (keep last 20)
        log = json.loads(row["execution_log"] or "[]")
        log.append({
            "timestamp": time.time(),
            "result": result,
            "user_feedback": None,
            "notes": notes,
        })
        if len(log) > 20:
            log = log[-20:]

        conn.execute("""
            UPDATE procedure_memories
            SET execution_count = ?,
                execution_success_rate = ?,
                weight = ?,
                last_executed = ?,
                execution_log = ?
            WHERE id = ?
        """, (
            count,
            new_rate,
            new_weight,
            time.time(),
            json.dumps(log, ensure_ascii=False),
            proc_id,
        ))
        conn.commit()
        logger.info(
            "%s Updated %s: count=%d rate=%.2f weight=%.2f result=%s",
            _P_LOG, proc_id, count, new_rate, new_weight, result,
        )

    def archive_low_weight(self, threshold: float = 0.1) -> int:
        """Archive procedures with weight below threshold. Returns count."""
        conn = self._get_conn()
        cur = conn.execute(
            "UPDATE procedure_memories SET status = 'archived' WHERE weight < ? AND status = 'active'",
            (threshold,)
        )
        conn.commit()
        if cur.rowcount > 0:
            logger.info("%s Archived %d procedures (weight < %.2f)", _P_LOG, cur.rowcount, threshold)
        return cur.rowcount

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["trigger_config"] = json.loads(d.get("trigger_config", "{}"))
        d["steps"] = json.loads(d.get("steps", "[]"))
        d["version_history"] = json.loads(d.get("version_history", "[]"))
        d["execution_log"] = json.loads(d.get("execution_log", "[]"))
        return d


# ── ProcedureMatcher ───────────────────────────────────────────────


class ProcedureMatcher:
    """语义向量 + 关键词 boosted 的过程记忆匹配。"""

    def __init__(self, store: ProcedureStore) -> None:
        self._store = store

    def match(
        self,
        user_message: str,
        top_k: int = 1,
        embed_fn: Any = None,
        threshold: float = 0.6,
    ) -> list[dict]:
        """语义匹配 user_message 与所有活跃过程记忆。

        Args:
            user_message: 用户消息
            top_k: 返回条数（默认 1，激活最匹配的一个）
            embed_fn: 文本→归一化向量的嵌入函数，None 时回退关键词匹配
            threshold: 余弦相似度阈值，低于此值的不入选

        Returns:
            匹配到的过程记忆列表，按 weight × similarity 排序
        """
        all_active = self._store.get_all_active()
        if not all_active:
            return []

        if embed_fn:
            return self._semantic_match(
                user_message, all_active, top_k, embed_fn, threshold,
            )

        # 回退：纯关键词匹配（embed_fn 不可用时）
        return self._keyword_match(user_message, all_active, top_k)

    def _semantic_match(
        self,
        user_message: str,
        all_active: list[dict],
        top_k: int,
        embed_fn,
        threshold: float,
    ) -> list[dict]:
        """向量语义匹配 + 关键词 boost。"""
        import numpy as np

        try:
            query_vec = np.array(embed_fn(user_message))
        except Exception as e:
            logger.warning("%s Embed query failed, fallback to keyword: %s", _P_LOG, e)
            return self._keyword_match(user_message, all_active, top_k)

        scored = []
        for proc in all_active:
            text = f"{proc['name']}: {proc.get('description', '')}"
            try:
                proc_vec = np.array(embed_fn(text))
                # 向量已归一化，dot product = cosine similarity
                sim = float(np.dot(proc_vec, query_vec))
            except Exception as e:
                logger.debug("%s Embed procedure '%s' failed: %s", _P_LOG, proc.get('name', ''), e)
                continue

            # 关键词精确命中 → boost
            config = proc.get("trigger_config", {})
            if _match_trigger_config(config, user_message):
                sim *= 1.3

            if sim >= threshold:
                weight = proc.get("weight", 0.5)
                scored.append((proc, sim * weight))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [p for p, _ in scored[:top_k]]

    def _keyword_match(
        self,
        user_message: str,
        all_active: list[dict],
        top_k: int,
    ) -> list[dict]:
        """关键词匹配（回退方案）。"""
        matched = []
        for proc in all_active:
            config = proc.get("trigger_config", {})
            if _match_trigger_config(config, user_message):
                matched.append(proc)

        matched.sort(key=lambda p: p.get("weight", 0.5), reverse=True)
        return matched[:top_k]

    def inject_context(self, procedures: list[dict]) -> str:
        """Build context injection string from procedures list."""
        if not procedures:
            return ""
        lines = ["\n## 可用标准流程"]
        for proc in procedures:
            steps_summary = " → ".join(s["name"] for s in proc.get("steps", []))
            lines.append(f"- [{proc['name']}] {proc.get('description', '')}")
            lines.append(f"  步骤：{steps_summary}")

        usage = (
            "\n\n当对方的需求匹配上述某条流程时，可主动按步骤执行。"
            "步骤是指导而非强制——如情况特殊可调整。执行完成后自然告知对方即可。"
        )
        return "\n".join(lines) + usage


# ── ProcedureLearner ──────────────────────────────────────────────


class ProcedureLearner:
    """Learn new procedures from conversation history."""

    def __init__(self, store: ProcedureStore, llm_client: Any = None) -> None:
        self._store = store
        self._llm = llm_client

    def detect_and_learn(
        self,
        conversation_history: list[dict],
        recent_procedures_injected: list[str] | None = None,
    ) -> list[str]:
        """Scan conversation history, generate new procedures if detected.

        Args:
            conversation_history: List of {role, content} dicts
            recent_procedures_injected: IDs of procedures in context (for result inference)

        Returns:
            List of newly created procedure ids.
        """
        if not self._llm:
            logger.warning("%s No LLM client, skipping learn", _P_LOG)
            return []

        history_text = self._format_history(conversation_history)
        detect_prompt = _PROCEDURE_LEARN_PROMPT.format(conversation_history=history_text)
        logger.info("%s 检测对话 (%d msgs)...", _P_LOG, len(conversation_history))
        try:
            resp = self._llm.chat(
                messages=[{"role": "user", "content": detect_prompt}],
                tools=None,
            )
            raw = (resp.content or "").strip()
            data = json.loads(raw or "{}")
        except Exception as e:
            logger.warning("%s 检测失败: %s", _P_LOG, e)
            return []

        teach_intent = data.get("teach_intent", False)
        task_completion = data.get("task_completion", False)
        logger.info("%s 检测结果: teach_intent=%s task_completion=%s", _P_LOG, teach_intent, task_completion)

        if not teach_intent and not task_completion:
            return []

        # Step 2: generate procedure
        if teach_intent:
            focus = f"教学：{data.get('teach_summary', '')}"
        else:
            focus = f"任务：{data.get('task_summary', '')}"

        generate_prompt = _PROCEDURE_GENERATE_PROMPT.format(
            conversation_history=self._format_history(conversation_history)
        )
        try:
            resp2 = self._llm.chat(
                messages=[{"role": "user", "content": generate_prompt}],
                tools=None,
            )
            raw2 = (resp2.content or "").strip()
            proc_data = json.loads(raw2 or "{}")
        except Exception as e:
            logger.info("%s 生成失败: %s", _P_LOG, e)
            return []

        if not proc_data.get("name") or not proc_data.get("steps"):
            logger.warning("%s 生成返回为空: %s", _P_LOG, resp2.content[:80])
            return []

        # Step 2.5: validate trigger keywords — filter out single-char and generic words
        trigger_cfg = proc_data.get("trigger_config", {})
        raw_conditions = trigger_cfg.get("conditions", [])
        if raw_conditions:
            validated = _validate_trigger_keywords(raw_conditions, proc_data["name"])
            proc_data["trigger_config"] = {**trigger_cfg, "conditions": validated}

        # Step 3: deduplicate — skip if name or trigger overlap with recent procedure
        new_name = proc_data.get("name", "")
        new_conditions = proc_data.get("trigger_config", {}).get("conditions", [])
        new_triggers = {c.get("value", "").lower() for c in new_conditions}
        all_active = self._store.get_all_active()
        for existing in all_active:
            existing_cfg = existing.get("trigger_config", {})
            existing_conds = existing_cfg.get("conditions", []) if isinstance(existing_cfg, dict) else []
            existing_triggers = {c.get("value", "").lower() for c in existing_conds}
            overlap = new_triggers & existing_triggers
            if overlap or new_name == existing.get("name", ""):
                logger.info("%s Duplicate detected: '%s' overlaps with '%s' (triggers=%s), skipping", _P_LOG, new_name, existing.get("name", ""), overlap)
                return []

        # Step 4: store
        proc_id = self._store.store(proc_data)
        logger.info(
            "%s Created: %s (%s teach=%s task=%s)",
            _P_LOG, proc_id, proc_data.get("name"), teach_intent, task_completion,
        )
        return [proc_id]

    def infer_execution_result(
        self,
        conversation_history: list[dict],
        injected_procedure_ids: list[str],
    ) -> list[dict]:
        """Infer which procedure was used and the result.

        Args:
            conversation_history: List of {role, content} dicts
            injected_procedure_ids: IDs of procedures that were in context

        Returns:
            List of {procedure_id, result, notes} dicts.
        """
        if not self._llm or not injected_procedure_ids:
            return []

        # Format injected procedures for prompt
        all_active = self._store.get_all_active()
        injected_map = {p["id"]: p for p in all_active if p["id"] in injected_procedure_ids}

        active_str = "\n".join([
            f"- {pid}: {p.get('name', '')} — {p.get('description', '')}"
            for pid, p in injected_map.items()
        ])

        prompt = _PROCEDURE_MATCH_INFERENCE_PROMPT.format(
            conversation_summary=self._format_history(conversation_history[-10:]),
            active_procedures=active_str or "(无)",
        )
        try:
            resp = self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
            )
            raw = (resp.content or "").strip()
            data = json.loads(raw or "{}")
        except Exception as e:
            logger.warning("%s infer failed: %s", _P_LOG, e)
            return []

        used_id = data.get("used_procedure_id")
        result = data.get("result", "none")
        notes = data.get("notes", "")

        if used_id and result != "none":
            self._store.update_execution(used_id, result, notes)
            logger.info(
                "%s Execution inferred: %s -> %s (%s)",
                _P_LOG, used_id, result, notes,
            )
            return [{"procedure_id": used_id, "result": result, "notes": notes}]
        return []

    def _format_history(self, history: list[dict]) -> str:
        lines = []
        for m in history[-20:]:
            role = m.get("role", "unknown")
            content = m.get("content", "")[:300]
            lines.append(f"[{role}] {content}")
        return "\n".join(lines)


# ── Main class ────────────────────────────────────────────────────


class ProcedureMemory:
    """Facade: combines store, matcher, and learner.

    Usage:
        pm = ProcedureMemory(db_path, llm_client)

        # In L2 tick — detect new procedures + infer execution results
        pm.learn_from_conversation(conversation_history, injected_procedure_ids)

        # In context assembly — get matching procedures for user message
        candidates = pm.match(user_message)
        context_hint = pm.inject_context(candidates)
    """

    def __init__(self, db_path: str, llm_client: Any = None) -> None:
        self._store = ProcedureStore(db_path)
        self._store._init_table()
        self._matcher = ProcedureMatcher(self._store)
        self._learner = ProcedureLearner(self._store, llm_client)

    def match(
        self, user_message: str, top_k: int = 1,
        embed_fn: Any = None, threshold: float = 0.6,
    ) -> list[dict]:
        """Match user_message against active procedures. Returns top_k candidates.

        Args:
            user_message: 用户消息
            top_k: 返回条数（默认 1）
            embed_fn: 嵌入函数，None 时回退关键词匹配
            threshold: 余弦相似度阈值
        """
        return self._matcher.match(user_message, top_k, embed_fn=embed_fn, threshold=threshold)

    def inject_context(self, procedures: list[dict]) -> str:
        """Build context injection string."""
        return self._matcher.inject_context(procedures)

    def learn_from_conversation(
        self,
        conversation_history: list[dict],
        injected_procedure_ids: list[str] | None = None,
    ) -> list[str]:
        """Scan history, detect teach/task, generate procedures. Returns new ids."""
        return self._learner.detect_and_learn(conversation_history, injected_procedure_ids)

    def record_execution(
        self,
        procedure_id: str,
        result: str,
        notes: str = "",
    ) -> None:
        """Record execution result for a procedure."""
        self._store.update_execution(procedure_id, result, notes)

    def archive_low_weight(self, threshold: float = 0.1) -> int:
        """Archive low-weight procedures. Returns count."""
        return self._store.archive_low_weight(threshold)

    def learn_from_conversation_db(
        self,
        conversation_db,
        injected_procedure_ids: list[str] | None = None,
        since: float | None = None,
    ) -> list[str]:
        """Fetch recent conversation history from db and run learn pipeline.

        Args:
            conversation_db: ConversationDB instance.
            injected_procedure_ids: IDs of procedures in context (for result inference).
            since: If given, only fetch messages created after this timestamp.
                   Used for incremental learning (only new messages since last check).
        """
        if not conversation_db:
            return []
        try:
            recent = conversation_db.get_recent(50, since=since)
            if len(recent) < 2:
                return []
            history = [
                {"role": m.get("role", "unknown"), "content": m.get("content", "")[:300]}
                for m in recent
            ]
            return self.learn_from_conversation(history, injected_procedure_ids)
        except Exception as e:
            logger.warning("%s 学习失败: %s", _P_LOG, e)
            return []