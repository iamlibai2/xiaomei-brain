"""Cron 调度系统 — 小美自己的闹钟。

支持三种模式：
- one-shot: 一次性定时器，如 "8小时后醒来查看用户"
- cron: 循环调度，如 "每周一早9点检查金价"、"每小时检查一次"
- round: 轮次触发，如 "每3轮对话"（对话完毕后触发）

Storage: ~/.xiaomei-brain/agents/{agent_id}/schedule/crons.json
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from croniter import croniter
    _has_croniter = True
except ImportError:
    _has_croniter = False

logger = logging.getLogger(__name__)


# ── CronJob ────────────────────────────────────────────────────────────

@dataclass
class CronJob:
    """一盏闹钟。"""

    id: str
    name: str                           # "醒来查看用户"
    schedule_type: str                  # "once" | "cron"
    trigger_at: float | None = None     # once: Unix 时间戳
    cron_expr: str | None = None        # cron: "0 9 * * 1"
    reason: str = ""                    # 为什么设这个闹钟
    action_hint: str = ""               # 响了要做什么
    created_at: float = field(default_factory=time.time)
    last_fired_at: float | None = None
    next_fire_at: float = 0.0           # 预计算的下次触发时间
    enabled: bool = True
    round_interval: int = 0             # round: 每N轮触发

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "schedule_type": self.schedule_type,
            "trigger_at": self.trigger_at,
            "cron_expr": self.cron_expr,
            "reason": self.reason,
            "action_hint": self.action_hint,
            "created_at": self.created_at,
            "last_fired_at": self.last_fired_at,
            "next_fire_at": self.next_fire_at,
            "enabled": self.enabled,
        }
        if self.round_interval:
            d["round_interval"] = self.round_interval
        return d

    @classmethod
    def from_dict(cls, data: dict) -> CronJob:
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            schedule_type=data.get("schedule_type", "once"),
            trigger_at=data.get("trigger_at"),
            cron_expr=data.get("cron_expr"),
            reason=data.get("reason", ""),
            action_hint=data.get("action_hint", ""),
            created_at=data.get("created_at", 0),
            last_fired_at=data.get("last_fired_at"),
            next_fire_at=data.get("next_fire_at", 0),
            enabled=data.get("enabled", True),
            round_interval=data.get("round_interval", 0),
        )

    def fire_and_reschedule(self) -> None:
        """触发热更新到期时间。"""
        self.last_fired_at = time.time()
        now = time.time()

        if self.schedule_type == "once":
            self.enabled = False
            self.next_fire_at = 0
        elif self.schedule_type == "cron" and self.cron_expr:
            self.next_fire_at = _next_cron(self.cron_expr, now)

    def summary(self) -> str:
        if not self.enabled:
            status = "[已停止]"
        elif self.schedule_type == "once":
            remain = max(0, int(self.next_fire_at - time.time()))
            h, m = remain // 3600, (remain % 3600) // 60
            status = f"[{h}时{m}分后]" if h > 0 else f"[{m}分钟后]"
        elif self.schedule_type == "round":
            status = f"[每{self.round_interval}轮]"
        else:
            status = f"[{self.cron_expr}]"

        parts = [f"{self.name} {status}"]
        if self.reason:
            parts.append(f"  原因：{self.reason}")
        if self.action_hint:
            parts.append(f"  到时：{self.action_hint}")
        return "\n".join(parts)


# ── Cron 解析 ──────────────────────────────────────────────────────────

def _next_cron(expr: str, from_time: float) -> float:
    """计算 cron 表达式下一次触发时间。"""
    if _has_croniter:
        try:
            cron = croniter(expr, from_time)
            return cron.get_next()
        except (ValueError, KeyError):
            return 0.0
    # fallback: 简单解析
    return _simple_next_cron(expr, from_time)


def _simple_next_cron(expr: str, from_time: float) -> float:
    """简单 cron 解析（无 croniter 时用），支持 */N 和固定值。"""
    import datetime

    try:
        parts = expr.strip().split()
        if len(parts) != 5:
            return 0.0

        minute, hour, dom, month, dow = parts
        dt = datetime.datetime.fromtimestamp(from_time)

        # 解析 minute
        if minute.startswith("*/"):
            step = int(minute[2:])
            next_min = ((dt.minute // step) + 1) * step
            if next_min >= 60:
                dt = dt + datetime.timedelta(hours=1)
                dt = dt.replace(minute=0)
            else:
                dt = dt.replace(minute=next_min)
        elif minute != "*":
            dt = dt.replace(minute=int(minute))

        # 解析 hour（简化：只处理固定值和 *）
        if hour.isdigit():
            target_h = int(hour)
            if dt.hour > target_h or (dt.hour == target_h and dt.minute > 0):
                dt = dt + datetime.timedelta(days=1)
            dt = dt.replace(hour=target_h, minute=0, second=0, microsecond=0)
        elif hour.startswith("*/"):
            step = int(hour[2:])
            next_h = ((dt.hour // step) + 1) * step
            if next_h >= 24:
                dt = dt + datetime.timedelta(days=1)
                dt = dt.replace(hour=0, minute=0)
            else:
                dt = dt.replace(hour=next_h, minute=0)

        # 解析 dow（简化：只处理固定星期几）
        if dow.isdigit():
            target_dow = int(dow)
            target_dow = target_dow % 7  # 0=Sunday → 0=Monday in Python
            current_dow = dt.weekday()
            days_ahead = target_dow - current_dow
            if days_ahead <= 0:
                days_ahead += 7
            dt = dt + datetime.timedelta(days=days_ahead)
            dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)

        dt = dt.replace(second=0, microsecond=0)
        return dt.timestamp()
    except Exception:
        return 0.0


# ── CronScheduler ──────────────────────────────────────────────────────

class CronScheduler:
    """闹钟调度引擎。

    管理 CronJob 的生命周期：创建、查询、取消、持久化、到期检测。
    """

    def __init__(self, agent_id: str, base_dir: str | Path | None = None):
        self._agent_id = agent_id
        if base_dir is None:
            base_dir = Path.home() / ".xiaomei-brain" / "agents" / agent_id
        self._base_dir = Path(base_dir)
        self._schedule_dir = self._base_dir / "schedule"
        self._schedule_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._schedule_dir / "crons.json"
        self._crons: dict[str, CronJob] = {}
        self._round_count: int = 0
        self._load()

    # ── CRUD ────────────────────────────────────────────────

    def add(
        self,
        name: str,
        schedule_type: str = "once",
        trigger_at: float | None = None,
        cron_expr: str | None = None,
        reason: str = "",
        action_hint: str = "",
        round_interval: int = 0,
    ) -> CronJob:
        """添加闹钟。"""
        now = time.time()
        if schedule_type == "once" and trigger_at:
            next_fire = trigger_at
        elif schedule_type == "cron" and cron_expr:
            next_fire = _next_cron(cron_expr, now)
        elif schedule_type == "round" and round_interval > 0:
            next_fire = 0  # 轮次触发不用时间戳
        else:
            raise ValueError(f"无效的调度: type={schedule_type}")

        if schedule_type != "round" and next_fire <= now:
            raise ValueError(f"触发时间已过期: {next_fire}")

        job = CronJob(
            id=uuid.uuid4().hex[:12],
            name=name,
            schedule_type=schedule_type,
            trigger_at=trigger_at,
            cron_expr=cron_expr,
            reason=reason,
            action_hint=action_hint,
            next_fire_at=next_fire,
            round_interval=round_interval,
        )
        self._crons[job.id] = job
        self._save()
        if schedule_type == "round":
            logger.info("[CronScheduler] 已添加: %s (每%d轮)", job.name, round_interval)
        else:
            logger.info("[CronScheduler] 已添加: %s (next=%s)", job.name, _ts_str(job.next_fire_at))
        return job

    def remove(self, job_id: str) -> bool:
        """删除闹钟。"""
        if job_id in self._crons:
            name = self._crons[job_id].name
            del self._crons[job_id]
            self._save()
            logger.info("[CronScheduler] 已删除: %s", name)
            return True
        return False

    def get(self, job_id: str) -> CronJob | None:
        return self._crons.get(job_id)

    def list_all(self) -> list[CronJob]:
        """列出所有闹钟，按下次触发时间排序。"""
        return sorted(self._crons.values(), key=lambda j: j.next_fire_at if j.enabled else float("inf"))

    def list_enabled(self) -> list[CronJob]:
        return [j for j in self._crons.values() if j.enabled]

    # ── 到期检测 ─────────────────────────────────────────────

    def check_due(self) -> list[CronJob]:
        """检测到期的时间闹钟（once/cron），不包含轮次闹钟。"""
        now = time.time()
        due: list[CronJob] = []
        for job in list(self._crons.values()):
            if not job.enabled:
                continue
            if job.schedule_type == "round":
                continue  # 轮次闹钟由 on_round_complete() 处理
            if job.next_fire_at <= now:
                job.fire_and_reschedule()
                due.append(job)
                logger.info("[CronScheduler] 闹钟触发: %s (type=%s)", job.name, job.schedule_type)
        if due:
            self._save()
        return due

    def on_round_complete(self) -> list[CronJob]:
        """对话轮次完成时调用，返回到期的轮次闹钟列表。"""
        self._round_count += 1
        due: list[CronJob] = []
        for job in list(self._crons.values()):
            if not job.enabled or job.schedule_type != "round":
                continue
            if job.round_interval <= 0:
                continue
            if self._round_count % job.round_interval == 0:
                job.last_fired_at = time.time()
                due.append(job)
                logger.info("[CronScheduler] 轮次闹钟触发: %s (每%d轮, 当前第%d轮)",
                            job.name, job.round_interval, self._round_count)
        return due

    # ── 持久化 ───────────────────────────────────────────────

    def _path_for_agent(self) -> Path:
        """兼容旧接口，实际使用 self._path。"""
        return self._path

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                job = CronJob.from_dict(item)
                self._crons[job.id] = job
            logger.info("[CronScheduler] 已加载 %d 个闹钟", len(self._crons))
        except Exception as e:
            logger.warning("[CronScheduler] 加载失败: %s", e)

    def _save(self) -> None:
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(
                    [j.to_dict() for j in self._crons.values()],
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            logger.warning("[CronScheduler] 保存失败: %s", e)


# ── Tools ──────────────────────────────────────────────────────────────

def create_cron_tools(scheduler: CronScheduler) -> list:
    """创建闹钟工具（注册到 agent 的 ToolRegistry）。

    Args:
        scheduler: CronScheduler 实例
    """
    from xiaomei_brain.tools.base import Tool, tool

    @tool(
        name="schedule_alarm",
        description=(
            "给自己设一个闹钟。关掉对话后闹钟依然会响。\n"
            "\n"
            "三种模式：\n"
            "- 一次性：when=\"2小时后\" / \"明天早上9点\" / \"30分钟后\"\n"
            "- 循环：when=\"每周一早9点\" / \"每小时\" / \"每天零点\" / \"每30分钟\"\n"
            "- 轮次：when=\"每3轮\" / \"每5轮对话\"（对话完成后触发）\n"
            "\n"
            "reason 是你为什么设这个闹钟，action 是闹钟响了你要做什么。\n"
            "设完后你会得到一个闹钟 ID，可以用 cancel_alarm 取消。\n"
            "\n"
            "示例：\n"
            "- schedule_alarm(when=\"8小时后\", reason=\"我困了想睡一会\", action=\"醒来查看用户有没有找我\")\n"
            "- schedule_alarm(when=\"每周一早上9点\", reason=\"\", action=\"检查金价\")\n"
            "- schedule_alarm(when=\"明天凌晨零点\", reason=\"\", action=\"限额重置后自动出图\")\n"
            "- schedule_alarm(when=\"每30分钟\", reason=\"\", action=\"检查一下用户有没有新消息\")\n"
        ),
    )
    def schedule_alarm(when: str, reason: str = "", action: str = "") -> str:
        """设闹钟。解析自然语言时间描述。"""
        return _handle_schedule_alarm(scheduler, when, reason, action)

    @tool(
        name="list_alarms",
        description="查看自己设的所有闹钟。返回闹钟列表，包含每个闹钟的名称、下次触发时间、原因和动作。",
    )
    def list_alarms() -> str:
        jobs = scheduler.list_all()
        if not jobs:
            return "你还没有设任何闹钟。"
        lines = ["你的闹钟：", ""]
        for j in jobs:
            lines.append(f"  [{j.id}] {j.summary()}")
            lines.append("")
        return "\n".join(lines)

    @tool(
        name="cancel_alarm",
        description="取消一个闹钟。需要闹钟 ID（可在 list_alarms 里看到）。",
    )
    def cancel_alarm(alarm_id: str) -> str:
        if scheduler.remove(alarm_id):
            return f"闹钟 {alarm_id} 已取消。"
        return f"未找到闹钟 {alarm_id}。"

    return [schedule_alarm, list_alarms, cancel_alarm]


def _parse_when(when: str) -> tuple[str, float | None, str | None]:
    """解析自然语言时间描述为 (type, trigger_at, cron_expr)。

    返回 None 表示解析失败。
    """
    import re

    when = when.strip()

    # ── 轮次模式（放在最前面，避免被循环模式误匹配）───
    m = re.match(r"每\s*(\d+)\s*轮", when)
    if m:
        return ("round", None, f"每{int(m.group(1))}轮")

    # ── 循环模式 ──────────────────────────
    cycle_patterns = [
        (r"每\s*(\d+)\s*分钟", lambda m: ("cron", None, f"*/{int(m.group(1))} * * * *")),
        (r"每\s*(\d+)\s*小时", lambda m: ("cron", None, f"0 */{int(m.group(1))} * * *")),
        (r"每\s*(\d+)\s*天", lambda m: ("cron", None, f"0 0 */{int(m.group(1))} * *")),
        (r"每小时", lambda m: ("cron", None, "0 * * * *")),
        (r"每天\s*零?点?", lambda m: ("cron", None, "0 0 * * *")),
        (r"每周一.*?(\d+)点", lambda m: ("cron", None, f"0 {int(m.group(1))} * * 1")),
        (r"每周一", lambda m: ("cron", None, "0 9 * * 1")),
        (r"每周二.*?(\d+)点", lambda m: ("cron", None, f"0 {int(m.group(1))} * * 2")),
        (r"每周三.*?(\d+)点", lambda m: ("cron", None, f"0 {int(m.group(1))} * * 3")),
        (r"每周四.*?(\d+)点", lambda m: ("cron", None, f"0 {int(m.group(1))} * * 4")),
        (r"每周五.*?(\d+)点", lambda m: ("cron", None, f"0 {int(m.group(1))} * * 5")),
        (r"每周六.*?(\d+)点", lambda m: ("cron", None, f"0 {int(m.group(1))} * * 6")),
        (r"每周日.*?(\d+)点", lambda m: ("cron", None, f"0 {int(m.group(1))} * * 0")),
    ]

    for pattern, mapper in cycle_patterns:
        m = re.match(pattern, when)
        if m:
            return mapper(m)

    # ── 一次性模式 ──────────────────────────
    now = time.time()

    # X分钟后/小时后/天后
    m = re.match(r"(\d+)\s*分钟后", when)
    if m:
        seconds = int(m.group(1)) * 60
        return ("once", now + seconds, None)

    m = re.match(r"(\d+)\s*小时后", when)
    if m:
        seconds = int(m.group(1)) * 3600
        return ("once", now + seconds, None)

    m = re.match(r"(\d+)\s*天后", when)
    if m:
        seconds = int(m.group(1)) * 86400
        return ("once", now + seconds, None)

    # 明天 X点
    m = re.match(r"明天\s*(\d+)\s*点", when)
    if m:
        import datetime
        target_h = int(m.group(1))
        tomorrow = datetime.datetime.now() + datetime.timedelta(days=1)
        dt = tomorrow.replace(hour=target_h, minute=0, second=0, microsecond=0)
        return ("once", dt.timestamp(), None)

    # X月X日 X点
    m = re.match(r"(\d+)月(\d+)日\s*(\d+)\s*点", when)
    if m:
        import datetime
        import calendar
        month, day, hour = int(m.group(1)), int(m.group(2)), int(m.group(3))
        now = datetime.datetime.now()
        target = now.replace(month=month, day=day, hour=hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target = target.replace(year=now.year + 1)
        return ("once", target.timestamp(), None)

    return ("unknown", None, None)


def _ts_str(ts: float) -> str:
    """时间戳转可读字符串。"""
    import datetime
    if ts <= 0:
        return "N/A"
    dt = datetime.datetime.fromtimestamp(ts)
    return dt.strftime("%Y-%m-%d %H:%M")


def _handle_schedule_alarm(scheduler: CronScheduler, when: str, reason: str, action: str) -> str:
    """处理设闹钟请求。"""
    s_type, trigger_at, cron_expr = _parse_when(when)

    if s_type == "unknown":
        return (
            f"无法理解时间「{when}」。请用以下格式之一：\n"
            "- 一次性：\"2小时后\" / \"30分钟后\" / \"明天早上9点\" / \"5月15日10点\"\n"
            "- 循环：\"每30分钟\" / \"每小时\" / \"每天零点\" / \"每周一早上9点\"\n"
            "- 轮次：\"每3轮\" / \"每5轮对话\""
        )

    try:
        round_interval = 0
        if s_type == "round" and cron_expr:
            import re
            m = re.search(r"(\d+)", cron_expr)
            if m:
                round_interval = int(m.group(1))

        job = scheduler.add(
            name=when if not reason else reason[:30],
            schedule_type=s_type,
            trigger_at=trigger_at,
            cron_expr=cron_expr,
            reason=reason,
            action_hint=action,
            round_interval=round_interval,
        )
    except ValueError as e:
        return f"设闹钟失败：{e}"

    if s_type == "once":
        type_label = "一次性"
    elif s_type == "round":
        type_label = "轮次"
    else:
        type_label = "循环"

    if s_type == "round":
        return f"闹钟已设好（{type_label}）。\nID: {job.id}\n触发: 每{job.round_interval}轮对话后\n名称: {job.name}"
    return f"闹钟已设好（{type_label}）。\nID: {job.id}\n下次触发: {_ts_str(job.next_fire_at)}\n名称: {job.name}"
