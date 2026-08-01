"""Application service shared by conversational template tools and writers."""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from xiaomei_brain.documents.rendering import render_office_preview

from .models import DocumentTemplate
from .store import DocumentTemplateStore


_MAX_TEMPLATE_BYTES = 20 * 1024 * 1024
_INVALID_FILE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class DocumentTemplateService:
    """Own immutable template sources and their queryable metadata."""

    def __init__(self, registry: Any, agent_root: str | Path, db_path: str | Path) -> None:
        self.registry = registry
        self.agent_root = Path(agent_root).resolve()
        self.db_path = Path(db_path)
        self.templates_root = self.agent_root / "documents" / "templates"

    def _store(self) -> DocumentTemplateStore:
        return DocumentTemplateStore(self.db_path)

    @staticmethod
    def _digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _scope(scope_type: str, person_id: str) -> tuple[str, str]:
        scope = str(scope_type or "person").strip().lower()
        if scope not in {"person", "global"}:
            raise ValueError("scope_type 只支持 person 或 global")
        if scope == "person" and not person_id:
            raise ValueError("个人模板需要当前 Person 身份")
        return scope, person_id if scope == "person" else ""

    def _analyzer(self, format_id: str) -> Any:
        writer = self.registry.get_document_writer(format_id)
        analyzer = getattr(writer, "template_analyzer", None)
        if analyzer is None:
            raise ValueError(f"当前没有可分析 {format_id} 模板的插件")
        return analyzer

    @staticmethod
    def _validate_source(source: Path) -> None:
        if not source.is_file():
            raise ValueError("模板附件文件不可用")
        if source.suffix.lower() != ".docx":
            raise ValueError("第一版模板库只支持 DOCX")
        size = source.stat().st_size
        if size <= 0 or size > _MAX_TEMPLATE_BYTES:
            raise ValueError("模板文件必须大于 0 且不超过 20 MB")

    @staticmethod
    def _normalize_name(name: str) -> str:
        normalized = " ".join(str(name).split()).strip()
        if not normalized or len(normalized) > 100:
            raise ValueError("模板名称不能为空且不能超过 100 个字符")
        return normalized

    @staticmethod
    def _normalize_keywords(keywords: list[str] | None) -> list[str]:
        values: list[str] = []
        for raw in keywords or []:
            value = " ".join(str(raw).split()).strip()
            if value and value not in values:
                values.append(value[:50])
        return values[:30]

    def register(
        self,
        source_path: str | Path,
        *,
        name: str,
        person_id: str,
        description: str = "",
        keywords: list[str] | None = None,
        scope_type: str = "person",
    ) -> DocumentTemplate:
        source = Path(source_path).resolve(strict=True)
        self._validate_source(source)
        normalized_name = self._normalize_name(name)
        scope, scope_id = self._scope(scope_type, person_id)
        analyzer = self._analyzer("word")
        manifest = analyzer.analyze(source)
        digest = self._digest(source)

        store = self._store()
        try:
            existing = store.find_scope_name(scope, scope_id, normalized_name)
            if existing is not None:
                if existing.sha256 == digest:
                    return existing
                raise ValueError("同一范围内已存在同名模板，请使用 update 替换")

            template_id = f"template_{uuid4().hex}"
            directory = self.templates_root / template_id
            directory.mkdir(parents=True, exist_ok=False)
            stored_source = directory / "template.docx"
            preview = directory / "preview.png"
            try:
                shutil.copy2(source, stored_source)
                preview_result = render_office_preview(stored_source, preview)
                preview_relative = (
                    preview.relative_to(self.agent_root).as_posix()
                    if preview_result.get("performed") is True and preview.is_file()
                    else ""
                )
                return store.insert({
                    "template_id": template_id,
                    "format": "word",
                    "name": normalized_name,
                    "description": str(description).strip()[:1000],
                    "keywords": self._normalize_keywords(keywords),
                    "scope_type": scope,
                    "scope_id": scope_id,
                    "created_by_person_id": person_id,
                    "source_filename": source.name,
                    "storage_relative_path": stored_source.relative_to(self.agent_root).as_posix(),
                    "preview_relative_path": preview_relative,
                    "sha256": digest,
                    "manifest": manifest,
                })
            except Exception:
                shutil.rmtree(directory, ignore_errors=True)
                raise
        finally:
            store.close()

    def list(self, person_id: str, format_id: str = "word") -> list[DocumentTemplate]:
        store = self._store()
        try:
            return store.list_visible(person_id, format_id)
        finally:
            store.close()

    def resolve(self, template_ref: str, person_id: str) -> DocumentTemplate:
        store = self._store()
        try:
            record = store.resolve(str(template_ref).strip(), person_id)
        finally:
            store.close()
        if record is None:
            raise ValueError(f"没有找到当前 Person 可使用的模板: {template_ref}")
        return record

    def _internal_path(self, relative_path: str) -> Path:
        try:
            path = (self.agent_root / relative_path).resolve(strict=True)
            path.relative_to(self.templates_root.resolve())
        except (OSError, ValueError) as exc:
            raise ValueError("模板文件索引损坏") from exc
        return path

    def source_for_use(self, template_ref: str, person_id: str) -> tuple[DocumentTemplate, Path]:
        record = self.resolve(template_ref, person_id)
        path = self._internal_path(record.storage_relative_path)
        if self._digest(path) != record.sha256:
            raise ValueError(f"模板文件完整性检查失败: {record.name}")
        return record, path

    def copy_preview_to(
        self,
        template: DocumentTemplate,
        output_root: str | Path,
        session_id: str,
    ) -> Path | None:
        if not template.preview_relative_path:
            return None
        source = self._internal_path(template.preview_relative_path)
        output_base = Path(output_root).resolve()
        try:
            output_base.relative_to(self.agent_root)
        except ValueError as exc:
            raise ValueError("模板预览只能复制到当前 Agent 的输出目录") from exc
        safe_name = _INVALID_FILE_CHARS.sub("_", template.name).strip(" ._") or "Word模板"
        session_key = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12]
        directory = output_base / "template-previews" / session_key
        directory.mkdir(parents=True, exist_ok=True)
        output = directory / f"{safe_name}-模板预览.png"
        shutil.copy2(source, output)
        return output

    def validate_generated(
        self,
        template: DocumentTemplate,
        output_path: Path,
    ) -> list[str]:
        analyzer = self._analyzer(template.format)
        return analyzer.unresolved_placeholders(output_path)

    def update(
        self,
        template_ref: str,
        person_id: str,
        *,
        source_path: str | Path | None = None,
        name: str = "",
        description: str | None = None,
        keywords: list[str] | None = None,
        scope_type: str = "",
    ) -> DocumentTemplate:
        current = self.resolve(template_ref, person_id)
        values: dict[str, Any] = {}
        if name:
            values["name"] = self._normalize_name(name)
        if description is not None:
            values["description"] = str(description).strip()[:1000]
        if keywords is not None:
            values["keywords"] = self._normalize_keywords(keywords)
        if scope_type:
            scope, scope_id = self._scope(scope_type, person_id)
            values.update({"scope_type": scope, "scope_id": scope_id})

        directory = self._internal_path(current.storage_relative_path).parent
        stable_source = directory / "template.docx"
        stable_preview = directory / "preview.png"
        backup_source: Path | None = None
        backup_preview: Path | None = None
        if source_path is not None:
            source = Path(source_path).resolve(strict=True)
            self._validate_source(source)
            analyzer = self._analyzer(current.format)
            manifest = analyzer.analyze(source)
            digest = self._digest(source)
            pending_source = directory / f".template-{uuid4().hex}.docx"
            pending_preview = directory / f".preview-{uuid4().hex}.png"
            shutil.copy2(source, pending_source)
            preview_result = render_office_preview(pending_source, pending_preview)
            backup_source = directory / f".backup-{uuid4().hex}.docx"
            stable_source.replace(backup_source)
            if stable_preview.exists():
                backup_preview = directory / f".backup-{uuid4().hex}.png"
                stable_preview.replace(backup_preview)
            pending_source.replace(stable_source)
            if preview_result.get("performed") is True and pending_preview.is_file():
                pending_preview.replace(stable_preview)
                preview_relative = stable_preview.relative_to(self.agent_root).as_posix()
            else:
                pending_preview.unlink(missing_ok=True)
                preview_relative = ""
            values.update({
                "source_filename": source.name,
                "storage_relative_path": stable_source.relative_to(self.agent_root).as_posix(),
                "preview_relative_path": preview_relative,
                "sha256": digest,
                "manifest": manifest,
            })

        if not values:
            raise ValueError("update 至少需要修改一个模板字段或提供新附件")
        store = self._store()
        try:
            updated = store.update(current.template_id, values)
        except Exception:
            if backup_source is not None and backup_source.exists():
                stable_source.unlink(missing_ok=True)
                backup_source.replace(stable_source)
            if backup_preview is not None and backup_preview.exists():
                stable_preview.unlink(missing_ok=True)
                backup_preview.replace(stable_preview)
            raise
        finally:
            store.close()
        if backup_source is not None:
            backup_source.unlink(missing_ok=True)
        if backup_preview is not None:
            backup_preview.unlink(missing_ok=True)
        return updated

    def remove(self, template_ref: str, person_id: str) -> DocumentTemplate:
        record = self.resolve(template_ref, person_id)
        directory = self._internal_path(record.storage_relative_path).parent
        quarantine = directory.with_name(f".{directory.name}.deleting-{uuid4().hex}")
        directory.replace(quarantine)
        store = self._store()
        try:
            if not store.delete(record.template_id):
                raise ValueError("模板索引已经不存在")
        except Exception:
            quarantine.replace(directory)
            raise
        finally:
            store.close()
        shutil.rmtree(quarantine, ignore_errors=True)
        return record
