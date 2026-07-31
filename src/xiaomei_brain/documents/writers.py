"""Protocol implemented by document-authoring plugins."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class DocumentWriter(Protocol):
    format_id: str
    suffix: str

    def write(
        self,
        specification: dict[str, Any],
        output_path: Path,
        *,
        source_path: Path | None = None,
        asset_paths: dict[str, Path] | None = None,
    ) -> dict[str, Any]: ...
