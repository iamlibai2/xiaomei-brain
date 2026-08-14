"""Context shared with tools during one sealed Agent tool invocation.

Most tools finish before ``Tool.execute`` returns.  Long-running tools may
delegate work to a background thread, so they need a durable copy of the
artifact callback that belongs to the original conversation turn.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from xiaomei_brain.projects.models import ProjectRuntimeContext


ArtifactCallback = Callable[[str, str, dict, str], Any]
SpeechCallback = Callable[[Any], str]
WorkspaceAssetResolver = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ToolExecutionContext:
    """Immutable metadata for the tool call currently being executed."""

    tool_call_id: str
    tool_name: str
    arguments: dict
    artifact_callback: ArtifactCallback | None = None
    speech_callback: SpeechCallback | None = None
    session_id: str = ""
    turn_id: str = ""
    person_id: str = ""
    attachments: tuple[dict[str, Any], ...] = ()
    workspace_root: str = ""
    working_directory: str = ""
    output_root: str = ""
    writable_roots: tuple[str, ...] = ()
    read_only_roots: tuple[str, ...] = ()
    execution_environment: Any = None
    tool_registry: Any = None
    project_context: ProjectRuntimeContext | None = None
    project_service: Any = None
    workspace_service: Any = None
    workspace_asset_resolver: WorkspaceAssetResolver | None = None
    cancel_check: Callable[[], bool] | None = None

    def publish_artifacts(self, result: str) -> Any:
        """Run the original turn's artifact projection, if one was installed."""
        if self.artifact_callback is not None:
            return self.artifact_callback(
                self.tool_call_id,
                self.tool_name,
                dict(self.arguments),
                result,
            )
        return None

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


def resolve_current_attachment(
    reference: str = "",
    *,
    allowed_suffixes: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Resolve an attachment without granting access beyond the current Turn.

    Models do not reliably echo opaque attachment IDs.  Accept an exact ID or
    filename and, when only one compatible attachment exists, select it
    automatically.  The candidate set is always the sealed tool-execution
    context, never conversation history or an arbitrary filesystem path.
    """
    context = current_tool_execution()
    if context is None:
        raise ValueError("Attachment access is only available during an Agent tool call")
    suffixes = {str(item).casefold() for item in allowed_suffixes if str(item)}

    def compatible(item: dict[str, Any]) -> bool:
        if not suffixes:
            return True
        name = str(item.get("name") or item.get("local_path") or "")
        return Path(name).suffix.casefold() in suffixes

    candidates = [item for item in context.attachments if compatible(item)]
    normalized = str(reference or "").strip().casefold()
    if normalized:
        for item in candidates:
            identities = {
                str(item.get("id") or "").strip().casefold(),
                str(item.get("name") or "").strip().casefold(),
                Path(str(item.get("local_path") or "")).name.casefold(),
            }
            if normalized in identities:
                return item
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError("No compatible attachment is available in the current Turn")
    raise ValueError(
        "Multiple compatible attachments are available; use the attachment ID or filename"
    )


def resolve_current_workspace_asset(
    asset_id: str,
    *,
    workspace_id: str = "",
    writable: bool = False,
    allowed_suffixes: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Resolve a Person-visible Asset without exposing arbitrary host paths."""
    context = current_tool_execution()
    if context is None or context.workspace_asset_resolver is None:
        raise ValueError("Workspace Asset access is unavailable in this tool call")
    item = context.workspace_asset_resolver(
        asset_id,
        person_id=context.person_id,
        session_id=context.session_id,
        workspace_id=workspace_id,
        writable=writable,
    )
    path = Path(str(item.get("local_path") or ""))
    suffixes = {str(value).casefold() for value in allowed_suffixes if str(value)}
    if suffixes and path.suffix.casefold() not in suffixes:
        raise ValueError(
            f"Workspace Asset format {path.suffix or '(none)'} is not supported here"
        )
    return item


@contextmanager
def bind_tool_execution(
    *,
    tool_call_id: str,
    tool_name: str,
    arguments: dict,
    artifact_callback: ArtifactCallback | None,
    speech_callback: SpeechCallback | None = None,
    session_id: str = "",
    turn_id: str = "",
    person_id: str = "",
    attachments: tuple[dict[str, Any], ...] = (),
    workspace_root: str = "",
    working_directory: str = "",
    output_root: str = "",
    writable_roots: tuple[str, ...] = (),
    read_only_roots: tuple[str, ...] = (),
    execution_environment: Any = None,
    tool_registry: Any = None,
    project_context: ProjectRuntimeContext | None = None,
    project_service: Any = None,
    workspace_service: Any = None,
    workspace_asset_resolver: WorkspaceAssetResolver | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> Iterator[ToolExecutionContext]:
    """Expose one tool call's immutable context while its function starts."""
    context = ToolExecutionContext(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=dict(arguments),
        artifact_callback=artifact_callback,
        speech_callback=speech_callback,
        session_id=session_id,
        turn_id=turn_id,
        person_id=person_id,
        attachments=tuple(dict(item) for item in attachments),
        workspace_root=workspace_root,
        working_directory=working_directory,
        output_root=output_root,
        writable_roots=tuple(
            str(item) for item in (writable_roots or ()) if str(item)
        ),
        read_only_roots=tuple(
            str(item) for item in (read_only_roots or ()) if str(item)
        ),
        execution_environment=execution_environment,
        tool_registry=tool_registry,
        project_context=project_context,
        project_service=project_service,
        workspace_service=workspace_service,
        workspace_asset_resolver=workspace_asset_resolver,
        cancel_check=cancel_check,
    )
    token = _current_context.set(context)
    try:
        yield context
    finally:
        _current_context.reset(token)
