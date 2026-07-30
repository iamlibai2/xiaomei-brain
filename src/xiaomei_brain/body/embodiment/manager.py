"""Per-Agent runtime registry and body selection policy."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from .adapters import (
    ChannelEmbodiment,
    EmbodimentRuntime,
    LocalBodyEmbodiment,
)
from .models import Embodiment, EmbodimentStatus, OrganCapability


@dataclass(frozen=True)
class EmbodimentResolution:
    """One selected body and the channel target it should act upon."""

    runtime: EmbodimentRuntime
    target: str = ""
    selected_embodiment: Embodiment | None = None

    @property
    def embodiment(self) -> Embodiment:
        return self.selected_embodiment or self.runtime.embodiment


class EmbodimentManager:
    """Manage bodies belonging to one Agent process without replacing Channels."""

    def __init__(self, router: Any) -> None:
        self._router = router
        self._runtimes: dict[str, EmbodimentRuntime] = {}
        self._channel_bodies: dict[str, str] = {}
        self._local_body_id = ""
        self._lock = threading.RLock()

    def register_local(
        self,
        body: Any,
        *,
        body_id: str = "local-host",
        allow_proactive_use: bool = False,
    ) -> Embodiment:
        runtime = LocalBodyEmbodiment(
            body,
            body_id=body_id,
            allow_proactive_use=allow_proactive_use,
        )
        self._register(runtime)
        with self._lock:
            self._local_body_id = runtime.embodiment.body_id
        return runtime.embodiment

    def register_channel(
        self,
        channel_type: str,
        adapter: Any,
    ) -> Embodiment | None:
        if not bool(getattr(adapter, "exposes_embodiment", False)):
            return None
        runtime = ChannelEmbodiment(channel_type, adapter)
        self._register(runtime)
        with self._lock:
            self._channel_bodies[channel_type] = runtime.embodiment.body_id
        return runtime.embodiment

    def unregister(self, body_id: str) -> None:
        with self._lock:
            self._runtimes.pop(body_id, None)
            self._channel_bodies = {
                channel: registered_id
                for channel, registered_id in self._channel_bodies.items()
                if registered_id != body_id
            }
            if self._local_body_id == body_id:
                self._local_body_id = ""

    def clear(self) -> None:
        with self._lock:
            self._runtimes.clear()
            self._channel_bodies.clear()
            self._local_body_id = ""

    def list(self) -> list[EmbodimentStatus]:
        with self._lock:
            runtimes = list(self._runtimes.values())
        statuses: list[EmbodimentStatus] = []
        for runtime in runtimes:
            getter = getattr(runtime, "statuses", None)
            if callable(getter):
                statuses.extend(getter())
            else:
                statuses.append(runtime.status())
        return statuses

    def get(self, body_id: str) -> EmbodimentStatus | None:
        with self._lock:
            runtime = self._runtimes.get(body_id)
        return runtime.status() if runtime is not None else None

    def resolve_for_turn(
        self,
        turn_id: str,
        session_id: str,
        capability: OrganCapability,
    ) -> EmbodimentResolution | None:
        route = self._router.route_for_turn(turn_id, session_id)
        if route is not None:
            with self._lock:
                remote_id = self._channel_bodies.get(route.type)
                runtime = self._runtimes.get(remote_id or "")
            if runtime is not None:
                target_embodiment = runtime.embodiment
                resolver = getattr(runtime, "embodiment_for_target", None)
                if callable(resolver):
                    target_embodiment = resolver(route.target)
                    if target_embodiment is None:
                        return None
                if target_embodiment.supports(capability):
                    return EmbodimentResolution(
                        runtime,
                        route.target,
                        target_embodiment,
                    )
                # A known remote body must not silently act through the
                # server's physical body when it lacks the requested organ.
                return None

        # A route-less internal/CLI Turn may still use the Agent host body.
        with self._lock:
            local = self._runtimes.get(self._local_body_id)
        if local is not None and local.embodiment.supports(capability):
            return EmbodimentResolution(local)
        return None

    def speak(self, resolution: EmbodimentResolution, audio: Any) -> bool:
        status = resolution.runtime.status()
        if not status.online:
            return False
        return resolution.runtime.speak(audio, resolution.target)

    def _register(self, runtime: EmbodimentRuntime) -> None:
        body_id = runtime.embodiment.body_id.strip()
        if not body_id:
            raise ValueError("Embodiment body_id 不能为空")
        with self._lock:
            if body_id in self._runtimes:
                raise ValueError(f"Embodiment 已注册：{body_id}")
            self._runtimes[body_id] = runtime
