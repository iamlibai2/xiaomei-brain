"""SelfModel: Agent's persistent identity across sessions.

Extends talent.md from plain text to structured self-model with:
- PurposeSeed: identity, calling, passions, boundaries (preset, grows through reflection)
- Self-cognition: what I'm good at, what I'm not
- Growth log: reflections and discoveries over time

The talent.md format is backward compatible: old plain-text files are parsed
as seed_text with no structure. New structured files use markdown headers.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PurposeSeed:
    """Core identity and purpose — innate/given, not self-discovered.

    This is the agent's '天赋' (gift/calling): preset first, grows later.
    """

    identity: str = ""       # "我是小美，一个温柔体贴的AI伴侣"
    calling: str = ""        # "我要成为真正懂用户内心的伙伴"
    passions: list[str] = field(default_factory=list)   # sources of joy
    boundaries: list[str] = field(default_factory=list)  # things I will not do


@dataclass
class GrowthEntry:
    """A reflection or self-discovery logged over time."""

    date: str       # "2026-04"
    content: str    # "发现自己更擅长情感支持而非技术解答"


@dataclass
class SelfModel:
    """Agent's persistent self-model, stored as talent.md.

    Three rendering modes for system prompt:
    - flow (心流): identity only — minimal, task-focused
    - daily (日常): identity + calling + passions — standard
    - reflect (反省): full model — deep self-awareness
    """

    purpose_seed: PurposeSeed = field(default_factory=PurposeSeed)
    seed_text: str = ""                  # original seed text (immutable)
    self_cognition: dict[str, list[str]] = field(default_factory=lambda: {
        "擅长": [], "不擅长": [],
    })
    behavioral_patterns: list[str] = field(default_factory=list)
    relationship_with_user: dict[str, Any] = field(default_factory=dict)
    habits: list[dict[str, Any]] = field(default_factory=list)
    emotional_baseline: dict[str, Any] = field(default_factory=dict)
    growth_log: list[GrowthEntry] = field(default_factory=list)

    # ── Serialization ───────────────────────────────────────────

    def to_talent_md(self) -> str:
        """Render as structured talent.md markdown."""
        lines: list[str] = []

        # 身份
        if self.purpose_seed.identity:
            lines.append(f"# 身份\n{self.purpose_seed.identity}\n")

        # 追求
        if self.purpose_seed.calling:
            lines.append(f"# 追求\n{self.purpose_seed.calling}\n")

        # 热爱
        if self.purpose_seed.passions:
            lines.append("# 热爱")
            for p in self.purpose_seed.passions:
                lines.append(f"- {p}")
            lines.append("")

        # 底线
        if self.purpose_seed.boundaries:
            lines.append("# 底线")
            for b in self.purpose_seed.boundaries:
                lines.append(f"- {b}")
            lines.append("")

        # 原始种子（不可修改）
        if self.seed_text:
            lines.append(f"# 原始种子（不可修改）\n{self.seed_text}\n")

        # 自我认知
        has_cognition = any(v for v in self.self_cognition.values())
        if has_cognition:
            lines.append("# 自我认知")
            for category, items in self.self_cognition.items():
                if items:
                    lines.append(f"## {category}")
                    for item in items:
                        lines.append(f"- {item}")
            lines.append("")

        # 行为模式
        if self.behavioral_patterns:
            lines.append("# 行为模式")
            for bp in self.behavioral_patterns:
                lines.append(f"- {bp}")
            lines.append("")

        # 与用户的关系
        if self.relationship_with_user:
            lines.append("# 与用户的关系")
            for k, v in self.relationship_with_user.items():
                if isinstance(v, list):
                    lines.append(f"## {k}")
                    for item in v:
                        lines.append(f"- {item}")
                else:
                    lines.append(f"- {k}: {v}")
            lines.append("")

        # 习惯
        if self.habits:
            lines.append("# 习惯")
            for h in self.habits:
                desc = h.get("description", "")
                lines.append(f"- {desc}")
            lines.append("")

        # 情感基线
        if self.emotional_baseline:
            lines.append("# 情感基线")
            for k, v in self.emotional_baseline.items():
                lines.append(f"- {k}: {v}")
            lines.append("")

        # 生长记录
        if self.growth_log:
            lines.append("# 生长记录")
            # Group by date
            by_date: dict[str, list[str]] = {}
            for entry in self.growth_log:
                by_date.setdefault(entry.date, []).append(entry.content)
            for date, contents in by_date.items():
                lines.append(f"## {date}")
                for c in contents:
                    lines.append(f"- {c}")
            lines.append("")

        return "\n".join(lines).strip() + "\n"

    @classmethod
    def from_talent_md(cls, content: str) -> SelfModel:
        """Parse talent.md into SelfModel.

        Backward compatible: if no structured headers found, treats entire
        content as seed_text and extracts identity from first line.
        """
        content = content.strip()
        if not content:
            return cls()

        # Check if structured format (has our known headers)
        has_structure = bool(re.search(
            r"^# (身份|追求|热爱|底线|原始种子|自我认知|行为模式|生长记录)",
            content, re.MULTILINE,
        ))

        if not has_structure:
            # Legacy format: plain text
            return cls(
                purpose_seed=PurposeSeed(identity=content.split("\n")[0].strip()),
                seed_text=content,
            )

        # Structured format: parse sections
        model = cls()
        sections = _parse_sections(content)

        # 身份
        if "身份" in sections:
            model.purpose_seed.identity = sections["身份"].strip()

        # 追求
        if "追求" in sections:
            model.purpose_seed.calling = sections["追求"].strip()

        # 热爱
        if "热爱" in sections:
            model.purpose_seed.passions = _parse_list_items(sections["热爱"])

        # 底线
        if "底线" in sections:
            model.purpose_seed.boundaries = _parse_list_items(sections["底线"])

        # 原始种子
        if "原始种子（不可修改）" in sections:
            model.seed_text = sections["原始种子（不可修改）"].strip()
        elif "原始种子" in sections:
            model.seed_text = sections["原始种子"].strip()

        # 自我认知
        if "自我认知" in sections:
            model.self_cognition = _parse_sub_sections(sections["自我认知"])

        # 行为模式
        if "行为模式" in sections:
            model.behavioral_patterns = _parse_list_items(sections["行为模式"])

        # 与用户的关系
        if "与用户的关系" in sections:
            model.relationship_with_user = _parse_sub_sections(sections["与用户的关系"])

        # 习惯
        if "习惯" in sections:
            model.habits = _parse_habits(sections["习惯"])

        # 情感基线
        if "情感基线" in sections:
            model.emotional_baseline = _parse_key_value(sections["情感基线"])

        # 生长记录
        if "生长记录" in sections:
            model.growth_log = _parse_growth_log(sections["生长记录"])

        return model

    # ── System prompt rendering ─────────────────────────────────

    def to_system_prompt(self, mode: str = "daily") -> str:
        """Render as system prompt based on operational mode.

        Args:
            mode: "flow" (心流), "daily" (日常), "reflect" (反省)

        Returns:
            System prompt string.
        """
        if mode == "flow":
            return self._render_flow()
        elif mode == "reflect":
            return self._render_reflect()
        else:
            return self._render_daily()

    def _render_flow(self) -> str:
        """心流模式: identity only, minimal context."""
        parts = []
        if self.purpose_seed.identity:
            parts.append(self.purpose_seed.identity)
        # For legacy format: identity is first line of seed_text,
        # include the full seed_text (which already contains identity)
        if self.seed_text and not self.purpose_seed.calling:
            # Legacy: no structure, seed_text is the whole prompt
            return self.seed_text
        elif self.seed_text:
            # Structured: add seed lines not already in identity
            for line in self.seed_text.strip().split("\n"):
                line = line.strip()
                if line and line != self.purpose_seed.identity:
                    parts.append(line)
        return "\n".join(parts) if parts else "You are a helpful assistant."

    def _render_daily(self) -> str:
        """日常模式: identity + calling + passions + boundaries."""
        lines: list[str] = []

        if self.purpose_seed.identity:
            lines.append(self.purpose_seed.identity)

        if self.purpose_seed.calling:
            lines.append(f"我的追求：{self.purpose_seed.calling}")

        if self.purpose_seed.passions:
            lines.append("我热爱：" + "、".join(self.purpose_seed.passions))

        if self.purpose_seed.boundaries:
            lines.append("我的底线：" + "、".join(self.purpose_seed.boundaries))

        # Add self-cognition highlights
        strengths = self.self_cognition.get("擅长", [])
        if strengths:
            lines.append("我擅长：" + "、".join(strengths))

        # Add recent growth (last 3)
        recent = self.growth_log[-3:] if self.growth_log else []
        if recent:
            lines.append("最近的成长：" + "；".join(g.content for g in recent))

        # Append seed text if not already covered (only for structured format)
        if self.seed_text and self.purpose_seed.calling:
            for sl in self.seed_text.strip().split("\n"):
                sl = sl.strip()
                if sl and sl not in lines and sl != self.purpose_seed.identity:
                    lines.append(sl)
        # Legacy format: seed_text is the full prompt (identity is already added)
        elif self.seed_text and not self.purpose_seed.calling:
            for sl in self.seed_text.strip().split("\n"):
                sl = sl.strip()
                if sl and sl != self.purpose_seed.identity and sl not in lines:
                    lines.append(sl)

        return "\n".join(lines) if lines else "You are a helpful assistant."

    def _render_reflect(self) -> str:
        """反省模式: full self-model for deep self-awareness."""
        return self.to_talent_md()

    # ── File I/O ────────────────────────────────────────────────

    @classmethod
    def load(cls, path: str | Path) -> SelfModel:
        """Load SelfModel from talent.md file."""
        p = Path(path)
        if not p.exists():
            logger.warning("talent.md not found: %s", p)
            return cls()
        content = p.read_text(encoding="utf-8")
        return cls.from_talent_md(content)

    def save(self, path: str | Path) -> None:
        """Save SelfModel to talent.md file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_talent_md(), encoding="utf-8")
        logger.info("SelfModel saved to %s", p)

    # ── Growth ──────────────────────────────────────────────────

    def add_growth(self, content: str, date: str | None = None) -> None:
        """Add a growth entry."""
        if date is None:
            date = datetime.now().strftime("%Y-%m")
        self.growth_log.append(GrowthEntry(date=date, content=content))

    def add_habit(self, description: str, context: str = "") -> None:
        """Add a habit."""
        self.habits.append({"description": description, "context": context})

    def add_strength(self, item: str) -> None:
        """Add to self-cognition strengths."""
        self.self_cognition.setdefault("擅长", []).append(item)

    def add_weakness(self, item: str) -> None:
        """Add to self-cognition weaknesses."""
        self.self_cognition.setdefault("不擅长", []).append(item)


