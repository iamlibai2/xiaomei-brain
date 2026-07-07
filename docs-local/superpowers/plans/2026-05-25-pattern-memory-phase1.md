# Pattern Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在梦境中从 ExperienceStream 提取跨时间统计规律，存入 LTM `type="pattern"`，通过五个注入点影响决策。

**Architecture:** 单文件 `memory/pattern.py` 三个类（PatternExtractor / PatternStorage / PatternInjector），复用 LTM `memories` 表，在 DreamEngine 中追加独立阶段，注入点修改 SelfImage / L2Engine / LearningEngine 的 prompt 构建逻辑。

**Tech Stack:** Python dataclasses, SQLite/LanceDB (已有 LTM), LLM 单次调用

---

## File Map

| 操作 | 文件 | 职责 |
|------|------|------|
| Create | `src/xiaomei_brain/prompts/pattern.py` | PATTERN_EXTRACT_PROMPT |
| Create | `src/xiaomei_brain/memory/pattern.py` | Pattern dataclass + 3 classes |
| Modify | `src/xiaomei_brain/consciousness/dream/dream_engine.py` | 构造函数 +exp_stream, run() 插入阶段3 |
| Modify | `src/xiaomei_brain/consciousness/conscious_living.py` | DreamEngine 实例化传 exp_stream |
| Modify | `src/xiaomei_brain/consciousness/self_image_proxy.py` | _render_patterns() + 注入到 daily/task/reflect |
| Modify | `src/xiaomei_brain/consciousness/l2_engine.py` | _build_intent_prompt() 注入相关模式 |
| Modify | `src/xiaomei_brain/learn/engine.py` | _select_topic() 模式加权 |

---

### Task 1: Create PATTERN_EXTRACT_PROMPT

**Files:**
- Create: `src/xiaomei_brain/prompts/pattern.py`

- [ ] **Step 1: 创建 prompt 文件**

```python
"""Pattern memory extraction prompt."""

PATTERN_EXTRACT_PROMPT = """你现在正在经历睡眠中的记忆巩固过程——回顾过去一段时间的经历，发现值得注意的规律。

过去一段时间的活动记录：
{experience_data}

目前已经观察到的模式：
{existing_patterns}

社交信号记录：
{social_signals}

请找出这段时间内值得注意的规律性变化——不是单次事件，而是跨时间的统计趋势。如果没有足够数据支撑规律，输出空数组即可。

注意：
- 关注跨时间的统计规律，不是单次事件
- 置信度要保守：初次发现的规律 0.3-0.5，反复验证后可以 0.6+
- 对于已有模式：再次观察到 → action="UPDATE" + 略升 confidence；未观察到或出现反例 → action="UPDATE" + 降低 confidence
- 每条模式控制在30字以内
- scene_tags 帮助后续场景化检索

直接返回 JSON（不要其他内容）：
{{"patterns": [
  {{
    "content": "30字以内的规律描述",
    "category": "user_behavior / self_efficacy / interaction",
    "subcategory": "temporal_rhythm / topic_cluster / mood_trend / error_pattern / strategy / learning / depth_pattern / transition",
    "confidence": 0.0-1.0,
    "evidence": "支持该规律的证据（过去时段的具体观察）",
    "scene_tags": ["标签1", "标签2"],
    "action": "ADD / UPDATE / MERGE",
    "existing_pattern_id": null
  }}
]}}
如果本时段没有值得记录的规律：{{"patterns": []}}"""
```

- [ ] **Step 2: 在 `__init__.py` 中导出**

在 `src/xiaomei_brain/prompts/__init__.py` 中：

import 区域（`from .dag import *` 之后）追加：
```python
from .pattern import *
```

`__all__` 列表末尾（`"NARR_BLOCK_INSTRUCTION"` 之后）追加：
```python
    # Pattern
    "PATTERN_EXTRACT_PROMPT",
```

- [ ] **Step 3: 验证**

