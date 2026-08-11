"""Safe cross-platform file and search tools."""

from __future__ import annotations

import difflib
import glob as glob_module
import logging
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any, Iterator

from xiaomei_brain.execution.workspace import WorkspaceBroker, protected_host_roots

from ..base import Tool
from ..execution_context import current_tool_execution

logger = logging.getLogger(__name__)

MAX_READ_LINES = 2000
MAX_READ_CHARS = 100_000
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_SEARCH_FILES = 10_000
_output_base: str | None = None
_PROTECTED_ROOTS = protected_host_roots()


def set_output_base(base_dir: str) -> None:
    """Set the fallback Agent data directory for calls outside Agent Core."""
    global _output_base
    _output_base = base_dir


def get_workspace_dir() -> str:
    context = current_tool_execution()
    if context and context.workspace_root:
        return str(Path(context.workspace_root).expanduser().resolve())
    if _output_base:
        return str((Path(_output_base) / "workspace").resolve())
    configured = os.environ.get(
        "XIAOMEI_OUTPUT_DIR",
        os.path.expanduser("~/.xiaomei-brain/global/workspace"),
    )
    return str(Path(configured).resolve())


def get_working_directory() -> str:
    context = current_tool_execution()
    if context and context.working_directory:
        return str(Path(context.working_directory).expanduser().resolve())
    return get_workspace_dir()


def _read_only_roots() -> list[Path]:
    context = current_tool_execution()
    if context is None:
        return []
    return list(dict.fromkeys(
        Path(item).expanduser().resolve()
        for item in context.read_only_roots
        if str(item).strip()
    ))


def _writable_roots() -> list[Path]:
    context = current_tool_execution()
    if context is None:
        return []
    return list(dict.fromkeys(
        Path(item).expanduser().resolve()
        for item in context.writable_roots
        if str(item).strip()
    ))


def _allowed_roots() -> list[Path]:
    roots = [Path(get_workspace_dir()).resolve()]
    context = current_tool_execution()
    if context and context.output_root:
        roots.append(Path(context.output_root).expanduser().resolve())
    roots.extend(_writable_roots())
    for item in os.environ.get("XIAOMEI_ALLOWED_PATHS", "").split(os.pathsep):
        if item.strip():
            roots.append(Path(item.strip()).expanduser().resolve())
    return list(dict.fromkeys(roots))


def _is_within(path: Path, root: Path) -> bool:
    try:
        Path(os.path.normcase(str(path))).relative_to(
            Path(os.path.normcase(str(root))),
        )
        return True
    except ValueError:
        return False


def _expand_virtual_root(path: str) -> str:
    candidate = Path(path).expanduser()
    if candidate.is_absolute() or not candidate.parts:
        return path
    first = candidate.parts[0].lower()
    workspace_root = Path(get_workspace_dir()).resolve()
    if first == workspace_root.name.lower():
        # The model may call the visible root "workspace/" even though every
        # file tool already starts inside that directory. Treat the prefix as
        # a virtual root instead of creating workspace/workspace/ by accident.
        return str(workspace_root.joinpath(*candidate.parts[1:]))
    for root in (*_writable_roots(), *_read_only_roots()):
        if first == root.name.lower():
            return str(root.joinpath(*candidate.parts[1:]))
    return path


def _resolve(
    path: str,
    *,
    exists: bool = False,
    for_write: bool = False,
) -> tuple[Path | None, str]:
    workspace_root = get_workspace_dir()
    path = _expand_virtual_root(path)
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path(get_working_directory()) / candidate
    try:
        resolved_candidate = candidate.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        return None, f"Error: cannot resolve path: {exc}"
    read_only_roots = _read_only_roots()
    if for_write and any(
        _is_within(resolved_candidate, root) for root in read_only_roots
    ):
        return None, "Error: Agent attachment archives are read-only."
    allowed_roots = [*_allowed_roots(), *([] if for_write else read_only_roots)]
    broker = WorkspaceBroker.create(
        workspace_root=workspace_root,
        working_directory=get_working_directory(),
        extra_allowed_roots=allowed_roots[1:],
        protected_roots=_PROTECTED_ROOTS,
    )
    return broker.resolve(path, exists=exists)


def resolve_readable_path(path: str, *, exists: bool = True) -> tuple[Path | None, str]:
    """Resolve a model-supplied path inside writable or read-only Agent roots."""
    return _resolve(path, exists=exists)


def resolve_writable_directory(path: str) -> tuple[Path | None, str]:
    """Resolve a shell working directory inside a writable Agent root."""
    resolved, error = _resolve(path, exists=True, for_write=True)
    if error:
        return None, error
    assert resolved is not None
    if not resolved.is_dir():
        return None, f"Error: not a directory: {path}"
    return resolved, ""


