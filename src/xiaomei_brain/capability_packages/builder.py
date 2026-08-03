"""Build deterministic local ``.xmcap`` capability packages."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any
import zipfile

import yaml

from xiaomei_brain.capabilities.loader import CapabilityManifestLoader

from .inspector import CHECKSUMS_PATH, MANIFEST_PATH, CapabilityPackageInspector
from .models import CapabilityPackageManifest
from .repository import CapabilityPackageError


class CapabilityPackageBuilder:
    """Export one declared capability source tree without bundling stray files."""

    def __init__(self) -> None:
        self._inspector = CapabilityPackageInspector()

    def pack(
        self,
        source_dir: str | Path,
        *,
        output_path: str | Path | None = None,
    ) -> dict[str, Any]:
        source = Path(source_dir).expanduser().resolve()
        if not source.is_dir():
            raise CapabilityPackageError(f"能力源目录不存在: {source}")

        manifest_path = source / MANIFEST_PATH
        try:
            raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("根节点必须是对象")
            manifest = CapabilityPackageManifest.model_validate(raw)
        except Exception as exc:
            raise CapabilityPackageError(f"capability.yaml 无效: {exc}") from exc

        files = self._collect_files(source, manifest)
        self._validate_catalog(source, manifest)
        destination = self._destination(source, manifest, output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)

        checksums = {
            relative: hashlib.sha256(content).hexdigest()
            for relative, content in sorted(files.items())
        }
        checksum_bytes = (
            json.dumps(
                {"algorithm": "sha256", "files": checksums},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")

        handle, temporary = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent,
        )
        os.close(handle)
        try:
            with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                for relative, content in sorted({**files, CHECKSUMS_PATH: checksum_bytes}.items()):
                    info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.create_system = 3
                    info.external_attr = 0o100644 << 16
                    archive.writestr(info, content)

            data = Path(temporary).read_bytes()
            inspection = self._inspector.inspect(data, file_name=destination.name)
            if not inspection.get("valid"):
                errors = inspection.get("errors") or ["未知错误"]
                raise CapabilityPackageError(
                    "导出后自检失败: " + "; ".join(str(item) for item in errors[:5])
                )
            os.replace(temporary, destination)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

        return {
            "path": str(destination),
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "size": destination.stat().st_size,
            "package": manifest.package.model_dump(),
            "file_count": len(files) + 1,
        }

    def _collect_files(
        self,
        source: Path,
        manifest: CapabilityPackageManifest,
    ) -> dict[str, bytes]:
        declared = [MANIFEST_PATH]
        for paths in manifest.contents.values():
            declared.extend(paths)

        files: dict[str, bytes] = {}
        for relative in declared:
            safe = self._inspector._safe_path(relative)
            if not safe or safe != relative or safe == CHECKSUMS_PATH:
                raise CapabilityPackageError(f"能力包声明了不安全的路径: {relative}")
            if safe in files:
                raise CapabilityPackageError(f"能力包重复声明文件: {safe}")
            path = (source / Path(safe)).resolve()
            try:
                path.relative_to(source)
            except ValueError as exc:
                raise CapabilityPackageError(f"能力包路径越界: {safe}") from exc
            if not path.is_file() or path.is_symlink():
                raise CapabilityPackageError(f"能力包声明的文件不存在或不可用: {safe}")
            files[safe] = path.read_bytes()
        return files

    @staticmethod
    def _validate_catalog(source: Path, manifest: CapabilityPackageManifest) -> None:
        declared = {item.id for item in manifest.capabilities}
        loaded = {
            CapabilityManifestLoader.load_file(source / path).id
            for path in sorted(manifest.contents.get("capabilities") or [])
        }
        if loaded != declared:
            raise CapabilityPackageError(
                "capability.yaml 声明的能力与 capabilities/ 清单不一致"
            )

        if manifest.contents.get("processes"):
            from xiaomei_brain.processes import ProcessTemplateRegistry
            ProcessTemplateRegistry([source / "processes"])

    @staticmethod
    def _destination(
        source: Path,
        manifest: CapabilityPackageManifest,
        output_path: str | Path | None,
    ) -> Path:
        if output_path is None:
            name = f"{manifest.package.id}-{manifest.package.version}.xmcap"
            return (source.parent / name).resolve()
        destination = Path(output_path).expanduser().resolve()
        if destination.suffix.lower() != ".xmcap":
            destination = destination.with_suffix(".xmcap")
        return destination
