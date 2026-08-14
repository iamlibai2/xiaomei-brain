"""Aggregate technical runtime state into user-facing Agent capabilities."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import math
import re
import shutil
import threading
from pathlib import Path
from typing import Any, Iterable

from xiaomei_brain.base.persistent_vector_index import PersistentVectorIndex

from .loader import CapabilityManifestLoader
from .models import (
    CapabilityComponent,
    CapabilityDefinition,
    CapabilityIssue,
    CapabilityOutcomeView,
    CapabilityRequirement,
    CapabilityStatus,
    CapabilityView,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ComponentHealth:
    available: bool
    code: str = ""
    message: str = ""
    warning: bool = False


class CapabilityRegistry:
    """A read-only capability view for one initialized Agent.

    The registry never loads or executes components.  It only observes the
    registries that already belong to the Agent and computes a truthful view.
    """

    def __init__(
        self,
        *,
        plugin_registry: Any,
        tool_registry: Any | None = None,
        skill_loader: Any | None = None,
        dynamic_tool_loader: Any | None = None,
        configuration: Any | None = None,
        tool_service_configuration: Any | None = None,
        runtime_probes: dict[str, Any] | None = None,
        definitions: Iterable[CapabilityDefinition] | None = None,
        vector_index_path: str | Path | None = None,
    ) -> None:
        self._plugin_registry = plugin_registry
        self._tool_registry = tool_registry
        self._skill_loader = skill_loader
        self._dynamic_tool_loader = dynamic_tool_loader
        self._configuration = configuration
        self._tool_service_configuration = tool_service_configuration
        self._runtime_probes = dict(runtime_probes or {})
        loaded = list(definitions) if definitions is not None else CapabilityManifestLoader().load()
        self._definitions = {definition.id: definition for definition in loaded}
        self._discovery_lock = threading.Lock()
        self._discovery_entries: list[dict[str, Any]] | None = None
        self._discovery_build_started = False
        self._vector_index = (
            PersistentVectorIndex(
                vector_index_path,
                "capability_embeddings",
                "capability.index",
            )
            if vector_index_path is not None
            else None
        )
        self._apply_activation_policy()

    def build_discovery_index(self) -> int:
        """Build the persistent index during Agent startup, not first chat."""
        return len(self._ensure_discovery_entries())

    def start_discovery_index_build(self) -> None:
        """Warm the persistent index without blocking Agent availability."""
        if (
            self._vector_index is None
            or self._discovery_entries is not None
            or self._discovery_build_started
        ):
            return
        with self._discovery_lock:
            if self._discovery_build_started:
                return
            self._discovery_build_started = True
        threading.Thread(
            target=self._build_discovery_index_background,
            name="capability-vector-index",
            daemon=True,
        ).start()

    def _build_discovery_index_background(self) -> None:
        try:
            self._ensure_discovery_entries()
        except Exception:
            logger.exception("[Capability] background index build failed")
            with self._discovery_lock:
                self._discovery_entries = []

    def list(self, *, person_id: str = "") -> list[CapabilityView]:
        skill_names = self._load_skill_names()
        return [
            self._build_view(
                self._definitions[key],
                person_id=person_id,
                _skill_names=skill_names,
            )
            for key in sorted(self._definitions)
        ]

    def get(self, capability_id: str, *, person_id: str = "") -> CapabilityView | None:
        definition = self._definitions.get(str(capability_id).strip())
        return (
            self._build_view(
                definition,
                person_id=person_id,
                _skill_names=self._load_skill_names(),
            )
            if definition
            else None
        )

    def set_enabled(self, capability_id: str, enabled: bool, *, person_id: str = "") -> CapabilityView | None:
        """Persist activation and immediately update Skill/Tool visibility."""
        normalized = str(capability_id or "").strip()
        definition = self._definitions.get(normalized)
        if definition is None:
            return None
        if self._configuration is None:
            raise RuntimeError("能力配置服务尚未初始化")
        self._configuration.set_enabled(normalized, enabled)
        self._apply_activation_policy()
        return self._build_view(definition, person_id=person_id)

    def bind_dynamic_tool_loader(self, loader: Any | None) -> None:
        """Attach the loader created after capability tools enter the index."""
        self._dynamic_tool_loader = loader
        self._apply_activation_policy()

    def to_list(self, *, include_technical: bool = False, person_id: str = "") -> list[dict[str, Any]]:
        return [view.to_dict(include_technical=include_technical) for view in self.list(person_id=person_id)]

    def resolve(self, query: str, *, limit: int = 3, person_id: str = "") -> list[CapabilityView]:
        """Return capabilities semantically relevant to one task description."""
        return [
            item["view"]
            for item in self.discover(
                query,
                limit=limit,
                person_id=person_id,
                min_score=0.50,
            )
        ]

    def discover(
        self,
        query: str,
        *,
        limit: int = 3,
        person_id: str = "",
        min_score: float | None = 0.50,
    ) -> list[dict[str, Any]]:
        """Search capability outcomes through the shared embedding service.

        Capability discovery deliberately has no lexical fallback.  A nearest
        two-character overlap such as ``file`` must not silently become a
        platform route such as Feishu Office when semantic retrieval is down.
        """
        normalized = self._normalized_text(query)
        if not normalized:
            return []
        try:
            if self._vector_index is not None and self._discovery_entries is None:
                self.start_discovery_index_build()
                return []
            entries = self._ensure_discovery_entries()
            from xiaomei_brain.base.shared_embedder import SharedEmbedder
            query_vector = SharedEmbedder.get_or_create().embed(
                normalized,
                source="capability.discover",
            )
        except Exception:
            logger.warning("[Capability] semantic discovery unavailable", exc_info=True)
            return []

        best: dict[str, tuple[float, dict[str, Any]]] = {}
        for entry in entries:
            score = self._cosine_similarity(query_vector, entry["vector"])
            current = best.get(entry["capability_id"])
            if current is None or score > current[0]:
                best[entry["capability_id"]] = (score, entry)
        all_ranked = sorted(best.values(), key=lambda item: (-item[0], item[1]["capability_id"]))
        ranked = [
            item for item in all_ranked
            if min_score is None or item[0] >= min_score
        ]
        skill_names = self._load_skill_names()
        result: list[dict[str, Any]] = []
        for score, entry in ranked[:max(1, int(limit or 1))]:
            definition = self._definitions[entry["capability_id"]]
            result.append({
                "view": self._build_view(definition, person_id=person_id, _skill_names=skill_names),
                "outcome_id": entry["outcome_id"],
                "score": round(score, 4),
            })
        from xiaomei_brain.base.vector_trace import record_vector_trace
        selected_ids = [item["view"].id for item in result]
        record_vector_trace(
            source="capability.discover",
            phase="retrieval",
            query=normalized,
            candidates=[{
                "id": entry["capability_id"],
                "name": self._definitions[entry["capability_id"]].name,
                "score": round(score, 4),
                "outcome_id": entry["outcome_id"],
                "selected": entry["capability_id"] in selected_ids,
            } for score, entry in all_ranked[:50]],
            selected=selected_ids,
            threshold=min_score,
            metadata={"top_k": limit, "metric": "cosine_similarity"},
        )
        return result

    def _ensure_discovery_entries(self) -> list[dict[str, Any]]:
        if self._discovery_entries is not None:
            return self._discovery_entries
        with self._discovery_lock:
            if self._discovery_entries is not None:
                return self._discovery_entries
            pending: list[dict[str, Any]] = []
            for definition in self._definitions.values():
                for outcome in definition.outcomes:
                    descriptor = "\n".join([
                        f"Capability: {definition.name} ({definition.id})",
                        f"Category: {definition.category}",
                        f"Purpose: {definition.summary}",
                        "Aliases: " + "；".join(definition.aliases),
                        f"Outcome: {outcome.name}",
                        f"Outcome purpose: {outcome.description}",
                    ])
                    search_texts = [descriptor]
                    search_texts.extend(
                        f"{alias} {outcome.name}: {outcome.description}"
                        for alias in definition.aliases
                    )
                    search_texts.extend(
                        f"{definition.name} {outcome.name}: {example}"
                        for example in (outcome.examples or definition.examples)
                    )
                    # Boundaries are intentionally excluded from positive
                    # vectors. Embeddings do not model negation reliably, so
                    # "not for PPT" can otherwise make an HTML capability
                    # rank higher for a PPT request.
                    for index, text in enumerate(search_texts):
                        pending.append({
                            "id": f"{definition.id}::{outcome.id}::{index}",
                            "capability_id": definition.id,
                            "outcome_id": outcome.id,
                            "text": text,
                        })
            if self._vector_index is not None:
                vectors = self._vector_index.sync(
                    ((entry["id"], entry["text"]) for entry in pending),
                    batch_size=4,
                    yield_seconds=0.02,
                )
                for entry in pending:
                    vector = vectors.get(entry["id"])
                    if vector is not None:
                        entry["vector"] = vector
                pending = [entry for entry in pending if "vector" in entry]
            else:
                # Tests and small standalone integrations may omit a cache
                # path; retain the previous in-memory behaviour for them.
                from xiaomei_brain.base.shared_embedder import SharedEmbedder
                texts = [entry["text"] for entry in pending]
                embedded = SharedEmbedder.get_or_create().embed_batch(
                    texts,
                    source="capability.index",
                ) if texts else []
                for entry, vector in zip(pending, embedded):
                    entry["vector"] = vector
            self._discovery_entries = pending
            return self._discovery_entries

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return -1.0
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if not left_norm or not right_norm:
            return -1.0
        return dot / (left_norm * right_norm)

    def select_execution_components(
        self,
        query: str,
        *,
        limit: int = 3,
        person_id: str = "",
    ) -> tuple[list[str], list[str]]:
        """Resolve deterministic Tool and Skill dependencies for one request.

        Capability manifests define the reliable execution floor. Semantic
        retrieval may still add optional tools, but cannot remove these.
        """
        tool_names: list[str] = []
        skill_names: list[str] = []
        selected_count = 0
        for match in self.discover(
            query,
            limit=max(limit, len(self._definitions)),
            person_id=person_id,
        ):
            view = match["view"]
            if view.status not in {CapabilityStatus.READY, CapabilityStatus.DEGRADED}:
                continue
            if selected_count >= limit:
                break
            selected_count += 1
            definition = self._definitions.get(view.id)
            if definition is None:
                continue
            selected_outcomes = [
                outcome for outcome in definition.outcomes
                if outcome.id == match["outcome_id"]
            ]

            component_ids = {
                component_id
                for outcome in selected_outcomes
                for component_id in outcome.components
            }
            component_ids.update(
                component.id for component in definition.components
                if component.required
            )
            for component in definition.components:
                if component.id not in component_ids:
                    continue
                if component.kind == "tool" and component.target not in tool_names:
                    tool_names.append(component.target)
                elif component.kind == "skill" and component.target not in skill_names:
                    skill_names.append(component.target)
        return tool_names, skill_names

    def prepare_execution_selection(
        self,
        query: str,
        *,
        scope_id: str,
        person_id: str = "",
        limit: int = 1,
    ) -> list[str]:
        """Pin Capability and Skill dependencies for one scoped ReAct run."""
        return self.prepare_execution_selection_details(
            query,
            scope_id=scope_id,
            person_id=person_id,
            limit=limit,
        )["skills"]

    def prepare_execution_selection_details(
        self,
        query: str,
        *,
        scope_id: str,
        person_id: str = "",
        limit: int = 1,
    ) -> dict[str, Any]:
        """Return semantic Capability summaries without silently routing work.

        Dependencies are activated only after explicit discovery or an
        explicitly selected Skill.  Prefetch is informative and reversible.
        """
        candidates = self.discover(
            query,
            limit=max(limit, len(self._definitions)),
            person_id=person_id,
        )
        selected_capabilities = [
            {
                "id": match["view"].id,
                "name": match["view"].name,
                "status": match["view"].status.value,
                "outcome_id": match["outcome_id"],
                "score": match["score"],
            }
            for match in candidates
            if match["view"].status in {CapabilityStatus.READY, CapabilityStatus.DEGRADED}
        ][:max(1, limit)]
        return {
            "capabilities": selected_capabilities,
            "tools": [],
            "skills": [],
        }

    def build_context(self, query: str, *, limit: int = 3, person_id: str = "") -> str:
        """Build a compact runtime-truth block for the current conversation."""
        views = self.resolve(query, limit=limit, person_id=person_id)
        return self.render_context(views)

    def render_context(self, views: Iterable[CapabilityView]) -> str:
        """Render already-resolved capabilities without a second search."""
        views = list(views)
        if not views:
            return ""
        labels = {
            CapabilityStatus.READY: "可用",
            CapabilityStatus.DEGRADED: "部分可用",
            CapabilityStatus.NEEDS_SETUP: "需要完善",
            CapabilityStatus.PREPARING: "准备中",
            CapabilityStatus.UNAVAILABLE: "暂不可用",
            CapabilityStatus.ERROR: "异常",
            CapabilityStatus.DISABLED: "已关闭",
            CapabilityStatus.NOT_ACQUIRED: "未获得",
        }
        lines = [
            "<相关能力>",
            "以下是当前 Agent 运行环境确认的能力事实。根据真实状态行动，不要仅凭常识声称具备未列出的工具或服务。"
            "如果任务依赖一项未就绪或已关闭的能力，明确说明限制并给出已有配置入口；"
            "不要假装完成，也不要为了绕过能力状态而擅自改用不等价的底层命令。",
        ]
        for view in views:
            available = "、".join(
                outcome.name for outcome in view.outcomes if outcome.available
            ) or "无"
            lines.append(
                f"- {view.name} [{labels[view.status]}]：{view.summary}；当前可完成：{available}。"
            )
            limitations = list(dict.fromkeys(
                limitation
                for outcome in view.outcomes
                for limitation in outcome.limitations
            ))
            if limitations:
                lines.append(f"  限制：{'；'.join(limitations[:3])}")
            if view.status in {
                CapabilityStatus.NEEDS_SETUP,
                CapabilityStatus.PREPARING,
                CapabilityStatus.DISABLED,
            }:
                setup_locations = (
                    [self._setup_location("capabilities")]
                    if view.status == CapabilityStatus.DISABLED
                    else [
                        self._setup_location(action.get("section", ""))
                        for action in view.actions
                        if action.get("section")
                    ]
                )
                if setup_locations:
                    lines.append(f"  完善入口：{'；'.join(dict.fromkeys(setup_locations))}")
                    lines.append(
                        f"  如果当前具体任务因此受阻，调用 request_capability_setup，"
                        f"capability_id 使用 {view.id}，在当前 Desktop 会话提供配置入口。"
                    )
        lines.append("</相关能力>")
        return "\n".join(lines)

    @staticmethod
    def _setup_location(section: str) -> str:
        labels = {
            "models": "Agent 设置 > 模型",
            "media": "Agent 设置 > 媒体服务",
            "search": "Agent 设置 > 联网搜索",
            "channels": "Agent 设置 > 渠道与绑定",
            "capabilities": "Agent 设置 > 能力",
        }
        return labels.get(section, f"Agent 设置 > {section}")

    @staticmethod
    def _normalized_text(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").lower()).strip()

    def _build_view(
        self,
        definition: CapabilityDefinition,
        *,
        person_id: str = "",
        _stack: frozenset[str] = frozenset(),
        _skill_names: frozenset[str] | None = None,
    ) -> CapabilityView:
        skill_names = _skill_names if _skill_names is not None else self._load_skill_names()
        enabled = self._is_enabled(definition.id)
        health = {
            component.id: self._component_health(
                component,
                person_id=person_id,
                skill_names=skill_names,
            )
            for component in definition.components
        }
        requirement_health = {
            requirement.id: self._requirement_health(
                requirement,
                person_id=person_id,
                stack=_stack | {definition.id},
                skill_names=skill_names,
            )
            for requirement in definition.requirements
        }

        outcomes: list[CapabilityOutcomeView] = []
        for outcome in definition.outcomes:
            limitations = (("此能力已关闭",) if not enabled else tuple(
                health[component_id].message
                for component_id in outcome.components
                if component_id in health and not health[component_id].available
            ) + tuple(
                requirement_health[requirement.id].message
                for requirement in definition.requirements
                if requirement.required
                and requirement.outcomes
                and outcome.id in requirement.outcomes
                and not requirement_health[requirement.id].available
            ))
            outcomes.append(CapabilityOutcomeView(
                id=outcome.id,
                name=outcome.name,
                description=outcome.description,
                available=not limitations,
                limitations=limitations,
            ))

        issues: list[CapabilityIssue] = []
        for component in definition.components:
            state = health[component.id]
            if state.message and (not state.available or state.warning):
                issues.append(CapabilityIssue(
                    code=state.code,
                    message=state.message,
                    component_id=component.id,
                    setup_section=component.setup_section,
                    setup_target=component.target if component.setup_section else "",
                    setup_label=(f"配置{component.label}" if component.setup_section else ""),
                ))
        for requirement in definition.requirements:
            state = requirement_health[requirement.id]
            if state.message and (not state.available or state.warning):
                issues.append(CapabilityIssue(
                    code=state.code,
                    message=state.message,
                    component_id=requirement.id,
                    setup_section=requirement.setup_section,
                    setup_target=requirement.target if requirement.setup_section else "",
                    setup_label=(f"配置{requirement.label}" if requirement.setup_section else ""),
                ))

        required_failures = [
            health[component.id]
            for component in definition.components
            if component.required and not health[component.id].available
        ]
        required_failures.extend(
            requirement_health[requirement.id]
            for requirement in definition.requirements
            if requirement.required
            and not requirement.outcomes
            and not requirement_health[requirement.id].available
        )
        available_count = sum(1 for outcome in outcomes if outcome.available)
        warning_present = (
            any(state.warning for state in health.values())
            or any(state.warning for state in requirement_health.values())
        )
        if not enabled:
            status = CapabilityStatus.DISABLED
        elif required_failures:
            failure_codes = {state.code for state in required_failures}
            service_configured = any(
                component.kind == "tool_service" and health[component.id].available
                for component in definition.components
            )
            setup_codes = {
                "configuration_required",
                "authorization_required",
                "identity_required",
                "runtime_missing",
                "skill_missing",
                "executable_missing",
                "service_missing",
                "capability_disabled",
                "capability_needs_setup",
            }
            if failure_codes and failure_codes <= (setup_codes | {"tool_missing"}):
                status = CapabilityStatus.NEEDS_SETUP
            elif "tool_missing" in failure_codes and service_configured:
                status = CapabilityStatus.PREPARING
            else:
                status = (
                    CapabilityStatus.ERROR
                    if any(state.code == "component_error" for state in required_failures)
                    else CapabilityStatus.UNAVAILABLE
                )
        elif available_count == 0:
            status = (
                CapabilityStatus.ERROR
                if any(state.code == "component_error" for state in health.values())
                else CapabilityStatus.UNAVAILABLE
            )
        elif available_count < len(outcomes) or warning_present:
            status = CapabilityStatus.DEGRADED
        else:
            status = CapabilityStatus.READY

        technical_components = tuple({
            "id": component.id,
            "kind": component.kind,
            "target": component.target,
            "label": component.label,
            "required": component.required,
            "setup_section": component.setup_section,
            "available": health[component.id].available,
            "status": health[component.id].code or "ready",
        } for component in definition.components)
        technical_components += tuple({
            "id": requirement.id,
            "kind": f"requirement.{requirement.kind}",
            "target": requirement.target,
            "label": requirement.label,
            "required": requirement.required,
            "setup_section": requirement.setup_section,
            "outcomes": list(requirement.outcomes),
            "available": requirement_health[requirement.id].available,
            "status": requirement_health[requirement.id].code or "ready",
        } for requirement in definition.requirements)

        actions = tuple({
            "type": "open_settings",
            "section": component.setup_section,
            "target": component.target,
            "label": f"管理{component.label}" if health[component.id].available else f"配置{component.label}",
        } for component in definition.components if component.setup_section)
        actions += tuple({
            "type": "open_settings",
            "section": requirement.setup_section,
            "target": requirement.target,
            "label": (
                f"管理{requirement.label}"
                if requirement_health[requirement.id].available
                else f"配置{requirement.label}"
            ),
        } for requirement in definition.requirements if requirement.setup_section)

        return CapabilityView(
            id=definition.id,
            name=definition.name,
            summary=definition.summary,
            category=definition.category,
            status=status,
            enabled=enabled,
            outcomes=tuple(outcomes),
            examples=definition.examples,
            issues=tuple(issues),
            actions=actions,
            version=definition.version,
            source=definition.source,
            technical_components=technical_components,
            runtime_setup=any(component.kind == "runtime_probe" for component in definition.components),
        )

    def _requirement_health(
        self,
        requirement: CapabilityRequirement,
        *,
        person_id: str,
        stack: frozenset[str],
        skill_names: frozenset[str],
    ) -> _ComponentHealth:
        label = requirement.label or requirement.target
        state: _ComponentHealth
        if requirement.kind == "tool":
            tool = self._tool_registry.get(requirement.target) if self._tool_registry is not None else None
            state = (
                _ComponentHealth(True)
                if tool is not None
                else _ComponentHealth(False, "tool_missing", f"依赖的{label}尚未就绪")
            )
        elif requirement.kind == "executable":
            state = (
                _ComponentHealth(True)
                if shutil.which(requirement.target)
                else _ComponentHealth(False, "executable_missing", f"未找到运行依赖：{label}")
            )
        elif requirement.kind == "capability":
            target = self._definitions.get(requirement.target)
            if target is None:
                state = _ComponentHealth(False, "capability_missing", f"依赖的{label}尚未获得")
            elif requirement.target in stack:
                state = _ComponentHealth(False, "capability_cycle", f"能力依赖形成循环：{label}")
            elif not self._is_enabled(requirement.target):
                state = _ComponentHealth(False, "capability_disabled", f"依赖的{label}已关闭")
            else:
                target_view = self._build_view(
                    target,
                    person_id=person_id,
                    _stack=stack,
                    _skill_names=skill_names,
                )
                if target_view.status == CapabilityStatus.READY:
                    state = _ComponentHealth(True)
                elif target_view.status == CapabilityStatus.DEGRADED:
                    state = _ComponentHealth(
                        True,
                        "capability_degraded",
                        f"依赖的{label}目前部分可用",
                        True,
                    )
                elif target_view.status in {CapabilityStatus.NEEDS_SETUP, CapabilityStatus.PREPARING}:
                    state = _ComponentHealth(
                        False,
                        "capability_needs_setup",
                        f"依赖的{label}尚未就绪",
                    )
                else:
                    state = _ComponentHealth(
                        False,
                        "capability_unavailable",
                        f"依赖的{label}当前不可用",
                    )
        elif requirement.kind == "service":
            probe = self._runtime_probes.get(requirement.target)
            if probe is not None:
                try:
                    runtime_state = probe.inspect(person_id)
                    state = _ComponentHealth(
                        bool(runtime_state.available),
                        str(runtime_state.code or ""),
                        "" if runtime_state.available else str(runtime_state.message or f"{label}尚未就绪"),
                    )
                except Exception as exc:
                    state = _ComponentHealth(False, "component_error", f"{label}状态异常：{exc}")
            elif self._tool_service_configuration is not None:
                try:
                    service = self._tool_service_configuration.get(requirement.target)
                except Exception:
                    service = None
                if isinstance(service, dict) and service.get("configured") and service.get("enabled"):
                    state = _ComponentHealth(True)
                elif isinstance(service, dict):
                    state = _ComponentHealth(False, "configuration_required", f"{label}尚未配置或启用")
                else:
                    state = _ComponentHealth(False, "service_missing", f"依赖的{label}尚未接入")
            else:
                state = _ComponentHealth(False, "service_missing", f"依赖的{label}尚未接入")
        else:
            state = _ComponentHealth(False, "requirement_unknown", f"无法检查运行依赖：{label}")

        if not requirement.required and not state.available:
            return _ComponentHealth(False, state.code, state.message, True)
        return state

    def _is_enabled(self, capability_id: str) -> bool:
        if self._configuration is None:
            return True
        return self._configuration.is_enabled(capability_id)

    def _apply_activation_policy(self) -> None:
        """Hide disabled capability entry points without unloading components.

        A Tool or Skill shared by an enabled capability remains available.
        Plugin code stays loaded because its process lifecycle may also serve
        other capabilities; only the Agent-facing entry points are filtered.
        """
        enabled_tools: set[str] = set()
        disabled_tools: set[str] = set()
        enabled_skills: set[str] = set()
        disabled_skills: set[str] = set()
        for definition in self._definitions.values():
            enabled = self._is_enabled(definition.id)
            for component in definition.components:
                if component.kind == "tool":
                    (enabled_tools if enabled else disabled_tools).add(component.target)
                elif component.kind == "skill":
                    (enabled_skills if enabled else disabled_skills).add(component.target)

        disabled_tools -= enabled_tools
        disabled_skills -= enabled_skills
        set_registry_disabled_tools = getattr(self._tool_registry, "set_disabled_names", None)
        if callable(set_registry_disabled_tools):
            set_registry_disabled_tools(disabled_tools)
        set_disabled_skills = getattr(self._skill_loader, "set_disabled_names", None)
        if callable(set_disabled_skills):
            set_disabled_skills(disabled_skills)
        set_disabled_tools = getattr(self._dynamic_tool_loader, "set_disabled_names", None)
        if callable(set_disabled_tools):
            set_disabled_tools(disabled_tools)

    def _component_health(
        self,
        component: CapabilityComponent,
        *,
        person_id: str = "",
        skill_names: frozenset[str] | None = None,
    ) -> _ComponentHealth:
        label = component.label or component.id
        if component.kind == "plugin":
            plugin = self._plugin_registry.get_plugin(component.target)
            if plugin is None:
                return _ComponentHealth(False, "component_missing", f"{label}尚未加载")
            if plugin.status == "disabled":
                return _ComponentHealth(False, "component_disabled", f"{label}已关闭")
            if plugin.status == "error":
                detail = str(plugin.error or "加载失败").strip()
                return _ComponentHealth(False, "component_error", f"{label}不可用：{detail}")
            if plugin.status == "warn":
                detail = str(plugin.error or "运行条件不完整").strip()
                return _ComponentHealth(True, "component_warning", f"{label}存在限制：{detail}", True)
            return _ComponentHealth(True)

        if component.kind == "skill":
            names = skill_names if skill_names is not None else self._load_skill_names()
            if component.target in names:
                return _ComponentHealth(True)
            return _ComponentHealth(False, "skill_missing", f"{label}尚未就绪")

        if component.kind == "tool":
            tool = self._tool_registry.get(component.target) if self._tool_registry is not None else None
            if tool is not None:
                return _ComponentHealth(True)
            return _ComponentHealth(False, "tool_missing", f"{label}执行能力尚未就绪")

        if component.kind == "tool_service":
            if self._tool_service_configuration is None:
                return _ComponentHealth(False, "configuration_required", f"{label}尚未配置")
            try:
                service = self._tool_service_configuration.get(component.target)
            except Exception as exc:
                return _ComponentHealth(False, "component_error", f"{label}状态异常：{exc}")
            if not service.get("configured"):
                return _ComponentHealth(False, "configuration_required", f"{label}尚未配置")
            if not service.get("enabled"):
                return _ComponentHealth(False, "configuration_required", f"{label}尚未启用")
            return _ComponentHealth(True)

        if component.kind == "runtime_probe":
            probe = self._runtime_probes.get(component.target)
            if probe is None:
                return _ComponentHealth(False, "component_missing", f"{label}状态检查器尚未加载")
            try:
                state = probe.inspect(person_id)
            except Exception as exc:
                return _ComponentHealth(False, "component_error", f"{label}状态异常：{exc}")
            return _ComponentHealth(bool(state.available), str(state.code), str(state.message))

        if component.kind == "document_writer":
            writer = self._plugin_registry.get_document_writer(component.target)
            if writer is not None:
                return _ComponentHealth(True)
            return _ComponentHealth(False, "writer_missing", f"{label}生成功能暂不可用")

        if component.kind == "document_extractor":
            extractor_ids = {
                str(getattr(item, "extractor_id", ""))
                for item in self._plugin_registry.get_document_extractors()
            }
            if component.target in extractor_ids:
                return _ComponentHealth(True)
            return _ComponentHealth(False, "extractor_missing", f"{label}读取功能暂不可用")

        return _ComponentHealth(False, "component_unknown", f"{label}状态无法确认")

    def _load_skill_names(self) -> frozenset[str]:
        if self._skill_loader is None:
            return frozenset()
        try:
            return frozenset(self._skill_loader.list_names())
        except Exception:
            return frozenset()