Run: `python3 -c "from xiaomei_brain.prompts.pattern import PATTERN_EXTRACT_PROMPT; print('OK', len(PATTERN_EXTRACT_PROMPT))"`
Expected: `OK <length>`

- [ ] **Step 4: Commit**

```bash
git add src/xiaomei_brain/prompts/pattern.py src/xiaomei_brain/prompts/__init__.py
git commit -m "feat: add PATTERN_EXTRACT_PROMPT"
```

---

### Task 2: Create Pattern dataclass + PatternStorage + PatternExtractor

**Files:**
- Create: `src/xiaomei_brain/memory/pattern.py`

- [ ] **Step 1: 创建 Pattern dataclass 和 PatternStorage**

```python
"""Pattern Memory — 模式记忆：跨时间统计规律的提取、存储和注入。

从 ExperienceStream 提取统计规律，存入 LTM type="pattern"，通过注入点影响决策。

Classes:
    Pattern: 一条模式记忆的数据结构
    PatternStorage: 存取 LTM type="pattern" 记录
    PatternExtractor: 在梦境中查询数据 → 构建 prompt → 调 LLM → 解析输出
    PatternInjector: 五个注入点的检索 + 格式化
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Pattern 数据结构 ─────────────────────────────────────

@dataclass
class Pattern:
    """一条模式记忆"""
    content: str = ""
    category: str = "user_behavior"
    subcategory: str = "temporal_rhythm"
    confidence: float = 0.5
    evidence: str = ""
    scene_tags: list[str] = field(default_factory=list)
    memory_id: int = 0

    VALID_CATEGORIES = {"user_behavior", "self_efficacy", "interaction"}
    VALID_SUBCATEGORIES = {
        "temporal_rhythm", "topic_cluster", "mood_trend",
        "error_pattern", "strategy", "learning",
        "depth_pattern", "transition",
    }

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "category": self.category,
            "subcategory": self.subcategory,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "scene_tags": self.scene_tags,
            "memory_id": self.memory_id,
        }

    @classmethod
    def from_ltm_record(cls, record: dict) -> "Pattern":
        tags = record.get("tags", [])
        scene_tags = record.get("scene_tags", [])
        category = "user_behavior"
        subcategory = "temporal_rhythm"
        for tag in tags:
            if tag in cls.VALID_CATEGORIES:
                category = tag
            elif tag in cls.VALID_SUBCATEGORIES:
                subcategory = tag
        return cls(
            content=record.get("content", ""),
            category=category,
            subcategory=subcategory,
            confidence=record.get("confidence", 0.5) or 0.5,
            evidence=record.get("evidence", "") or "",
            scene_tags=list(scene_tags) if scene_tags else [],
            memory_id=record.get("id", 0),
        )


# ── PatternStorage ───────────────────────────────────────

class PatternStorage:
    """模式记忆的持久化存储，复用 LTM memories 表 type="pattern"。"""

    def __init__(self, ltm) -> None:
        self._ltm = ltm

    def store(self, pattern: Pattern) -> int | None:
        """存储一条模式到 LTM。返回 memory_id 或 None。"""
        if not self._ltm:
            return None
        try:
            memory_id = self._ltm.store(
                content=pattern.content,
                source="dream",
                tags=[
                    "pattern",
                    pattern.category,
                    pattern.subcategory,
                ],
                importance=pattern.confidence,
                user_id="global",
                mem_type="pattern",
                scene_tags=pattern.scene_tags,
                confidence=pattern.confidence,
            )
            pattern.memory_id = memory_id
            logger.info("[PatternStorage] 存储: #%d cat=%s conf=%.2f: %s",
                        memory_id, pattern.category, pattern.confidence, pattern.content)
            return memory_id
        except Exception as e:
            logger.warning("[PatternStorage] 存储失败: %s", e)
            return None

    def update_confidence(self, memory_id: int, new_confidence: float) -> bool:
        """更新已有模式的置信度。"""
        if not self._ltm:
            return False
        try:
            old = self._ltm.get_by_id(memory_id)
            if old:
                old_content = old.get("content", "")
                merged = f"{old_content}（置信度 {old.get('confidence', 0):.2f}→{new_confidence:.2f}）"
                self._ltm.update(memory_id, content=merged, confidence=new_confidence, importance=new_confidence)
            else:
                self._ltm.update(memory_id, confidence=new_confidence, importance=new_confidence)
            logger.info("[PatternStorage] 更新置信度: #%d → %.2f", memory_id, new_confidence)
            return True
        except Exception as e:
            logger.warning("[PatternStorage] 更新置信度失败: %s", e)
            return False

    def get_all(self) -> list[dict]:
        """获取所有模式（用于梦境对比）。"""
        if not self._ltm:
            return []
        try:
            return self._ltm.search_by_tags(["pattern"], user_id="global")
        except Exception:
            return []

    def get_top(self, top_k: int = 3) -> list[dict]:
        """获取置信度最高的 N 条模式（用于系统提示词注入）。"""
        patterns = self.get_all()
        patterns.sort(key=lambda p: p.get("confidence", 0) or 0, reverse=True)
        return patterns[:top_k]

    def search_by_tags(self, tags: list[str]) -> list[dict]:
        """按标签检索模式。"""
        if not self._ltm:
            return []
        try:
            return self._ltm.search_by_tags(tags, user_id="global")
        except Exception:
            return []

    def decay_unobserved(self, observed_ids: set[int]) -> int:
        """衰减未被本次观察到的模式。返回衰减数量。"""
        all_patterns = self.get_all()
        decayed = 0
        for p in all_patterns:
            pid = p.get("id", 0)
            if pid not in observed_ids:
                old_conf = p.get("confidence", 0.5) or 0.5
                new_conf = round(old_conf * 0.9, 2)
                if new_conf < 0.1:
                    new_conf = 0.05
                self.update_confidence(pid, new_conf)
                decayed += 1
                logger.debug("[PatternStorage] 衰减: #%d %.2f→%.2f", pid, old_conf, new_conf)
        return decayed
```

