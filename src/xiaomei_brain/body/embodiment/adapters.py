"""Runtime adapters from the existing Body and Channel mechanisms."""

from __future__ import annotations

from typing import Any, Protocol

from .models import (
    Embodiment,
    EmbodimentKind,
    EmbodimentStatus,
    OrganCapability,
)


class EmbodimentRuntime(Protocol):
    @property
    def embodiment(self) -> Embodiment: ...

    def status(self) -> EmbodimentStatus: ...

    def speak(self, audio: Any, target: str = "") -> bool: ...


class LocalBodyEmbodiment:
    """Expose the existing singleton physical Body as one Embodiment."""

    def __init__(
        self,
        body: Any,
        *,
        body_id: str = "local-host",
        label: str = "本机身体",
        allow_proactive_use: bool = False,
    ) -> None:
        self._body = body
        capabilities: set[OrganCapability] = set()
        if getattr(body, "ears", None) is not None:
            capabilities.add(OrganCapability.HEARING)
        if getattr(body, "throat", None) is not None:
            capabilities.add(OrganCapability.SPEECH)
        if getattr(body, "eyes", None) is not None:
            capabilities.add(OrganCapability.VISION)
        self._embodiment = Embodiment(
            body_id=body_id,
            label=label,
            kind=EmbodimentKind.LOCAL,
            capabilities=frozenset(capabilities),
            allow_proactive_use=allow_proactive_use,
        )

    @property
    def embodiment(self) -> Embodiment:
        return self._embodiment

    def status(self) -> EmbodimentStatus:
        online = self._body is not None
        return EmbodimentStatus(
            embodiment=self._embodiment,
            online=online,
            state="online" if online else "offline",
        )

    def speak(self, audio: Any, target: str = "") -> bool:
        throat = getattr(self._body, "throat", None)
        if throat is None:
            return False
        throat.play_stream(
            audio.chunks,
            codec=audio.codec,
            sample_rate=audio.sample_rate,
            channels=audio.channels,
            initial_buffer_ms=audio.initial_buffer_ms,
        )
        return True


class ChannelEmbodiment:
    """Expose body-like powers while retaining the existing ChannelAdapter."""

    _ONLINE_STATES = {"online", "connected", "running"}

    def __init__(self, channel_type: str, adapter: Any) -> None:
        capabilities: set[OrganCapability] = set()
        channel_capabilities = adapter.capabilities
        if getattr(channel_capabilities, "audio_input", False):
            capabilities.add(OrganCapability.HEARING)
        if getattr(channel_capabilities, "audio_output", False):
            capabilities.add(OrganCapability.SPEECH)
        body_id = str(
            getattr(adapter, "embodiment_id", "")
            or f"{channel_type}:default"
        )
        label = str(
            getattr(adapter, "embodiment_label", "")
            or channel_type
        )
        self._adapter = adapter
        self._embodiment = Embodiment(
            body_id=body_id,
            label=label,
            kind=EmbodimentKind.REMOTE,
            capabilities=frozenset(capabilities),
            allow_proactive_use=bool(
                getattr(adapter, "allow_proactive_embodiment_use", False),
            ),
            channel_type=channel_type,
        )

    @property
    def embodiment(self) -> Embodiment:
        return self._embodiment

    def status(self) -> EmbodimentStatus:
        state = "online"
        error = ""
        online = True
        status_getter = getattr(self._adapter, "status", None)
        if callable(status_getter):
            try:
                raw = status_getter() or {}
                if isinstance(raw, dict):
                    state = str(raw.get("state", "online") or "online")
                    error = str(raw.get("error", "") or "")
                    online = state.lower() in self._ONLINE_STATES
            except Exception as exc:
                state = "error"
                error = str(exc)
                online = False
        return EmbodimentStatus(
            embodiment=self._embodiment,
            online=online,
            state=state,
            error=error,
        )

    def speak(self, audio: Any, target: str = "") -> bool:
        if not target or not self._embodiment.supports(OrganCapability.SPEECH):
            return False
        return bool(self._adapter.send_audio(target, audio))

    def embodiment_for_target(self, target: str) -> Embodiment | None:
        resolver = getattr(self._adapter, "embodiment_for_target", None)
        if not callable(resolver):
            return self._embodiment
        return resolver(target)

    def statuses(self) -> list[EmbodimentStatus]:
        getter = getattr(self._adapter, "embodiment_statuses", None)
        if callable(getter):
            return list(getter())
        return [self.status()]