def _display(path: Path) -> str:
    resolved = path.resolve()
    for root in (*_writable_roots(), *_read_only_roots()):
        if _is_within(resolved, root):
            relative = resolved.relative_to(root)
            return (Path(root.name) / relative).as_posix()
    try:
        return resolved.relative_to(
            Path(get_working_directory()).resolve(),
        ).as_posix()
    except ValueError:
        return str(resolved)


def _binary(data: bytes) -> bool:
    if not data:
        return False
    if b"\x00" in data:
        return True
    sample = data[:4096]
    controls = sum(byte < 9 or 13 < byte < 32 for byte in sample)
    return controls / len(sample) > 0.1


def read(path: str, offset: int = 1, limit: int = 500) -> dict[str, Any]:
    resolved, error = _resolve(path, exists=True)
    if error:
        return {"error": error}
    assert resolved is not None
    if not resolved.is_file():
        return {"error": f"Error: not a file: {path}"}
    try:
        raw = resolved.read_bytes()
    except OSError as exc:
        return {"error": f"Error: {exc}"}
    if _binary(raw):
        return {"error": f"Error: binary file cannot be read as text: {path}"}
    lines = raw.decode("utf-8-sig", errors="replace").splitlines()
    offset = max(1, int(offset or 1))
    limit = min(MAX_READ_LINES, max(1, int(limit or 500)))
    selected = lines[offset - 1:offset - 1 + limit]
    content = "\n".join(
        f"{number:>6}|{line}"
        for number, line in enumerate(selected, start=offset)
    )
    if len(content) > MAX_READ_CHARS:
        return {"error": "Error: selected range is too large; use a smaller limit"}
    end = offset + len(selected) - 1
    return {
        "path": _display(resolved),
        "content": content,
        "total_lines": len(lines),
        "file_size": len(raw),
        "offset": offset,
        "truncated": end < len(lines),
        "next_offset": end + 1 if end < len(lines) else None,
    }


def _text_format(path: Path) -> tuple[bool, str]:
    try:
        sample = path.read_bytes()[:65536]
    except OSError:
        return False, "\n"
    bom = sample.startswith(b"\xef\xbb\xbf")
    crlf = sample.count(b"\r\n")
    lf = sample.count(b"\n") - crlf
    return bom, "\r\n" if crlf > lf else "\n"


def _atomic_write(path: Path, content: str) -> tuple[int, bool]:
    existed = path.exists()
    bom, newline = _text_format(path) if existed else (False, "\n")
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    if newline == "\r\n":
        normalized = normalized.replace("\n", "\r\n")
    data = normalized.encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    path.parent.mkdir(parents=True, exist_ok=True)
    mode: int | None = None
    if existed:
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
        except OSError:
            pass
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".xiaomei-",
            suffix=".tmp",
            dir=str(path.parent),
            delete=False,
        ) as handle:
            temp_path = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temp_path, mode)
        os.replace(temp_path, path)
        return len(data), not existed
    finally:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                logger.debug("Failed to remove temp file", exc_info=True)


def write(path: str, content: str) -> dict[str, Any]:
    if not isinstance(content, str):
        return {"error": "Error: content must be text"}
    resolved, error = _resolve(path, for_write=True)
    if error:
        return {"error": error}
    assert resolved is not None
    try:
        size, created = _atomic_write(resolved, content)
    except OSError as exc:
        return {"error": f"Error: {exc}"}
    return {
        "path": str(resolved),
        "relative_path": _display(resolved),
        "bytes_written": size,
        "created": created,
    }


