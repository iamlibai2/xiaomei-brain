"""Extensible policies evaluated before an Agent ReAct run may finish."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class CompletionGuardResult:
    """Explain why a normal final response must not end the current run."""

    key: str
    reason: str
    failure_message: str
    max_retries: int = 2


CompletionGuard = Callable[[Any, str], CompletionGuardResult | None]