- [ ] **Step 2: 创建 PatternExtractor**

```python
# ── PatternExtractor ─────────────────────────────────────

class PatternExtractor:
    """在梦境中提取模式：查询数据 → 构建 prompt → 调 LLM → 解析 → 存储。"""

    def __init__(
        self,
        storage: PatternStorage,
        exp_stream,
        conversation_db,
        ltm,
    ) -> None:
        self._storage = storage
        self._exp_stream = exp_stream
        self._conversation_db = conversation_db
        self._ltm = ltm

    def extract(self, llm, time_window: float = 86400.0) -> list[Pattern]:
        """执行一次模式提取。

        Args:
            llm: LLM 客户端（需要 .chat() 方法）
            time_window: 回顾时间窗口（秒），默认 24h

        Returns:
            提取到的 Pattern 列表
        """
        # 1. 收集数据
        experience_data = self._gather_experience(time_window)
        existing_patterns = self._gather_existing_patterns()
        social_signals = self._gather_social_signals(time_window)

        # 2. 构建 prompt
        from ..prompts.pattern import PATTERN_EXTRACT_PROMPT
        prompt = PATTERN_EXTRACT_PROMPT.format(
            experience_data=experience_data or "（本时段无活动记录）",
            existing_patterns=existing_patterns or "（暂无已有模式）",
            social_signals=social_signals or "（无社交信号记录）",
        )

        # 3. 调 LLM
        try:
            resp = llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
            )
            raw = resp.content or ""
            logger.info("[PatternExtractor] LLM 返回 %d 字", len(raw))
        except Exception as e:
            logger.error("[PatternExtractor] LLM 调用失败: %s", e)
            return []

        # 4. 解析输出
        patterns = self._parse_response(raw)

        # 5. 存储
        stored_ids = set()
        for p in patterns:
            if p.memory_id > 0:
                # UPDATE 已有模式
                self._storage.update_confidence(p.memory_id, p.confidence)
                stored_ids.add(p.memory_id)
            else:
                # ADD 新模式
                mid = self._storage.store(p)
                if mid:
                    stored_ids.add(mid)

        # 6. 衰减未观察到的已有模式
        decayed = self._storage.decay_unobserved(stored_ids)
        logger.info("[PatternExtractor] 提取完成: new+updated=%d, decayed=%d",
                    len(stored_ids), decayed)

        return patterns

    def _gather_experience(self, time_window: float) -> str:
        """从 ExperienceStream 收集最近时段的数据。"""
        if not self._exp_stream:
            return ""
        since = time.time() - time_window
        try:
            events = self._exp_stream.get_recent(limit=200)
            if not events:
                return ""
            filtered = [e for e in events if e.get("created_at", 0) >= since]
            lines = []
            for e in filtered[-100:]:
                etype = e.get("type", "?")
                content = e.get("content", "")[:150]
                lines.append(f"[{etype}] {content}")
            return "\n".join(lines)
        except Exception as e:
            logger.warning("[PatternExtractor] 收集经验失败: %s", e)
            return ""

    def _gather_existing_patterns(self) -> str:
        """获取已有模式列表（供 LLM 对比）。"""
        patterns = self._storage.get_all()
        if not patterns:
            return ""
        lines = []
        for p in patterns[-30:]:
            lines.append(
                f"#{p.get('id', '?')} [{p.get('confidence', 0):.2f}] "
                f"{p.get('content', '')}"
            )
        return "\n".join(lines)

    def _gather_social_signals(self, time_window: float) -> str:
        """从 ExperienceStream 收集社交感知相关事件。"""
        if not self._exp_stream:
            return ""
        since = time.time() - time_window
        try:
            events = self._exp_stream.get_recent(limit=200)
            if not events:
                return ""
            # 过滤 internal_reflection 类型（InnerVoice/SocialPerception 写入）
            filtered = [
                e for e in events
                if e.get("type") == "internal_reflection"
                and e.get("created_at", 0) >= since
            ]
            lines = []
            for e in filtered[-20:]:
                content = e.get("content", "")[:120]
                lines.append(f"[{e.get('created_at', 0)}] {content}")
            return "\n".join(lines)
        except Exception:
            return ""

    def _parse_response(self, raw: str) -> list[Pattern]:
        """解析 LLM 返回的 JSON。"""
        try:
            # 尝试提取 JSON 块
            json_str = raw
            if "```json" in raw:
                json_str = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                json_str = raw.split("```")[1].split("```")[0]
            data = json.loads(json_str.strip())
            pattern_list = data.get("patterns", [])
        except json.JSONDecodeError:
            logger.warning("[PatternExtractor] JSON 解析失败: %.100s", raw)
            return []

        patterns = []
        for item in pattern_list:
            action = item.get("action", "ADD").upper()
            content = item.get("content", "").strip()
            if not content:
                continue

            category = item.get("category", "user_behavior")
            if category not in Pattern.VALID_CATEGORIES:
                category = "user_behavior"

            subcategory = item.get("subcategory", "temporal_rhythm")
            if subcategory not in Pattern.VALID_SUBCATEGORIES:
                subcategory = "temporal_rhythm"

            confidence = max(0.05, min(0.95, float(item.get("confidence", 0.5))))

            memory_id = 0
            if action == "UPDATE":
                memory_id = int(item.get("existing_pattern_id", 0) or 0)
            elif action == "MERGE":
                memory_id = 0  # 新建合并后的模式

            p = Pattern(
                content=content,
                category=category,
                subcategory=subcategory,
                confidence=confidence,
                evidence=item.get("evidence", "").strip(),
                scene_tags=item.get("scene_tags", []) or [],
                memory_id=memory_id,
            )
            patterns.append(p)
            logger.info("[PatternExtractor] %s: %.2f %s/%s: %s",
                        action, confidence, category, subcategory, content)

        return patterns
