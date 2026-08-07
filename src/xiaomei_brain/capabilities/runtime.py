"""Generic contracts for capability-owned external runtimes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, TypeVar


@dataclass(frozen=True)
class CapabilityRuntimeState:
    """Truthful, Person-scoped availability reported by a runtime."""

    available: bool
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    actions: tuple[str, ...] = ()


class CapabilityRuntime(Protocol):
    """Runtime contract consumed by capability RPC and availability checks."""

    capability_id: str

    def inspect(self, person_id: str = "") -> CapabilityRuntimeState: ...

    def start(
        self,
        action: str,
        person_id: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def job_status(
        self,
        person_id: str,
        job_id: str = "",
    ) -> dict[str, Any] | None: ...

    def cancel(
        self,
        person_id: str,
        job_id: str = "",
    ) -> dict[str, Any] | None: ...

    def complete(
        self,
        person_id: str,
        job_id: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any] | None: ...


RuntimeT = TypeVar("RuntimeT", bound=CapabilityRuntime)


class DeferredCapabilityRuntime(Generic[RuntimeT]):
    """Resolve tools against a Runtime created after Agent dependencies exist."""

    def __init__(self, display_name: str) -> None:
        self.display_name = display_name
        self._runtime: RuntimeT | None = None

    def bind(self, runtime: RuntimeT) -> None:
        self._runtime = runtime

    def __getattr__(self, name: str) -> Any:
        if self._runtime is None:
            raise RuntimeError(f"{self.display_name}运行组件尚未完成初始化")
        return getattr(self._runtime, name)


class UnavailableCapabilityRuntime:
    """Non-crashing runtime used when one capability cannot be assembled."""

    def __init__(self, capability_id: str, reason: str) -> None:
        self.capability_id = capability_id
        self.reason = reason

    def inspect(self, person_id: str = "") -> CapabilityRuntimeState:
        return CapabilityRuntimeState(
            available=False,
            code="component_error",
            message=f"运行组件加载失败：{self.reason}",
        )

    def start(
        self,
        action: str,
        person_id: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise RuntimeError(self.reason)

    def job_status(self, person_id: str, job_id: str = "") -> None:
        return None

    def cancel(self, person_id: str, job_id: str = "") -> None:
        return None

    def complete(
        self,
        person_id: str,
        job_id: str,
        parameters: dict[str, Any],
    ) -> None:
        return None
