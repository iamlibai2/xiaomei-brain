"""WildObserver: 被动观测器——记录 agent 的意外行为，不干预。

只观测，不控制。只写日志，不改逻辑。

观测点：L2 加柴时记录触发原因、Drive 状态、LLM 产生的意图、
涌现文本、自我不确定感。这些数据的差异和pattern就是"野性"的痕迹。

Usage:
    observer = WildObserver(agent_id)
    observer.log(tick_data)  # 在 L2Engine.tick() 中调用

日志输出: ~/.xiaomei-brain/{agent_id}/wild_log/{date}.md
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class WildObserver:
    """被动观测器。

    只记录，不干预。设计原则：
    - 零副作用：不改变任何现有逻辑，不阻断流程
    - 可读性：Markdown 格式，人可以直接看
    - 轻量：每次写入 < 1KB，不过滤、不分析
    """

    def __init__(self, agent_id: str) -> None:
        self._agent_id = agent_id
        self._log_dir = Path(os.path.expanduser(
            f"~/.xiaomei-brain/{agent_id}/wild_log"
        ))
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._tick_count = 0

    # ── 公共 API ─────────────────────────────────────────────

    def observe_l2(
        self,
        *,
        context: str,
        drive_snapshot: dict[str, Any],
        intent: Any | None,
        emergence_text: str,
        doubts: list[dict],
        user_name: str = "",
    ) -> None:
        """记录一次 L2 加柴的观测数据。"""
        self._tick_count += 1

        entry = {
            "tick": self._tick_count,
            "time": time.time(),
            "context": context,
            "drive": drive_snapshot,
            "intent": self._serialize_intent(intent),
            "emergence_preview": emergence_text[:300] if emergence_text else "",
            "doubts": [d.get("content", "") for d in doubts],
            "user_name": user_name,
        }

        self._write_entry(entry)

    # ── 内部 ──────────────────────────────────────────────────

    @staticmethod
    def _serialize_intent(intent: Any) -> dict | None:
        if intent is None:
            return None
        try:
            return {
                "type": getattr(intent, "type", None),
                "content": getattr(intent, "content", ""),
                "priority": getattr(intent, "priority", 0),
            }
        except Exception:
            return {"raw": str(intent)}

    def _write_entry(self, entry: dict) -> None:
        """追加一条观测记录到当日的 Markdown 文件。"""
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = self._log_dir / f"{today}.md"

        is_new = not log_file.exists()

        try:
            with open(log_file, "a", encoding="utf-8") as f:
                if is_new:
                    f.write(f"# {self._agent_id} Wild Log — {today}\n\n")
                    f.write("> 被动观测日志。只记录，不干预。\n\n")

                t = datetime.fromtimestamp(entry["time"]).strftime("%H:%M:%S")

                f.write(f"## [{t}] tick #{entry['tick']}\n\n")

                f.write(f"**触发**: `{entry['context']}`  \n")

                f.write(f"**Drive**: ")
                drive_parts = []
                for k, v in entry["drive"].items():
                    if isinstance(v, float):
                        drive_parts.append(f"{k}={v:.2f}")
                    else:
                        drive_parts.append(f"{k}={v}")
                f.write(", ".join(drive_parts))
                f.write("  \n")

                intent = entry["intent"]
                if intent:
                    itype = intent.get("type", "?")
                    f.write(f"**意图**: {itype}/{intent.get('content', '')[:80]} (p={intent.get('priority', 0)})  \n")
                else:
                    f.write(f"**意图**: (无)  \n")

                if entry["doubts"]:
                    f.write(f"**不确定**:\n")
                    for d in entry["doubts"]:
                        f.write(f"- {d}\n")
                    f.write("\n")

                if entry["emergence_preview"]:
                    f.write(f"**涌现**:\n> {entry['emergence_preview']}\n\n")

                f.write("---\n\n")

        except Exception as e:
            logger.warning("[WildObserver] 写入失败: %s", e)