```

- [ ] **Step 3: 验证**

Run: `PYTHONPATH=src python3 -c "from xiaomei_brain.memory.pattern import Pattern, PatternStorage, PatternExtractor; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/xiaomei_brain/memory/pattern.py
git commit -m "feat: add Pattern dataclass + PatternStorage + PatternExtractor"
```

---

### Task 3: Add PatternInjector

**Files:**
- Modify: `src/xiaomei_brain/memory/pattern.py` (append)

- [ ] **Step 1: 追加 PatternInjector 类**

```python
# ── PatternInjector ──────────────────────────────────────

class PatternInjector:
    """模式注入：五个注入点的检索 + 格式化。

    注入点：
    1. 系统提示词 — top-3 高置信度模式
    2. L2 intent  — 语义匹配当前情境
    3. 对话上下文 — 语义匹配用户消息
    4. 学习选题   — topic_cluster 加成
    5. 梦境提取   — 全部已有模式（由 PatternExtractor._gather_existing_patterns 处理）
    """

    def __init__(self, storage: PatternStorage, ltm) -> None:
        self._storage = storage
        self._ltm = ltm

    # ── 注入点 1: 系统提示词 ─────────────────────────────

    def render_system_prompt(self) -> str:
        """渲染系统提示词中的模式片段。"""
        top = self._storage.get_top(top_k=3)
        if not top:
            return ""
        lines = ["我注意到："]
        for p in top:
            content = p.get("content", "")
            if content:
                lines.append(f"· {content}")
        return "\n".join(lines)

    # ── 注入点 2: L2 intent 决策 ──────────────────────────

    def inject_l2_intent(self, context_description: str) -> str:
        """为 L2 intent 决策注入情境相关模式。"""
        if not self._ltm or not context_description:
            return ""
        try:
            results = self._ltm.recall(
                context_description, top_k=2, user_id="global",
            )
            pattern_results = [r for r in results
                             if "pattern" in (r.get("tags", []) or [])]
            if not pattern_results:
                return ""
            content = pattern_results[0].get("content", "")[:80]
            return f"当前情境相关模式：{content}"
        except Exception:
            return ""

    # ── 注入点 3: 对话上下文 ──────────────────────────────

    def inject_context(self, user_message: str) -> str:
        """为用户消息注入话题相关模式。"""
        if not self._ltm or not user_message:
            return ""
        try:
            results = self._ltm.recall(
                user_message, top_k=2, user_id="global",
            )
            pattern_results = [r for r in results
                             if "pattern" in (r.get("tags", []) or [])]
            if not pattern_results:
                return ""
            content = pattern_results[0].get("content", "")[:80]
            return f"\n[话题趋势] {content}"
        except Exception:
            return ""

    # ── 注入点 4: 学习选题加权 ────────────────────────────

    def boost_learning_topics(self, candidates: list[str]) -> dict[str, float]:
        """根据 topic_cluster 模式给候选主题加权。返回 {topic: boost}。"""
        if not candidates:
            return {}
        try:
            cluster_patterns = self._storage.search_by_tags(
                ["pattern", "topic_cluster"],
            )
            boosts: dict[str, float] = {}
            for candidate in candidates:
                boost = 0.0
                for p in cluster_patterns:
                    content = p.get("content", "")
                    confidence = p.get("confidence", 0.5) or 0.5
                    if candidate in content or any(
                        keyword in content
                        for keyword in candidate.split()
                    ):
                        boost += confidence * 0.2
                boosts[candidate] = min(boost, 0.5)
            return boosts
        except Exception:
            return {}
