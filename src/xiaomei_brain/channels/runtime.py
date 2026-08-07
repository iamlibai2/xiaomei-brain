"""Hot-apply external channels without restarting the Agent."""

from __future__ import annotations

from typing import Any


class ChannelRuntimeService:
    def __init__(self, living: Any) -> None:
        self.living = living

    def apply(self, channel: str, config: dict[str, Any]):
        registry = getattr(self.living, "_registry", None)
        factory = registry.get_channel_factory(channel) if registry is not None else None
        if not callable(factory):
            raise ValueError(f"Channel '{channel}' does not support runtime configuration")
        adapter = factory(config)
        gateway = self.living._gateway_inbound
        gateway.replace_channel(channel, adapter)
        self.living._router.register_adapter(channel, adapter)
        if registry is not None:
            registry.register_channel(channel, adapter)
        return adapter

    def remove(self, channel: str) -> bool:
        gateway = self.living._gateway_inbound
        return gateway.remove_channel(channel)

    def status(self, channel: str) -> dict[str, Any]:
        gateway = self.living._gateway_inbound
        adapter = gateway.get_channel(channel)
        if adapter is None:
            return {"state": "stopped", "error": ""}
        status = getattr(adapter, "status", None)
        return status() if callable(status) else {"state": "running", "error": ""}
