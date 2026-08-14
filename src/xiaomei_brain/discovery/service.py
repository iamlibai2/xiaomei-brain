"""One discovery entrance over the existing capability, Skill and Tool indexes."""

from __future__ import annotations

from typing import Any


ACTIVE_CAPABILITY_EXPANSION_MIN_SCORE = 0.65
ACTIVE_TOOL_DISCOVERY_LIMIT = 3


class DiscoveryService:
    """Coordinate discovery without merging resource lifecycles or indexes."""

    def __init__(
        self,
        *,
        capability_registry: Any,
        skill_loader: Any,
        dynamic_tool_loader: Any,
        tool_registry: Any,
    ) -> None:
        self._capabilities = capability_registry
        self._skills = skill_loader
        self._tools = dynamic_tool_loader
        self._tool_registry = tool_registry
        self._last_discovery: dict[str, Any] | None = None

    def begin_run(self) -> None:
        """Clear turn-local discovery evidence before a new ReAct run."""
        self._last_discovery = None

    def prefetch(self, query: str, *, person_id: str = "") -> dict[str, Any]:
        """Return compact semantic candidates; never activate capability dependencies."""
        capability_candidates = self._capabilities.discover(
            query,
            limit=max(2, len(getattr(self._capabilities, "_definitions", {}))),
            person_id=person_id,
            min_score=0.50,
        )
        capabilities = [
            item for item in capability_candidates
            if item["view"].status.value in {"ready", "degraded"}
        ][:2]
        context_renderer = getattr(self._capabilities, "render_context", None)
        capability_context = (
            context_renderer([
                item["view"] for item in capability_candidates[:3]
            ])
            if callable(context_renderer)
            else ""
        )
        return {
            "capabilities": [self._capability_summary(item) for item in capabilities],
            "context": capability_context,
            # SkillLoader already builds the prompt and exact selection in one
            # vector query. render_execution_context fills this list from that
            # result rather than issuing the same search twice.
            "skills": [],
        }

    def discover(
        self,
        query: str,
        *,
        limit: int = 5,
        person_id: str = "",
    ) -> dict[str, Any]:
        """Actively discover and activate resources needed for one task."""
        bounded = max(1, min(int(limit or 5), 8))
        capability_matches = self._capabilities.discover(
            query,
            limit=min(2, bounded),
            person_id=person_id,
            min_score=0.50,
        )
        nearby_capabilities = []
        if not capability_matches:
            nearby_capabilities = self._capabilities.discover(
                query,
                limit=min(2, bounded),
                person_id=person_id,
                min_score=None,
            )
        skill_candidates = self._skills.list_skills(
            query=query,
            top_k=min(3, bounded),
        )
        reliable_skills = [
            item for item in skill_candidates
            if item.get("_distance") is None or float(item.get("_distance")) <= 0.82
        ]
        tool_result = self._tools.search_and_activate(
            query,
            limit=min(ACTIVE_TOOL_DISCOVERY_LIMIT, bounded),
        )

        # Explicit discovery may expand the concrete outcome of a matching
        # capability. Unlike prefetch, this is a model-requested action.
        strongest_capability = capability_matches[0] if capability_matches else None
        expand_capability = (
            strongest_capability is not None
            and float(strongest_capability.get("score") or 0.0)
            >= ACTIVE_CAPABILITY_EXPANSION_MIN_SCORE
        )
        capability_tools: list[str] = []
        capability_skills: list[str] = []
        if expand_capability:
            capability_tools, capability_skills = self._capabilities.select_execution_components(
                query,
                # Active discovery expands only the strongest high-confidence
                # Capability outcome. Weaker matches remain visible candidates.
                limit=1,
                person_id=person_id,
            )
        activated_capability_tools, missing = self._tools.activate_required_tools(
            capability_tools,
        )

        skill_matches = list(reliable_skills)
        skill_names = [str(item.get("name") or "") for item in skill_matches if item.get("name")]
        for name in capability_skills:
            if name not in skill_names:
                skill = self._skills.view_skill(name)
                if skill:
                    skill_matches.append(skill)
                    skill_names.append(name)

        loaded_skill: dict[str, Any] | None = None
        if len(skill_names) == 1:
            skill_tool = self._tool_registry.get("skill_view")
            if skill_tool is not None:
                loaded_skill = {
                    "name": skill_names[0],
                    "content": skill_tool.execute(name=skill_names[0]),
                }

        activated_tools = list(tool_result.get("activated", []))
        activated_names = {str(item.get("name") or "") for item in activated_tools}
        for name in activated_capability_tools:
            if name in activated_names:
                continue
            tool = self._tool_registry.get(name)
            if tool is not None:
                activated_tools.append({
                    "name": tool.name,
                    "category": tool.category,
                    "description": tool.description[:300],
                    "source": "capability",
                })

        result = {
            "query": str(query),
            "capabilities": [self._capability_summary(item) for item in capability_matches],
            "nearby_capabilities": [
                self._capability_summary(item) for item in nearby_capabilities
            ],
            "skills": [self._skill_summary(item) for item in skill_matches],
            "nearby_skills": [
                self._skill_summary(item)
                for item in skill_candidates
                if item not in reliable_skills
            ],
            "loaded_skill": loaded_skill,
            "activated_tools": activated_tools,
            "missing_tools": list(dict.fromkeys([*tool_result.get("missing", []), *missing])),
            "instruction": (
                "Activated tool schemas are available in the next reasoning step. "
                "A loaded Skill is ready to follow now. If several Skill candidates remain, "
                "use skill_view(name) for the one that best matches the task."
            ),
        }
        self._last_discovery = result
        return result

    @property
    def last_discovery(self) -> dict[str, Any] | None:
        return self._last_discovery

    @staticmethod
    def _capability_summary(match: dict[str, Any]) -> dict[str, Any]:
        view = match["view"]
        outcome_id = str(match.get("outcome_id") or "")
        outcome = next((item for item in view.outcomes if item.id == outcome_id), None)
        return {
            "id": view.id,
            "name": view.name,
            "status": view.status.value,
            "outcome_id": outcome_id,
            "outcome": outcome.name if outcome else "",
            "description": outcome.description if outcome else view.summary,
            "score": match.get("score"),
        }

    @staticmethod
    def _skill_summary(skill: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": str(skill.get("name") or ""),
            "description": str(skill.get("description") or "")[:300],
            "tags": list(skill.get("tags") or []),
            "tool_bindings": list(skill.get("tool_bindings") or []),
            "distance": skill.get("_distance"),
        }