# ── Parsing helpers ─────────────────────────────────────────────

def _parse_sections(content: str) -> dict[str, str]:
    """Split markdown by top-level headers (# ) into section dict."""
    sections: dict[str, str] = {}
    current_header = ""
    current_lines: list[str] = []

    for line in content.split("\n"):
        m = re.match(r"^# (.+)$", line)
        if m:
            if current_header:
                sections[current_header] = "\n".join(current_lines)
            current_header = m.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_header:
        sections[current_header] = "\n".join(current_lines)

    return sections


def _parse_list_items(text: str) -> list[str]:
    """Parse '- item' lines from text."""
    items = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if line.startswith("- "):
            items.append(line[2:].strip())
    return items


def _parse_sub_sections(text: str) -> dict[str, list[str]]:
    """Parse '## Category' sub-sections with '- item' lists."""
    result: dict[str, list[str]] = {}
    current_key = ""
    for line in text.strip().split("\n"):
        m = re.match(r"^## (.+)$", line)
        if m:
            current_key = m.group(1).strip()
            result[current_key] = []
        elif line.strip().startswith("- ") and current_key:
            result[current_key].append(line.strip()[2:].strip())
    return result


def _parse_habits(text: str) -> list[dict[str, Any]]:
    """Parse habit entries."""
    items = _parse_list_items(text)
    return [{"description": item} for item in items]


def _parse_key_value(text: str) -> dict[str, Any]:
    """Parse '- key: value' lines."""
    result: dict[str, Any] = {}
    for line in text.strip().split("\n"):
        line = line.strip()
        if line.startswith("- ") and ":" in line:
            kv = line[2:].split(":", 1)
            result[kv[0].strip()] = kv[1].strip()
    return result


def _parse_growth_log(text: str) -> list[GrowthEntry]:
    """Parse growth log with ## date sub-headers."""
    entries: list[GrowthEntry] = []
    current_date = ""
    for line in text.strip().split("\n"):
        m = re.match(r"^## (.+)$", line)
        if m:
            current_date = m.group(1).strip()
        elif line.strip().startswith("- ") and current_date:
            entries.append(GrowthEntry(
                date=current_date,
                content=line.strip()[2:].strip(),
            ))
    return entries
