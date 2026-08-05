"""User-facing composer invocation catalog."""

from __future__ import annotations

from typing import Any

from xiaomei_brain.agent.invocations import EXECUTION_MODES, process_matches_capability

from ..protocol import ErrorCode, build_error, build_response


class InvocationMethods:
    """Expose only choices meaningful in the conversation composer."""

    def __init__(self, living: Any) -> None:
        self._living = living

    @property
    def handlers(self) -> dict[str, Any]:
        return {"interaction.catalog": self.handle_catalog}

    def handle_catalog(self, _conn_id: str, req_id: str, _params: dict) -> dict:
        instance = getattr(self._living, "agent", None)
        if instance is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "Agent 尚未就绪")

        capabilities = []
        for capability in instance.list_capabilities():
            if not capability.get("enabled"):
                continue
            if capability.get("status") not in {"ready", "degraded"}:
                continue
            capabilities.append({
                "id": capability.get("id", ""),
                "name": capability.get("name", ""),
                "description": capability.get("summary", ""),
                "kind": "capability",
                "status": capability.get("status", ""),
                "processes": [],
            })

        template_registry = getattr(instance, "_process_template_registry", None)
        templates = template_registry.list() if template_registry is not None else []
        for capability in capabilities:
            capability["processes"] = [
                template.public_dict()
                for template in templates
                if process_matches_capability(template, str(capability["id"]))
            ]

        loader = getattr(instance, "_skill_loader", None)
        skills = []
        if loader is not None:
            refresh = getattr(loader, "refresh_if_changed", None)
            if callable(refresh):
                refresh()
            skills = [
                {
                    "id": str(item.get("name", "")),
                    "name": str(item.get("name", "")),
                    "description": str(item.get("description", "")),
                    "kind": "skill",
                    "tags": list(item.get("tags") or []),
                }
                for item in loader.list_skills(query="", top_k=200)
                if str(item.get("name", "")).strip()
            ]

        return build_response(req_id, result={
            "capabilities": capabilities,
            "skills": skills,
            "execution_modes": [
                {**dict(item), "kind": "execution"} for item in EXECUTION_MODES
            ],
        })
