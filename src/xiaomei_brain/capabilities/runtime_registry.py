"""Load capability runtimes declared by capability manifests."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from .runtime import CapabilityRuntime, UnavailableCapabilityRuntime


CapabilityRuntimeFactory = Callable[..., CapabilityRuntime]


class CapabilityRuntimeRegistry:
    """Resolve runtime factories without leaking concrete capabilities into Core."""

    def __init__(self) -> None:
        self._factories: dict[str, CapabilityRuntimeFactory] = {}
        self._load_errors: dict[str, str] = {}

    def register(
        self,
        capability_id: str,
        factory: CapabilityRuntimeFactory,
    ) -> None:
        normalized = str(capability_id).strip()
        if not normalized:
            raise ValueError("Capability runtime must define capability_id")
        if normalized in self._factories:
            raise ValueError(f"Duplicate capability runtime: {normalized}")
        self._factories[normalized] = factory

    def register_factories(
        self,
        factories: dict[str, CapabilityRuntimeFactory] | Iterable[
            tuple[str, CapabilityRuntimeFactory]
        ],
    ) -> None:
        """Register factories already discovered by the Plugin system."""
        entries = factories.items() if isinstance(factories, dict) else factories
        for capability_id, factory in entries:
            try:
                self.register(capability_id, factory)
            except Exception as exc:
                self._load_errors[str(capability_id).strip()] = str(exc)

    def create_all(self, **dependencies: Any) -> dict[str, CapabilityRuntime]:
        runtimes: dict[str, CapabilityRuntime] = {
            capability_id: UnavailableCapabilityRuntime(capability_id, reason)
            for capability_id, reason in self._load_errors.items()
        }
        for capability_id, factory in self._factories.items():
            try:
                runtime = factory(capability_id=capability_id, **dependencies)
            except Exception as exc:
                runtimes[capability_id] = UnavailableCapabilityRuntime(
                    capability_id,
                    str(exc),
                )
                continue
            runtime_id = str(getattr(runtime, "capability_id", "")).strip()
            if runtime_id != capability_id:
                runtimes[capability_id] = UnavailableCapabilityRuntime(
                    capability_id,
                    f"runtime returned mismatched id '{runtime_id or '<empty>'}'",
                )
                continue
            runtimes[capability_id] = runtime
        return runtimes
