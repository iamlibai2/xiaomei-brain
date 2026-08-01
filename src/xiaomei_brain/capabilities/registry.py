"""Aggregate technical runtime state into user-facing Agent capabilities."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable

from .loader import CapabilityManifestLoader
from .models import (
    CapabilityComponent,
    CapabilityDefinition,
    CapabilityIssue,
    CapabilityOutcomeView,
    CapabilityStatus,
    CapabilityView,
)


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
        definitions: Iterable[CapabilityDefinition] | None = None,
    ) -> None:
        self._plugin_registry = plugin_registry
        self._tool_registry = tool_registry
        self._skill_loader = skill_loader
        self._dynamic_tool_loader = dynamic_tool_loader
        self._configuration = configuration
        self._tool_service_configuration = tool_service_configuration
        loaded = list(definitions) if definitions is not None else CapabilityManifestLoader().load()
        self._definitions = {definition.id: definition for definition in loaded}
        self._apply_activation_policy()

    def list(self) -> list[CapabilityView]:
        return [self._build_view(self._definitions[key]) for key in sorted(self._definitions)]

    def get(self, capability_id: str) -> CapabilityView | None:
        definition = self._definitions.get(str(capability_id).strip())
        return self._build_view(definition) if definition else None

    def set_enabled(self, capability_id: str, enabled: bool) -> CapabilityView | None:
        """Persist activation and immediately update Skill/Tool visibility."""
        normalized = str(capability_id or "").strip()
        definition = self._definitions.get(normalized)
        if definition is None:
            return None
        if self._configuration is None:
            raise RuntimeError("能力配置服务尚未初始化")
        self._configuration.set_enabled(normalized, enabled)
        self._apply_activation_policy()
        return self._build_view(definition)

    def bind_dynamic_tool_loader(self, loader: Any | None) -> None:
        """Attach the loader created after capability tools enter the index."""
        self._dynamic_tool_loader = loader
        self._apply_activation_policy()

    def to_list(self, *, include_technical: bool = False) -> list[dict[str, Any]]:
        return [view.to_dict(include_technical=include_technical) for view in self.list()]

    def resolve(self, query: str, *, limit: int = 3) -> list[CapabilityView]:
        """Return capabilities lexically relevant to one task description.

        Skill and Tool retrieval remain embedding based.  This inexpensive
        resolver only decides which user-facing capability facts are useful
        to expose in the current prompt.
        """
        normalized_query = self._normalized_text(query)
        if not normalized_query:
            return []
        query_terms = self._terms(normalized_query)
        ranked: list[tuple[int, str, CapabilityView]] = []
        for definition in self._definitions.values():
            searchable = self._normalized_text(" ".join([
                definition.id,
                definition.name,
                definition.summary,
                definition.category,
                *definition.examples,
                *(outcome.name for outcome in definition.outcomes),
                *(outcome.description for outcome in definition.outcomes),
            ]))
            score = sum(
                3 if term in searchable and len(term) > 2 else 1
                for term in query_terms
                if term in searchable
            )
            if score:
                ranked.append((score, definition.id, self._build_view(definition)))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in ranked[:max(1, limit)]]

    def build_context(self, query: str, *, limit: int = 3) -> str:
        """Build a compact runtime-truth block for the current conversation."""
        views = self.resolve(query, limit=limit)
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

    @staticmethod
    def _terms(value: str) -> set[str]:
        ascii_terms = set(re.findall(r"[a-z0-9][a-z0-9_.+-]{1,}", value))
        chinese_runs = re.findall(r"[\u4e00-\u9fff]+", value)
        chinese_terms = {
            run[index:index + 2]
            for run in chinese_runs
            for index in range(max(0, len(run) - 1))
        }
        return ascii_terms | chinese_terms

    def _build_view(self, definition: CapabilityDefinition) -> CapabilityView:
        enabled = self._is_enabled(definition.id)
        health = {
            component.id: self._component_health(component)
            for component in definition.components
        }

        outcomes: list[CapabilityOutcomeView] = []
        for outcome in definition.outcomes:
            limitations = (("此能力已关闭",) if not enabled else tuple(
                health[component_id].message
                for component_id in outcome.components
                if component_id in health and not health[component_id].available
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

        required_failures = [
            health[component.id]
            for component in definition.components
            if component.required and not health[component.id].available
        ]
        available_count = sum(1 for outcome in outcomes if outcome.available)
        warning_present = any(state.warning for state in health.values())
        if not enabled:
            status = CapabilityStatus.DISABLED
        elif required_failures:
            failure_codes = {state.code for state in required_failures}
            service_configured = any(
                component.kind == "tool_service" and health[component.id].available
                for component in definition.components
            )
            if (
                "configuration_required" in failure_codes
                and failure_codes <= {"configuration_required", "tool_missing"}
            ):
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

        actions = tuple({
            "type": "open_settings",
            "section": component.setup_section,
            "target": component.target,
            "label": f"管理{component.label}" if health[component.id].available else f"配置{component.label}",
        } for component in definition.components if component.setup_section)

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
        )

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

    def _component_health(self, component: CapabilityComponent) -> _ComponentHealth:
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
            names = self._skill_names()
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

    def _skill_names(self) -> set[str]:
        if self._skill_loader is None:
            return set()
        try:
            return set(self._skill_loader.list_names())
        except Exception:
            return set()