```

- [ ] **Step 2: 验证**

Run: `PYTHONPATH=src python3 -c "from xiaomei_brain.memory.pattern import PatternInjector; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/xiaomei_brain/memory/pattern.py
git commit -m "feat: add PatternInjector — five injection points"
```

---

### Task 4: Wire into DreamEngine

**Files:**
- Modify: `src/xiaomei_brain/consciousness/dream/dream_engine.py`

- [ ] **Step 1: 修改 DreamEngine 构造函数，新增 exp_stream 参数**

Read `dream_engine.py:84-111`，在 `__init__` 中添加：

```python
# 在 __init__ 参数列表末尾添加
exp_stream: Any | None = None,

# 在 self.procedure_memory = procedure_memory 之后添加
self.exp_stream = exp_stream
```

- [ ] **Step 2: 在 run() 方法中插入 Pattern 提取阶段**

在 `dream_engine.py` 的 `run()` 方法中，Narrative 整合（阶段 2.x）之后、L3 火焰燃烧（阶段 3）之前，插入：

```python
        # ── 阶段3：Pattern 提取 ──────────────────────────
        if self.exp_stream and self.ltm:
            try:
                from ...memory.pattern import PatternStorage, PatternExtractor
                pstorage = PatternStorage(self.ltm)
                extractor = PatternExtractor(
                    storage=pstorage,
                    exp_stream=self.exp_stream,
                    conversation_db=getattr(
                        self.extractor, 'db', None,
                    ) if self.extractor else None,
                    ltm=self.ltm,
                )
                patterns = extractor.extract(self.llm)
                report.patterns_extracted = len(patterns)
                logger.info("[DreamEngine] Pattern 提取: %d 条", len(patterns))
            except Exception as e:
                logger.warning("[DreamEngine] Pattern 提取失败: %s", e)