def edit(
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> dict[str, Any]:
    resolved, error = _resolve(path, exists=True, for_write=True)
    if error:
        return {"error": error}
    assert resolved is not None
    try:
        raw = resolved.read_bytes()
    except OSError as exc:
        return {"error": f"Error: {exc}"}
    if _binary(raw):
        return {"error": f"Error: binary file cannot be edited: {path}"}
    original = raw.decode("utf-8-sig", errors="replace")
    count = original.count(old_string)
    if count == 0:
        return {"error": "Error: old_string was not found"}
    if count > 1 and not replace_all:
        return {
            "error": (
                f"Error: old_string occurs {count} times; add surrounding "
                "context or set replace_all=true"
            ),
        }
    updated = original.replace(old_string, new_string, -1 if replace_all else 1)
    # Build a display diff independently from the source file's final newline.
    # ``keepends=True`` can concatenate ``-old`` and ``+new`` when the edited
    # file has no trailing newline, which makes CLI/Desktop output misleading.
    diff_lines = list(difflib.unified_diff(
        original.splitlines(),
        updated.splitlines(),
        fromfile=_display(resolved),
        tofile=_display(resolved),
        lineterm="",
    ))
    diff = "\n".join(diff_lines)
    if diff:
        diff += "\n"
    try:
        size, _created = _atomic_write(resolved, updated)
    except OSError as exc:
        return {"error": f"Error: {exc}"}
    return {
        "path": str(resolved),
        "relative_path": _display(resolved),
        "replacements": count if replace_all else 1,
        "bytes_written": size,
        "diff": diff,
    }


def _pattern_error(pattern: str) -> str:
    if not isinstance(pattern, str) or not pattern.strip():
        return "Error: pattern cannot be empty"
    parts = Path(pattern).parts
    if Path(pattern).is_absolute() or ".." in parts:
        return "Error: pattern must be relative and cannot contain '..'"
    return ""


def _expand_brace_patterns(pattern: str, *, limit: int = 64) -> tuple[list[str], str]:
    """Expand shell-style ``*.{mp3,wav}`` alternatives for Python glob.

    ``glob`` from Python's standard library does not implement brace
    expansion, while models and users commonly use this portable-looking
    syntax.  Expand it explicitly and cap the result to avoid pathological
    patterns.
    """
    pending = [pattern]
    expanded: list[str] = []
    expression = re.compile(r"\{([^{}]+)\}")
    while pending:
        current = pending.pop()
        match = expression.search(current)
        if match is None:
            expanded.append(current)
            continue
        choices = [item.strip() for item in match.group(1).split(",") if item.strip()]
        if not choices:
            return [], "Error: glob brace alternatives cannot be empty"
        if len(pending) + len(expanded) + len(choices) > limit:
            return [], f"Error: glob pattern expands to more than {limit} alternatives"
        prefix, suffix = current[:match.start()], current[match.end():]
        pending.extend(f"{prefix}{choice}{suffix}" for choice in reversed(choices))
    return list(dict.fromkeys(expanded)), ""


def _split_named_root_pattern(pattern: str, path: str) -> tuple[str, str]:
    """Treat ``inputs/**/*.csv`` like ``path=inputs, pattern=**/*.csv``.

    Models naturally place a workspace directory either in ``path`` or at the
    start of the glob. Both forms must resolve identically.
    """
    if str(path or ".").strip() not in {"", ".", "./", ".\\"}:
        return pattern, path
    parts = Path(pattern).parts
    if len(parts) < 2:
        return pattern, path
    first = str(parts[0])
    named_roots = {
        root.name.casefold()
        for root in (
            Path(get_workspace_dir()).resolve(),
            *_writable_roots(),
            *_read_only_roots(),
        )
    }
    if first.casefold() not in named_roots:
        return pattern, path
    remainder = str(Path(*parts[1:]))
    return remainder, first


def glob(pattern: str, path: str = ".", limit: int = 200) -> dict[str, Any]:
    error = _pattern_error(pattern)
    if error:
        return {"error": error}
    pattern, path = _split_named_root_pattern(pattern, path)
    root, error = _resolve(path, exists=True)
    if error:
        return {"error": error}
    assert root is not None
    if not root.is_dir():
        return {"error": f"Error: not a directory: {path}"}
    patterns, error = _expand_brace_patterns(pattern)
    if error:
        return {"error": error}
    limit = min(1000, max(1, int(limit or 200)))
    found: list[Path] = []
    seen: set[Path] = set()
    try:
        for expanded_pattern in patterns:
            iterator = glob_module.iglob(
                str(root / expanded_pattern),
                recursive=True,
                include_hidden=True,
            )
            for value in iterator:
                item = Path(value)
                if item.is_file() and item not in seen:
                    seen.add(item)
                    found.append(item)
                    if len(found) > limit:
                        break
            if len(found) > limit:
                break
    except (OSError, ValueError) as exc:
        return {"error": f"Error: {exc}"}
    found.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    result: dict[str, Any] = {
        "files": [_display(item) for item in found[:limit]],
        "count": min(len(found), limit),
        "truncated": len(found) > limit,
    }
    return result


def _grep_candidates(path: str, file_glob: str) -> tuple[Iterator[Path], str]:
    error = _pattern_error(file_glob)
    if error:
        return iter(()), error
    file_glob, path = _split_named_root_pattern(file_glob, path)
    root, error = _resolve(path, exists=True)
    if error:
        return iter(()), error
    assert root is not None
    if root.is_file():
        return iter((root,)), ""
    if "/" not in file_glob and "\\" not in file_glob:
        file_glob = f"**/{file_glob}"
    iterator = (
        Path(value)
        for value in glob_module.iglob(
            str(root / file_glob),
            recursive=True,
            include_hidden=True,
        )
        if Path(value).is_file()
    )
    return iterator, ""


def grep(
    pattern: str,
    path: str = ".",
    glob: str = "**/*",
    output_mode: str = "content",
    context: int = 0,
    case_insensitive: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    if output_mode not in {"content", "files_with_matches", "count"}:
        return {"error": "Error: invalid output_mode"}
    try:
        expression = re.compile(pattern, re.IGNORECASE if case_insensitive else 0)
    except re.error as exc:
        return {"error": f"Error: invalid regular expression: {exc}"}
    candidates, error = _grep_candidates(path, glob)
    if error:
        return {"error": error}
    context = min(20, max(0, int(context or 0)))
    limit = min(2000, max(1, int(limit or 100)))
    matches: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    files_seen = 0
    for candidate in candidates:
        files_seen += 1
        if files_seen > MAX_SEARCH_FILES:
            break
        try:
            if candidate.stat().st_size > MAX_FILE_BYTES:
                continue
            raw = candidate.read_bytes()
        except OSError:
            continue
        if _binary(raw):
            continue
        lines = raw.decode("utf-8-sig", errors="replace").splitlines()
        display = _display(candidate)
        for index, line in enumerate(lines):
            if not expression.search(line):
                continue
            counts[display] = counts.get(display, 0) + 1
            if output_mode == "content" and len(matches) < limit:
                start, end = max(0, index - context), min(len(lines), index + context + 1)
                matches.append({
                    "path": display,
                    "line": index + 1,
                    "content": line,
                    "before": lines[start:index],
                    "after": lines[index + 1:end],
                })
        if output_mode == "content" and len(matches) >= limit:
            break
        if output_mode == "files_with_matches" and len(counts) >= limit:
            break
    result: dict[str, Any] = {
        "total_matches": sum(counts.values()),
        "matched_files": len(counts),
    }
    if output_mode == "content":
        result["matches"] = matches
        result["truncated"] = result["total_matches"] > len(matches)
    elif output_mode == "files_with_matches":
        result["files"] = list(counts)[:limit]
        result["truncated"] = len(counts) > limit
    else:
        result["counts"] = dict(list(counts.items())[:limit])
        result["truncated"] = len(counts) > limit
    return result


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
    func: Any,
) -> Tool:
    return Tool(
        name=name,
        description=description,
        parameters={
            "type": "object",
            "properties": properties,
            "required": required,
        },
        func=func,
        category="fs",
    )


read_tool = _tool(
    "read",
    "Read a text file with line numbers and pagination. Every user-operable file is below the current Agent workspace. Reuse relative paths returned by glob/write/edit exactly and never reconstruct an absolute Agent data directory. Inbound files are under inputs/ and generated files are normally under outputs/.",
    {
        "path": {"type": "string"},
        "offset": {"type": "integer", "minimum": 1, "default": 1},
        "limit": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 500},
    },
    ["path"],
    read,
)
write_tool = _tool(
    "write",
    "Create or completely replace a UTF-8 text file atomically. The current directory is already the Agent workspace: use work/analyze.py or outputs/report.md, never workspace/work/analyze.py. inputs/ is read-only.",
    {"path": {"type": "string"}, "content": {"type": "string"}},
    ["path", "content"],
    write,
)
edit_tool = _tool(
    "edit",
    "Edit a text file by exact replacement and return a unified diff. Reuse the exact workspace-relative path returned by glob/read; do not prepend workspace/ or rebuild an absolute Agent data path. inputs/ is read-only.",
    {
        "path": {"type": "string"},
        "old_string": {"type": "string"},
        "new_string": {"type": "string"},
        "replace_all": {"type": "boolean", "default": False},
    },
    ["path", "old_string", "new_string"],
    edit,
)
glob_tool = _tool(
    "glob",
    "Find files anywhere in the current Agent workspace. The default path '.' includes inputs, work, outputs, and project files. Shell-style alternatives such as **/*.{mp3,wav,m4a} are supported. Returned names are workspace-relative canonical paths; pass them unchanged to read/edit or the shell and never construct an absolute Agent data directory.",
    {
        "pattern": {
            "type": "string",
            "description": "Relative glob pattern; brace alternatives such as **/*.{mp3,wav} are supported.",
        },
        "path": {
            "type": "string",
            "default": ".",
            "description": "Workspace-relative directory to search; '.' searches the complete Agent workspace.",
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
    },
    ["pattern"],
    glob,
)
grep_tool = _tool(
    "grep",
    "Search text contents with a regular expression anywhere below the current Agent workspace. inputs/ contains read-only inbound files.",
    {
        "pattern": {"type": "string"},
        "path": {"type": "string", "default": "."},
        "glob": {"type": "string", "default": "**/*"},
        "output_mode": {
            "type": "string",
            "enum": ["content", "files_with_matches", "count"],
            "default": "content",
        },
        "context": {"type": "integer", "minimum": 0, "maximum": 20, "default": 0},
        "case_insensitive": {"type": "boolean", "default": False},
        "limit": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 100},
    },
    ["pattern"],
    grep,
)
