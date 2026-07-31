"""Context shared with tools during one sealed Agent tool invocation.

Most tools finish before ``Tool.execute`` returns.  Long-running tools may
delegate work to a background thread, so they need a durable copy of the
artifact callback that belongs to the original conversation turn.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable, Iterator


ArtifactCallback = Callable[[str, str, dict, str], None]
SpeechCallback = Callable[[Any], str]


@dataclass(frozen=True)
class ToolExecutionContext:
    """Immutable metadata for the tool call currently being executed."""

    tool_call_id: str
    tool_name: str
    arguments: dict
    artifact_callback: ArtifactCallback | None = None
    speech_callback: SpeechCallback | None = None
    session_id: str = ""
    attachments: tuple[dict[str, Any], ...] = ()
    workspace_root: str = ""
    working_directory: str = ""
    output_root: str = ""

    def publish_artifacts(self, result: str) -> None:
        """Run the original turn's artifact projection, if one was installed."""
        if self.artifact_callback is not None:
            self.artifact_callback(
                self.tool_call_id,
                self.tool_name,
                dict(self.arguments),
                result,
            )

    def publish_speech(self, audio: Any) -> str | None:
        """Route one speech expression through the original conversation Turn."""
        if self.speech_callback is None:
            return None
        return self.speech_callback(audio)


_current_context: ContextVar[ToolExecutionContext | None] = ContextVar(
    "xiaomei_tool_execution_context",
    default=None,
)


def current_tool_execution() -> ToolExecutionContext | None:
    """Return the active tool call context in the current execution context."""
    return _current_context.get()


@contextmanager
def bind_tool_execution(
    *,
    tool_call_id: str,
    tool_name: str,
    arguments: dict,
    artifact_callback: ArtifactCallback | None,
    speech_callback: SpeechCallback | None = None,
    session_id: str = "",
    attachments: tuple[dict[str, Any], ...] = (),
    workspace_root: str = "",
    working_directory: str = "",
    output_root: str = "",
) -> Iterator[ToolExecutionContext]:
    """Expose one tool call's immutable context while its function starts."""
    context = ToolExecutionContext(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=dict(arguments),
        artifact_callback=artifact_callback,
        speech_callback=speech_callback,
        session_id=session_id,
        attachments=tuple(dict(item) for item in attachments),
        workspace_root=workspace_root,
        working_directory=working_directory,
        output_root=output_root,
    )
    token = _current_context.set(context)
    try:
        yield context
    finally:
        _current_context.reset(token)
