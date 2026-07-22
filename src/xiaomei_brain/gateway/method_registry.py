"""Registry for Gateway RPC methods and their access metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping


MethodHandler = Callable[[str, str, dict], dict]


@dataclass(frozen=True)
class RegisteredMethod:
    name: str
    handler: MethodHandler
    requires_auth: bool = True


class MethodRegistry:
    """Own the public RPC catalog independently from method implementations."""

    def __init__(self) -> None:
        self._methods: dict[str, RegisteredMethod] = {}

    def register(
        self,
        name: str,
        handler: MethodHandler,
        *,
        requires_auth: bool = True,
    ) -> None:
        if not name or not callable(handler):
            raise ValueError("Gateway method requires a name and callable handler")
        if name in self._methods:
            raise ValueError(f"Gateway method already registered: {name}")
        self._methods[name] = RegisteredMethod(name, handler, requires_auth)

    def register_many(
        self,
        handlers: Mapping[str, MethodHandler],
        *,
        requires_auth: bool = True,
    ) -> None:
        for name, handler in handlers.items():
            self.register(name, handler, requires_auth=requires_auth)

    def resolve(self, name: str) -> RegisteredMethod | None:
        return self._methods.get(name)

    @property
    def handlers(self) -> dict[str, MethodHandler]:
        """Compatibility/read-only snapshot of the callable method catalog."""
        return {name: method.handler for name, method in self._methods.items()}

    def names(self) -> tuple[str, ...]:
        return tuple(self._methods)