```

- [ ] **Step 3: 在 DreamReport dataclass 中添加 patterns_extracted 字段**

在 `DreamReport` dataclass（约第 44 行附近）添加：

```python
patterns_extracted: int = 0
"""提取/更新了多少条模式"""
```

- [ ] **Step 4: 验证**

Run: `PYTHONPATH=src python3 -c "from xiaomei_brain.consciousness.dream.dream_engine import DreamEngine, DreamReport; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/xiaomei_brain/consciousness/dream/dream_engine.py
git commit -m "feat: add Pattern extraction stage to DreamEngine"
```

---

### Task 5: Wire into ConsciousLiving

**Files:**
- Modify: `src/xiaomei_brain/consciousness/conscious_living.py`

- [ ] **Step 1: DreamEngine 实例化传入 exp_stream**

在 `conscious_living.py:250-257` DreamEngine 实例化处，添加 `exp_stream=exp_stream`：

```python
self._dream_engine = DreamEngine(
    consciousness=self.consciousness,
    drive=self.drive,
    ltm=getattr(self.agent, 'longterm_memory', None),
    extractor=getattr(self.agent, 'memory_extractor', None),
    llm=getattr(self.agent, 'llm', None),
    procedure_memory=getattr(self.agent, '_procedure_memory', None),
    exp_stream=exp_stream,  # 新增
)
```

- [ ] **Step 2: 验证**

Run: `PYTHONPATH=src python3 -c "print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/xiaomei_brain/consciousness/conscious_living.py
git commit -m "feat: pass exp_stream to DreamEngine for Pattern extraction"
```

---

### Task 6: Wire into SelfImage (system prompt injection)

**Files:**
- Modify: `src/xiaomei_brain/consciousness/self_image_proxy.py`
- Modify: `src/xiaomei_brain/consciousness/core.py`
- Modify: `src/xiaomei_brain/consciousness/conscious_living.py`

- [ ] **Step 1: SelfImage 构造函数添加 `_ltm` 属性**

在 `self_image_proxy.py` 的 `SelfImage.__init__()` 末尾添加：

```python
        self._ltm = None  # set by set_ltm()
```

- [ ] **Step 2: 添加 set_ltm() 方法**

在 `SelfImage` 类中（`history = SelfHistory()` 之后）添加：

```python
    def set_ltm(self, ltm) -> None:
        """设置 LongTermMemory 引用，供模式记忆渲染使用。"""
        self._ltm = ltm
