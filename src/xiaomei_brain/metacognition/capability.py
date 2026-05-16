"""能力校准器：跟踪 Agent 擅长和不擅长的操作领域。

CapabilityTracker 在每次 PACE step 后记录工具调用的执行效果，
生成"能力画像"（strengths/weaknesses/uncertain），注入到目标分解 prompt 中，
帮助 LLM 在分解时避开 Agent 不擅长的操作。

Usage:
    tracker = CapabilityTracker(agent_id=agent_id)
    tracker.record("file_ops", "success", [], 5.2, 0)
    profile = tracker.get_profile()
    context = tracker.get_calibration_context()
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CapabilityRecord:
    """单次操作的执行记录"""
    domain: str          # "file_ops" | "web_search" | "code_gen" | "shell_exec"
    operation: str       # 工具名
    result: str          # "success" | "partial" | "failed"
    surprise_types: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    retry_count: int = 0
    timestamp: float = field(default_factory=time.time)


class CapabilityTracker:
    """能力校准器。

    持久化到 ~/.xiaomei-brain/agents/{agent_id}/metacognition/capabilities.json
    """

    # 工具名 → domain 映射
    TOOL_DOMAIN_MAP: dict[str, str] = {
        "write_file": "file_ops",
        "read_file": "file_ops",
        "list_files": "file_ops",
        "delete_file": "file_ops",
        "websearch": "web_search",
        "webget": "web_search",
        "web_search": "web_search",
        "web_get": "web_search",
        "shell": "shell_exec",
        "run_command": "shell_exec",
        "exec": "shell_exec",
        "tts": "speech",
        "speak": "speech",
        "music": "music",
        "play_music": "music",
        "image": "image",
        "generate_image": "image",
        "dag_search": "memory",
        "memory_search": "memory",
        "longterm_search": "memory",
    }

    # 默认 domain（工具不在映射中时使用）
    DEFAULT_DOMAIN = "other"

    def __init__(self, agent_id: str = "") -> None:
        self._agent_id = agent_id
        self._records: list[CapabilityRecord] = []
        self._loaded = False

    # ── Domain classification ──────────────────────────────────────

    @classmethod
    def classify_domain(cls, tool_names: list[str]) -> str:
        """根据工具名称分类到操作领域。

        多工具调用时，返回最"危险"的 domain（优先级：shell_exec > file_ops > web_search > other）
        """
        if not tool_names:
            return cls.DEFAULT_DOMAIN

        domains = []
        for name in tool_names:
            domain = cls.TOOL_DOMAIN_MAP.get(name, cls.DEFAULT_DOMAIN)
            domains.append(domain)

        # 优先级：shell > file > web > speech/music/image > memory > other
        priority = ["shell_exec", "file_ops", "web_search", "speech", "music", "image", "memory", "other"]
        for p in priority:
            if p in domains:
                return p
        return cls.DEFAULT_DOMAIN

    # ── Record ─────────────────────────────────────────────────────

    def record(
        self,
        domain: str,
        result: str,
        surprises: list[str],
        elapsed: float,
        retries: int,
    ) -> None:
        """记录一次操作执行效果。

        Args:
            domain: 操作领域（"file_ops" / "web_search" / "shell_exec" / ...）
            result: 执行结果（"success" / "partial" / "failed"）
            surprises: 触发的异常信号列表
            elapsed: 耗时（秒）
            retries: 重试次数
        """
        self._ensure_loaded()
        record = CapabilityRecord(
            domain=domain,
            operation=domain,
            result=result,
            surprise_types=list(surprises),
            elapsed_seconds=elapsed,
            retry_count=retries,
            timestamp=time.time(),
        )
        self._records.append(record)

        # 只保留最近 200 条
        if len(self._records) > 200:
            self._records = self._records[-200:]

        self._save()

    # ── Profile ────────────────────────────────────────────────────

    def get_profile(self) -> dict:
        """返回当前能力画像。

        Returns:
            {
                "strengths": ["file_ops", "web_search"],     # 成功率 > 80%
                "weaknesses": ["shell_exec"],                 # 成功率 < 40%
                "uncertain": ["code_gen"],                    # 40%-80%
                "domain_stats": {
                    "file_ops": {"success": 45, "partial": 8, "failed": 3,
                                 "avg_time": 12.5, "avg_retries": 0.3},
                    ...
                }
            }
        """
        self._ensure_loaded()
        if not self._records:
            return self._empty_profile()

        # 按 domain 聚合
        stats: dict[str, dict] = {}
        for r in self._records:
            if r.domain not in stats:
                stats[r.domain] = {
                    "success": 0, "partial": 0, "failed": 0,
                    "total_time": 0.0, "total_retries": 0, "count": 0,
                }
            s = stats[r.domain]
            s[r.result] += 1
            s["total_time"] += r.elapsed_seconds
            s["total_retries"] += r.retry_count
            s["count"] += 1

        domain_stats = {}
        for domain, s in stats.items():
            domain_stats[domain] = {
                "success": s["success"],
                "partial": s["partial"],
                "failed": s["failed"],
                "avg_time": round(s["total_time"] / s["count"], 1) if s["count"] else 0,
                "avg_retries": round(s["total_retries"] / s["count"], 2) if s["count"] else 0,
            }

        strengths, weaknesses, uncertain = [], [], []
        for domain, s in domain_stats.items():
            total = s["success"] + s["partial"] + s["failed"]
            if total < 3:
                continue  # 样本太少，不判断
            rate = s["success"] / total
            if rate >= 0.8:
                strengths.append(domain)
            elif rate < 0.4:
                weaknesses.append(domain)
            else:
                uncertain.append(domain)

        return {
            "strengths": strengths,
            "weaknesses": weaknesses,
            "uncertain": uncertain,
            "domain_stats": domain_stats,
        }

    def get_calibration_context(self) -> str:
        """生成能力校准上下文，注入到目标分解 prompt 中。

        Returns:
            格式化的能力画像文本（空字符串 = 无数据）
        """
        profile = self.get_profile()
        if not profile["domain_stats"]:
            return ""

        parts = ["\n【能力画像】"]

        if profile["strengths"]:
            strengths_str = "、".join(self._domain_label(d) for d in profile["strengths"])
            parts.append(f"  - 擅长：{strengths_str}")
        if profile["weaknesses"]:
            weaknesses_str = "、".join(self._domain_label(d) for d in profile["weaknesses"])
            parts.append(f"  - 不擅长：{weaknesses_str}（避免分解出依赖这些操作的子目标）")
        if profile["uncertain"]:
            uncertain_str = "、".join(self._domain_label(d) for d in profile["uncertain"])
            parts.append(f"  - 不确定：{uncertain_str}（谨慎分解）")

        parts.append("")
        return "\n".join(parts)

    # ── Persistence ────────────────────────────────────────────────

    def _data_dir(self) -> Path:
        return Path.home() / ".xiaomei-brain" / "agents" / self._agent_id / "metacognition"

    def _data_path(self) -> Path:
        return self._data_dir() / "capabilities.json"

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        path = self._data_path()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self._records = [
                    CapabilityRecord(**item)
                    for item in data.get("records", [])
                ]
                logger.info("[CapabilityTracker] 加载了 %d 条能力记录", len(self._records))
            except Exception as e:
                logger.warning("[CapabilityTracker] 加载失败: %s", e)
        self._loaded = True

    def _save(self) -> None:
        path = self._data_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = {
                "records": [
                    {
                        "domain": r.domain,
                        "operation": r.operation,
                        "result": r.result,
                        "surprise_types": r.surprise_types,
                        "elapsed_seconds": r.elapsed_seconds,
                        "retry_count": r.retry_count,
                        "timestamp": r.timestamp,
                    }
                    for r in self._records
                ],
                "updated_at": time.time(),
            }
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("[CapabilityTracker] 保存失败: %s", e)

    @staticmethod
    def _empty_profile() -> dict:
        return {
            "strengths": [],
            "weaknesses": [],
            "uncertain": [],
            "domain_stats": {},
        }

    @staticmethod
    def _domain_label(domain: str) -> str:
        """领域 → 中文标签"""
        return {
            "file_ops": "文件操作",
            "web_search": "网络搜索",
            "shell_exec": "Shell执行",
            "speech": "语音合成",
            "music": "音乐播放",
            "image": "图像处理",
            "memory": "记忆检索",
        }.get(domain, domain)
