"""Safe, non-executing inspection of portable capability archives."""

from __future__ import annotations

import hashlib
import io
import json
import posixpath
import stat
import zipfile
from typing import Any

import yaml
from pydantic import ValidationError

from .models import CapabilityPackageManifest


MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_ENTRIES = 512
MAX_COMPRESSION_RATIO = 200
MANIFEST_PATH = "capability.yaml"
CHECKSUMS_PATH = "checksums.json"


class CapabilityPackageInspector:
    """Validate structure and checksums without extracting or importing code."""

    def inspect(self, data: bytes, *, file_name: str = "") -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        result: dict[str, Any] = {
            "valid": False,
            "file_name": file_name,
            "archive_size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "errors": errors,
            "warnings": warnings,
        }
        if not file_name.lower().endswith(".xmcap"):
            errors.append("能力包文件必须使用 .xmcap 扩展名")
        if not data:
            errors.append("能力包内容为空")
            return result
        if len(data) > MAX_ARCHIVE_BYTES:
            errors.append(f"能力包超过 {MAX_ARCHIVE_BYTES // (1024 * 1024)} MB 检查上限")
            return result

        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = self._validate_entries(archive, errors)
                if errors:
                    return result
                names = {entry.filename for entry in entries}
                file_names = {entry.filename for entry in entries if not entry.is_dir()}
                if MANIFEST_PATH not in names:
                    errors.append(f"能力包根目录缺少 {MANIFEST_PATH}")
                    return result
                if CHECKSUMS_PATH not in names:
                    errors.append(f"能力包根目录缺少 {CHECKSUMS_PATH}")
                    return result

                manifest = self._read_manifest(archive, errors)
                if manifest is None:
                    return result
                self._validate_declared_contents(manifest, file_names, errors)
                self._validate_checksums(archive, entries, errors)
                if errors:
                    result["manifest"] = manifest.public_dict()
                    return result

                requirements = manifest.requirements
                if requirements.python_packages or requirements.node_packages or requirements.executables:
                    warnings.append("此能力包声明了外部依赖；当前安装器不会自动安装依赖")
                result.update({
                    "valid": True,
                    "manifest": manifest.public_dict(),
                    "entry_count": len(entries),
                    "uncompressed_size": sum(item.file_size for item in entries),
                })
                return result
        except zipfile.BadZipFile:
            errors.append("文件不是有效的 ZIP/.xmcap 归档")
        except Exception as exc:
            errors.append(f"能力包检查失败: {exc}")
        return result

    @staticmethod
    def _safe_path(raw: str) -> str:
        if not raw or "\\" in raw or raw.startswith(("/", "~")):
            return ""
        normalized = posixpath.normpath(raw)
        if normalized in {".", ".."} or normalized.startswith("../") or ":" in normalized:
            return ""
        return normalized

    def _validate_entries(
        self,
        archive: zipfile.ZipFile,
        errors: list[str],
    ) -> list[zipfile.ZipInfo]:
        entries = archive.infolist()
        if len(entries) > MAX_ENTRIES:
            errors.append(f"能力包文件数超过 {MAX_ENTRIES} 个")
            return []
        seen: set[str] = set()
        total = 0
        for entry in entries:
            safe = self._safe_path(entry.filename)
            if not safe or safe != entry.filename.rstrip("/"):
                errors.append(f"能力包包含不安全路径: {entry.filename}")
                continue
            if safe in seen:
                errors.append(f"能力包包含重复路径: {safe}")
            seen.add(safe)
            mode = entry.external_attr >> 16
            if mode and stat.S_ISLNK(mode):
                errors.append(f"能力包不允许符号链接: {safe}")
            if entry.flag_bits & 0x1:
                errors.append(f"能力包不允许加密文件: {safe}")
            total += entry.file_size
            if entry.file_size and not entry.compress_size:
                errors.append(f"文件压缩信息异常: {safe}")
            elif entry.compress_size and entry.file_size / entry.compress_size > MAX_COMPRESSION_RATIO:
                errors.append(f"文件压缩比异常: {safe}")
        if total > MAX_UNCOMPRESSED_BYTES:
            errors.append(f"能力包解压后超过 {MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MB")
        return entries

    @staticmethod
    def _read_manifest(
        archive: zipfile.ZipFile,
        errors: list[str],
    ) -> CapabilityPackageManifest | None:
        info = archive.getinfo(MANIFEST_PATH)
        if info.file_size > MAX_MANIFEST_BYTES:
            errors.append("capability.yaml 过大")
            return None
        try:
            raw = yaml.safe_load(archive.read(info).decode("utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("根节点必须是对象")
            return CapabilityPackageManifest.model_validate(raw)
        except UnicodeDecodeError:
            errors.append("capability.yaml 必须使用 UTF-8 编码")
        except (ValidationError, ValueError, yaml.YAMLError) as exc:
            errors.append(f"capability.yaml 无效: {exc}")
        return None

    def _validate_declared_contents(
        self,
        manifest: CapabilityPackageManifest,
        archive_names: set[str],
        errors: list[str],
    ) -> None:
        for category, paths in manifest.contents.items():
            for path in paths:
                safe = self._safe_path(path)
                if not safe or safe != path:
                    errors.append(f"内容分类 {category} 声明了不安全路径: {path}")
                elif safe not in archive_names:
                    errors.append(f"内容分类 {category} 引用了不存在的文件: {path}")

    @staticmethod
    def _validate_checksums(
        archive: zipfile.ZipFile,
        entries: list[zipfile.ZipInfo],
        errors: list[str],
    ) -> None:
        try:
            raw = json.loads(archive.read(CHECKSUMS_PATH).decode("utf-8"))
        except Exception as exc:
            errors.append(f"checksums.json 无效: {exc}")
            return
        if not isinstance(raw, dict) or raw.get("algorithm") != "sha256":
            errors.append("checksums.json 必须声明 algorithm: sha256")
            return
        checksums = raw.get("files")
        if not isinstance(checksums, dict):
            errors.append("checksums.json 缺少 files 对象")
            return
        expected = {
            item.filename for item in entries
            if not item.is_dir() and item.filename != CHECKSUMS_PATH
        }
        actual = set(checksums)
        for missing in sorted(expected - actual):
            errors.append(f"校验清单缺少文件: {missing}")
        for extra in sorted(actual - expected):
            errors.append(f"校验清单引用未知文件: {extra}")
        for path in sorted(expected & actual):
            digest = checksums.get(path)
            if not isinstance(digest, str) or len(digest) != 64:
                errors.append(f"无效 SHA-256: {path}")
                continue
            calculated = hashlib.sha256(archive.read(path)).hexdigest()
            if calculated.lower() != digest.lower():
                errors.append(f"文件校验失败: {path}")