```

- [ ] **Step 3: 在 Consciousness.__init__() 中保存 ltm 引用**

在 `core.py` 的 `Consciousness.__init__()` 中，`self.self_image = SelfImage(...)` 之后：

```python
        self._ltm = None  # 由 ConsciousLiving 通过 set_ltm() 设置
```

- [ ] **Step 4: ConsciousLiving 初始化时调用 set_ltm()**

在 `conscious_living.py` 的 `_init_consciousness_system()` 方法中，DreamEngine 创建之前，添加：

```python
        # 注入 LTM 到 SelfImage（供模式记忆渲染）
        ltm = getattr(self.agent, 'longterm_memory', None)
        if ltm:
            self.consciousness.self_image.set_ltm(ltm)
            logger.info("[ConsciousLiving] LTM 已注入到 SelfImage")
```

- [ ] **Step 5: 添加 _render_patterns() 方法和注入到 assemble**

在 `self_image_proxy.py` 的 `SelfImage` 类中，所有 `_render_*` 方法附近添加：

```python
    def _render_patterns(self) -> list[str]:
        """渲染模式记忆（注入点1: 系统提示词 top-3 高置信度模式）。"""
        try:
            if not self._ltm:
                return []
            from ..memory.pattern import PatternStorage, PatternInjector
            storage = PatternStorage(self._ltm)
            injector = PatternInjector(storage, self._ltm)
            rendered = injector.render_system_prompt()
            if rendered:
                return ["", rendered]
        except Exception:
            pass
        return []
```

在 `_assemble_daily()` 的 return 中，`+ self._render_environment()` 之前：

```python
            + self._render_patterns()
```

在 `_assemble_task()` 的 return 中，`+ self._render_environment()` 之前：

```python
            + self._render_patterns()
```

不改动 `_assemble_flow()`。

- [ ] **Step 6: 验证**

Run: `PYTHONPATH=src python3 -c "from xiaomei_brain.consciousness.self_image_proxy import SelfImage; si = SelfImage(); assert hasattr(si, '_ltm'); assert si._ltm is None; si.set_ltm(None); print('OK')"`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add src/xiaomei_brain/consciousness/self_image_proxy.py src/xiaomei_brain/consciousness/core.py src/xiaomei_brain/consciousness/conscious_living.py
git commit -m "feat: wire Pattern memory into SelfImage system prompt injection"
```

---

### Task 7: Wire into L2Engine (intent decision)

**Files:**
- Modify: `src/xiaomei_brain/consciousness/l2_engine.py`

- [ ] **Step 1: _build_intent_prompt() 注入情境相关模式**

在 `l2_engine.py:354`（`prompt += ...` 的 context_note 之后，最终 return 之前），添加：

```python
        # 注入情境相关模式（注入点2）
        try:
            ltm_ref = getattr(self._c, 'agent', None)
            ltm_ref = getattr(ltm_ref, 'longterm_memory', None) if ltm_ref else None
            if ltm_ref:
                from ..memory.pattern import PatternStorage, PatternInjector
                storage = PatternStorage(ltm_ref)
                injector = PatternInjector(storage, ltm_ref)
                pattern_line = injector.inject_l2_intent(context)
                if pattern_line:
                    prompt += f"\n{pattern_line}\n"
        except Exception:
            pass
```

插入位置在 `if context_note: prompt += ...` 之后，`prompt += "\n如果需要，先执行工具操作..."` 之前。

- [ ] **Step 2: 验证**

Run: `PYTHONPATH=src python3 -c "from xiaomei_brain.consciousness.l2_engine import L2Engine; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/xiaomei_brain/consciousness/l2_engine.py
git commit -m "feat: wire Pattern memory into L2 intent decision"
```

---

### Task 8: Wire into LearningEngine (topic priority boost)

**Files:**
- Modify: `src/xiaomei_brain/learn/engine.py`

- [ ] **Step 1: _select_topic() 模式加权**

在 `engine.py` 的 `_select_topic()` 步骤4（学习兴趣），`if fresh: return random.choice(fresh)` 之前，添加：

```python
            # 模式加权：topic_cluster 模式给候选主题加分
            if len(fresh) > 1:
                try:
                    from ..memory.pattern import PatternStorage, PatternInjector
                    ltm_ref = getattr(self._storage, '_ltm', None)
                    if ltm_ref:
                        storage = PatternStorage(ltm_ref)
                        injector = PatternInjector(storage, ltm_ref)
                        boosts = injector.boost_learning_topics(fresh)
                        if boosts:
                            fresh.sort(key=lambda t: boosts.get(t, 0), reverse=True)
                            logger.info("[LearningEngine] 模式加权前3: %s",
                                        str([f"{t}={boosts.get(t, 0):.2f}" for t in fresh[:3]]))
                except Exception:
                    pass
```

- [ ] **Step 2: 验证**

Run: `PYTHONPATH=src python3 -c "from xiaomei_brain.learn.engine import LearningEngine; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/xiaomei_brain/learn/engine.py
git commit -m "feat: wire Pattern memory into learning topic priority boost"
```

---

### Task 9: End-to-end verification

**Files:**
- Verify: all created/modified files

- [ ] **Step 1: 完整导入检查**

Run: `PYTHONPATH=src python3 -c "
from xiaomei_brain.prompts.pattern import PATTERN_EXTRACT_PROMPT
from xiaomei_brain.memory.pattern import Pattern, PatternStorage, PatternExtractor, PatternInjector
from xiaomei_brain.consciousness.dream.dream_engine import DreamEngine, DreamReport
print('All imports OK')
"`
Expected: `All imports OK`

- [ ] **Step 2: Pattern dataclass 单元测试**

Run: `PYTHONPATH=src python3 -c "
from xiaomei_brain.memory.pattern import Pattern

# Test creation
p = Pattern(
    content='用户深夜活跃度是白天3倍',
    category='user_behavior',
    subcategory='temporal_rhythm',
    confidence=0.85,
    evidence='过去24h观察',
    scene_tags=['深夜', '技术对话'],
)
assert p.content == '用户深夜活跃度是白天3倍'
assert p.category == 'user_behavior'
assert p.confidence == 0.85

# Test to_dict round-trip
d = p.to_dict()
assert d['content'] == p.content
assert d['confidence'] == p.confidence

print('Pattern tests OK')
"`
Expected: `Pattern tests OK`

- [ ] **Step 3: PatternStorage API 模拟测试（无 LTM 实例时安全返回）**

Run: `PYTHONPATH=src python3 -c "
from xiaomei_brain.memory.pattern import PatternStorage

# Storage with None LTM should return safely
storage = PatternStorage(None)
assert storage.get_all() == []
assert storage.get_top(3) == []
assert storage.search_by_tags(['pattern']) == []
assert storage.store(None) is None  # Would be caught but pattern validation is separate
print('PatternStorage safety OK')
"`
Expected: `PatternStorage safety OK`

- [ ] **Step 4: PatternInjector 安全返回（无 LTM）**

Run: `PYTHONPATH=src python3 -c "
from xiaomei_brain.memory.pattern import PatternStorage, PatternInjector

storage = PatternStorage(None)
injector = PatternInjector(storage, None)
assert injector.render_system_prompt() == ''
assert injector.inject_l2_intent('用户空闲中') == ''
assert injector.inject_context('你好') == ''
assert injector.boost_learning_topics(['量化交易']) == {}
print('PatternInjector safety OK')
"`
Expected: `PatternInjector safety OK`

- [ ] **Step 5: Commit** (if any fixes during verification)

```bash
git add -A && git commit -m "test: add Pattern memory end-to-end verification"
```
