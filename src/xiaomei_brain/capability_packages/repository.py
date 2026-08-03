"""Shared capability package repository with per-Agent activation locks."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
from typing import Any, Iterator
import zipfile

import yaml

from xiaomei_brain.capabilities.loader import CapabilityManifestLoader

from .inspector import CHECKSUMS_PATH, CapabilityPackageInspector
from .models import PACKAGE_ID_PATTERN


RUNTIME_CONTENT_KINDS = frozenset({
    "capabilities",
    "plugins",
    "processes",
    "skills",
    "scripts",
    "resources",
})


class CapabilityPackageError(ValueError):
    """A user-facing package lifecycle error."""


@dataclass(frozen=True)
class InstalledPackage:
    package_id: str
    name: str
    version: str
    sha256: str
    publisher: str
    description: str
    installed_at: float
    package_dir: Path
    manifest: dict[str, Any]

    @property
    def content_dir(self) -> Path:
        return self.package_dir / "content"

    def to_dict(
        self,
        *,
        active: bool = False,
        runtime_valid: bool = True,
        issue: str = "",
        loaded: bool = False,
    ) -> dict[str, Any]:
        return {
            "id": self.package_id,
            "name": self.name,
            "version": self.version,
            "sha256": self.sha256,
            "publisher": self.publisher,
            "description": self.description,
            "installed_at": self.installed_at,
            "active": active,
            "runtime_valid": runtime_valid,
            "issue": issue,
            "loaded": loaded,
            "capabilities": list(self.manifest.get("capabilities") or []),
            "permissions": list(self.manifest.get("permissions") or []),
            "requirements": dict(self.manifest.get("requirements") or {}),
        }


class _RepositoryFileLock:
    """Small cross-process lock using exclusive file creation."""

    def __init__(self, path: Path, *, timeout: float = 10.0) -> None:
        self.path = path
        self.timeout = timeout
        self._owned = False

    def __enter__(self):
        deadline = time.monotonic() + self.timeout
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                handle = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(handle, "w", encoding="utf-8") as stream:
                    json.dump({"pid": os.getpid(), "created_at": time.time()}, stream)
                self._owned = True
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > 120:
                        self.path.unlink()
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() >= deadline:
                    raise CapabilityPackageError("能力包仓库正被其他 Agent 使用，请稍后重试")
                time.sleep(0.05)

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        if self._owned:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


class CapabilityPackageService:
    """Install immutable shared packages and activate them for one Agent."""

    def __init__(self, *, base_dir: str | Path, agent_id: str) -> None:
        self.base_dir = Path(base_dir).expanduser().resolve()
        self.agent_id = str(agent_id).strip()
        self.repository_dir = self.base_dir / "capability-packages"
        self.cache_dir = self.repository_dir / "cache"
        self.installed_dir = self.repository_dir / "installed"
        self.lock_path = self.base_dir / self.agent_id / "capabilities.lock"
        self._repository_lock = self.repository_dir / ".repository.lock"
        self._thread_lock = threading.RLock()
        self._inspector = CapabilityPackageInspector()
        self._runtime_issues: dict[str, str] = {}
        self._loaded_packages: set[tuple[str, str, str]] = set()
        self._protected_skill_directories: set[Path] = set()

    def add_protected_skill_directories(self, directories: list[str | Path]) -> None:
        """Protect normal host/plugin Skill sources from package collisions."""
        self._protected_skill_directories.update(
            Path(directory).expanduser().resolve() for directory in directories
        )

    def install(
        self,
        data: bytes,
        *,
        file_name: str,
        expected_sha256: str = "",
    ) -> dict[str, Any]:
        inspection = self._inspector.inspect(data, file_name=file_name)
        if not inspection.get("valid"):
            errors = inspection.get("errors") or ["能力包检查失败"]
            raise CapabilityPackageError("；".join(str(item) for item in errors[:5]))
        sha256 = str(inspection["sha256"])
        if expected_sha256 and sha256.lower() != expected_sha256.lower():
            raise CapabilityPackageError("能力包内容已改变，请重新检查")
        manifest = dict(inspection["manifest"])
        self._validate_installable_manifest(manifest)
        identity = dict(manifest["package"])
        package_id = str(identity["id"])
        version = str(identity["version"])

        with self._thread_lock, _RepositoryFileLock(self._repository_lock):
            previous = self._latest_installed(package_id)
            target = self.installed_dir / package_id / version
            existing = self._read_record(target)
            if existing is not None:
                if existing.sha256 != sha256:
                    raise CapabilityPackageError(
                        "同一能力包 ID 和版本已存在，但内容不同；请使用新的版本号"
                    )
                affected_agents = self._migrate_agent_locks(existing)
                return {
                    "package": existing.to_dict(),
                    "already_installed": True,
                    "operation": "upgraded" if previous and previous.version != version else "existing",
                    "affected_agents": affected_agents,
                }

            target.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=f".{version}.", dir=target.parent))
            try:
                content_dir = staging / "content"
                content_dir.mkdir()
                self._extract_validated(data, content_dir)
                self._validate_runtime_catalog(manifest, content_dir)
                record = {
                    "schema_version": 1,
                    "sha256": sha256,
                    "installed_at": time.time(),
                    "manifest": manifest,
                }
                self._write_json(staging / "package.json", record)
                self._write_cache(data, sha256)
                os.replace(staging, target)
            except Exception:
                shutil.rmtree(staging, ignore_errors=True)
                raise
            installed = self._read_record(target)
            if installed is None:
                raise CapabilityPackageError("能力包安装记录写入失败")
            affected_agents = self._migrate_agent_locks(installed)
            return {
                "package": installed.to_dict(),
                "already_installed": False,
                "operation": "upgraded" if previous is not None else "installed",
                "affected_agents": affected_agents,
            }

    def activate(self, package_id: str, version: str, sha256: str = "") -> dict[str, Any]:
        with self._thread_lock, _RepositoryFileLock(self._repository_lock):
            installed = self.get_installed(package_id, version)
            if installed is None:
                raise CapabilityPackageError("能力包尚未安装")
            if sha256 and installed.sha256.lower() != sha256.lower():
                raise CapabilityPackageError("能力包版本与检查结果不一致")
            valid, issue = self.verify(installed)
            if not valid:
                raise CapabilityPackageError(issue)
            lock = self._read_activation_lock()
            self._validate_activation_collisions(installed, lock)
            packages = lock.setdefault("packages", {})
            packages[installed.package_id] = {
                "version": installed.version,
                "sha256": installed.sha256,
                "enabled": True,
                "activated_at": time.time(),
            }
            hidden_skills = set(lock.get("hidden_skills") or [])
            hidden_skills.difference_update(self._package_skill_names(installed))
            lock["hidden_skills"] = sorted(hidden_skills)
            self._write_json(self.lock_path, lock)
            return installed.to_dict(
                active=True,
                loaded=(installed.package_id, installed.version, installed.sha256) in self._loaded_packages,
            )

    def deactivate(self, package_id: str) -> dict[str, Any]:
        with self._thread_lock, _RepositoryFileLock(self._repository_lock):
            lock = self._read_activation_lock()
            entry = lock.setdefault("packages", {}).get(package_id)
            if not isinstance(entry, dict):
                raise CapabilityPackageError("当前 Agent 未激活该能力包")
            entry["enabled"] = False
            entry["deactivated_at"] = time.time()
            self._write_json(self.lock_path, lock)
            installed = self.get_installed(package_id, str(entry.get("version") or ""))
            if installed is None:
                return {"id": package_id, "active": False, "runtime_valid": False, "issue": "安装文件不存在"}
            return installed.to_dict(
                active=False,
                loaded=(installed.package_id, installed.version, installed.sha256) in self._loaded_packages,
            )

    def uninstall(self, package_id: str) -> dict[str, Any]:
        """Remove one shared package and detach it from every local Agent."""
        package_id = str(package_id).strip()
        if not PACKAGE_ID_PATTERN.fullmatch(package_id):
            raise CapabilityPackageError("能力包 ID 无效")

        with self._thread_lock, _RepositoryFileLock(self._repository_lock):
            installed_versions = self._installed_for_id(package_id)
            if not installed_versions:
                raise CapabilityPackageError("能力包尚未安装")

            skill_names: set[str] = set()
            cache_hashes: set[str] = set()
            for installed in installed_versions:
                skill_names.update(self._package_skill_names(installed))
                cache_hashes.add(installed.sha256)

            affected_agents: list[str] = []
            agent_locks = list(self._iter_agent_locks())
            for lock_path, lock in agent_locks:
                packages = lock.setdefault("packages", {})
                if package_id not in packages:
                    continue
                packages.pop(package_id, None)
                hidden = set(lock.get("hidden_skills") or [])
                hidden.update(skill_names)
                lock["hidden_skills"] = sorted(hidden)
                self._write_json(lock_path, lock)
                affected_agents.append(lock_path.parent.name)

            package_root = (self.installed_dir / package_id).resolve()
            installed_root = self.installed_dir.resolve()
            if package_root.parent != installed_root:
                raise CapabilityPackageError("能力包安装路径无效")
            shutil.rmtree(package_root)
            for sha256 in cache_hashes:
                try:
                    (self.cache_dir / f"{sha256}.xmcap").unlink()
                except FileNotFoundError:
                    pass

            return {
                "package_id": package_id,
                "affected_agents": sorted(set(affected_agents)),
                "removed_versions": sorted(item.version for item in installed_versions),
            }

    def list_packages(self) -> list[dict[str, Any]]:
        activation = self._read_activation_lock().get("packages", {})
        activation = activation if isinstance(activation, dict) else {}
        result: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        visible: dict[str, InstalledPackage] = {}
        for installed in self._scan_installed():
            entry = activation.get(installed.package_id)
            if (
                isinstance(entry, dict)
                and entry.get("version") == installed.version
                and entry.get("sha256") == installed.sha256
            ):
                visible[installed.package_id] = installed
                continue
            current = visible.get(installed.package_id)
            if current is None or installed.installed_at > current.installed_at:
                visible[installed.package_id] = installed

        for installed in visible.values():
            entry = activation.get(installed.package_id)
            active = bool(
                isinstance(entry, dict)
                and entry.get("enabled") is True
                and entry.get("version") == installed.version
                and entry.get("sha256") == installed.sha256
            )
            valid, issue = self.verify(installed)
            loaded = (installed.package_id, installed.version, installed.sha256) in self._loaded_packages
            result.append(installed.to_dict(
                active=active,
                runtime_valid=valid,
                issue=issue,
                loaded=loaded,
            ))
            seen.add((installed.package_id, installed.version))
        for package_id, entry in activation.items():
            if not isinstance(entry, dict) or entry.get("enabled") is not True:
                continue
            version = str(entry.get("version") or "")
            if (package_id, version) in seen:
                continue
            result.append({
                "id": package_id,
                "name": package_id,
                "version": version,
                "sha256": str(entry.get("sha256") or ""),
                "publisher": "",
                "description": "",
                "installed_at": 0,
                "active": True,
                "runtime_valid": False,
                "issue": "当前 Agent 的激活记录引用了不存在的安装包",
                "loaded": False,
                "capabilities": [],
                "permissions": [],
                "requirements": {},
            })
        return sorted(result, key=lambda item: (str(item["name"]), str(item["version"])))

    def runtime_directories(self) -> dict[str, list[str]]:
        """Return verified directories for packages active for this Agent."""
        self._runtime_issues = {}
        self._loaded_packages = set()
        result = {
            "plugins": [],
            "processes": [],
            "skills": [],
            "capabilities": [],
            "resources": [],
            "scripts": [],
        }
        activation = self._read_activation_lock().get("packages", {})
        if not isinstance(activation, dict):
            return result
        for package_id, entry in activation.items():
            if not isinstance(entry, dict) or entry.get("enabled") is not True:
                continue
            installed = self.get_installed(package_id, str(entry.get("version") or ""))
            if installed is None or installed.sha256 != str(entry.get("sha256") or ""):
                self._runtime_issues[package_id] = "激活记录与共享仓库不一致"
                continue
            valid, issue = self.verify(installed)
            if not valid:
                self._runtime_issues[package_id] = issue
                continue
            self._loaded_packages.add((installed.package_id, installed.version, installed.sha256))
            contents = installed.manifest.get("contents") or {}
            for kind in result:
                if contents.get(kind):
                    directory = installed.content_dir / kind
                    if directory.is_dir():
                        result[kind].append(str(directory))
        return result

    @property
    def runtime_issues(self) -> dict[str, str]:
        return dict(self._runtime_issues)

    def inactive_skill_names(self) -> set[str]:
        """Return package Skills that must stay hidden in this Agent's storage.

        Skill documents are imported into the Agent database. They therefore
        outlive one process and must be explicitly hidden when their package is
        inactive, damaged, or waiting for a restart. Agent-local and built-in
        Skills always keep precedence.
        """
        loaded_skills: set[str] = set()
        lock = self._read_activation_lock()
        inactive_skills: set[str] = set(lock.get("hidden_skills") or [])
        for installed in self._scan_installed():
            names = self._package_skill_names(installed)
            identity = (installed.package_id, installed.version, installed.sha256)
            if identity in self._loaded_packages:
                loaded_skills.update(names)
            else:
                inactive_skills.update(names)
        return inactive_skills - loaded_skills - self._protected_skill_names()

    def get_installed(self, package_id: str, version: str) -> InstalledPackage | None:
        if not package_id or not version:
            return None
        return self._read_record(self.installed_dir / package_id / version)

    def _installed_for_id(self, package_id: str) -> list[InstalledPackage]:
        root = self.installed_dir / package_id
        if not root.is_dir():
            return []
        return [
            installed
            for path in sorted(root.iterdir())
            if path.is_dir() and (installed := self._read_record(path)) is not None
        ]

    def _latest_installed(self, package_id: str) -> InstalledPackage | None:
        installed = self._installed_for_id(package_id)
        return max(installed, key=lambda item: item.installed_at, default=None)

    def _iter_agent_locks(self) -> Iterator[tuple[Path, dict[str, Any]]]:
        for lock_path in sorted(self.base_dir.glob("*/capabilities.lock")):
            if not lock_path.is_file():
                continue
            try:
                raw = json.loads(lock_path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise CapabilityPackageError(
                    f"Agent {lock_path.parent.name} capabilities.lock 无法读取: {exc}"
                ) from exc
            if not isinstance(raw, dict) or raw.get("schema_version") != 1:
                raise CapabilityPackageError(
                    f"Agent {lock_path.parent.name} capabilities.lock 格式无效"
                )
            if not isinstance(raw.get("packages", {}), dict):
                raise CapabilityPackageError(
                    f"Agent {lock_path.parent.name} capabilities.lock packages 必须是对象"
                )
            raw.setdefault("packages", {})
            if not isinstance(raw.get("hidden_skills", []), list):
                raise CapabilityPackageError(
                    f"Agent {lock_path.parent.name} capabilities.lock hidden_skills 必须是列表"
                )
            raw.setdefault("hidden_skills", [])
            yield lock_path, raw

    def _migrate_agent_locks(self, installed: InstalledPackage) -> list[str]:
        candidates: list[tuple[Path, dict[str, Any], dict[str, Any]]] = []
        for lock_path, lock in self._iter_agent_locks():
            entry = lock.setdefault("packages", {}).get(installed.package_id)
            if not isinstance(entry, dict):
                continue
            if entry.get("version") == installed.version and entry.get("sha256") == installed.sha256:
                continue
            if entry.get("enabled") is True:
                agent_service = CapabilityPackageService(
                    base_dir=self.base_dir,
                    agent_id=lock_path.parent.name,
                )
                agent_service.add_protected_skill_directories(
                    list(self._protected_skill_directories)
                )
                agent_service._validate_activation_collisions(installed, lock)
            candidates.append((lock_path, lock, entry))

        affected: list[str] = []
        for lock_path, lock, entry in candidates:
            entry["version"] = installed.version
            entry["sha256"] = installed.sha256
            entry["updated_at"] = time.time()
            self._write_json(lock_path, lock)
            affected.append(lock_path.parent.name)
        return sorted(set(affected))

    def verify(self, installed: InstalledPackage) -> tuple[bool, str]:
        try:
            checksums_path = installed.content_dir / CHECKSUMS_PATH
            checksums_raw = json.loads(checksums_path.read_text(encoding="utf-8"))
            if checksums_raw.get("algorithm") != "sha256" or not isinstance(checksums_raw.get("files"), dict):
                return False, "能力包校验清单损坏"
            expected: dict[str, str] = checksums_raw["files"]
            self._remove_runtime_bytecode(installed.content_dir, set(expected))
            actual_files = {
                path.relative_to(installed.content_dir).as_posix()
                for path in installed.content_dir.rglob("*")
                if path.is_file() and path.name != CHECKSUMS_PATH
            }
            if actual_files != set(expected):
                return False, "能力包文件集合与校验清单不一致"
            for relative, expected_hash in expected.items():
                path = installed.content_dir / Path(relative)
                if hashlib.sha256(path.read_bytes()).hexdigest().lower() != str(expected_hash).lower():
                    return False, f"能力包文件校验失败: {relative}"
            return True, ""
        except Exception as exc:
            return False, f"能力包验证失败: {exc}"

    @staticmethod
    def _remove_runtime_bytecode(content_dir: Path, expected: set[str]) -> None:
        """Remove Python bytecode derived after installation, never package files."""
        cache_directories: set[Path] = set()
        for path in content_dir.rglob("*.pyc"):
            relative = path.relative_to(content_dir).as_posix()
            if "__pycache__" not in path.relative_to(content_dir).parts or relative in expected:
                continue
            path.unlink()
            cache_directories.add(path.parent)
        for directory in sorted(cache_directories, key=lambda item: len(item.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass

    def _scan_installed(self) -> Iterator[InstalledPackage]:
        if not self.installed_dir.is_dir():
            return
        for package_root in sorted(self.installed_dir.iterdir()):
            if not package_root.is_dir():
                continue
            for version_root in sorted(package_root.iterdir()):
                installed = self._read_record(version_root)
                if installed is not None:
                    yield installed

    @staticmethod
    def _read_record(package_dir: Path) -> InstalledPackage | None:
        try:
            raw = json.loads((package_dir / "package.json").read_text(encoding="utf-8"))
            manifest = raw["manifest"]
            identity = manifest["package"]
            return InstalledPackage(
                package_id=str(identity["id"]),
                name=str(identity["name"]),
                version=str(identity["version"]),
                sha256=str(raw["sha256"]),
                publisher=str(identity.get("publisher") or ""),
                description=str(identity.get("description") or ""),
                installed_at=float(raw.get("installed_at") or 0),
                package_dir=package_dir,
                manifest=dict(manifest),
            )
        except Exception:
            return None

    def _validate_installable_manifest(self, manifest: dict[str, Any]) -> None:
        requirements = manifest.get("requirements") or {}
        external = [
            *(requirements.get("python_packages") or []),
            *(requirements.get("node_packages") or []),
            *(requirements.get("executables") or []),
        ]
        if external:
            raise CapabilityPackageError(
                "D2 不会自动安装外部依赖，请使用不依赖额外环境的能力包"
            )
        contents = manifest.get("contents") or {}
        unknown = sorted(set(contents) - RUNTIME_CONTENT_KINDS)
        if unknown:
            raise CapabilityPackageError(f"D2 不支持内容分类: {', '.join(unknown)}")
        if not contents.get("capabilities"):
            raise CapabilityPackageError("可安装能力包必须包含 capabilities 能力清单")
        for kind, paths in contents.items():
            for value in paths:
                if not str(value).startswith(f"{kind}/"):
                    raise CapabilityPackageError(f"{kind} 内容必须位于 {kind}/ 目录")

    @staticmethod
    def _extract_validated(data: bytes, target: Path) -> None:
        from io import BytesIO

        with zipfile.ZipFile(BytesIO(data)) as archive:
            for entry in archive.infolist():
                destination = target / Path(entry.filename)
                if entry.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)

    @staticmethod
    def _validate_runtime_catalog(manifest: dict[str, Any], content_dir: Path) -> None:
        declared = {str(item["id"]) for item in manifest.get("capabilities") or []}
        loaded = {
            CapabilityManifestLoader.load_file(path).id
            for path in sorted((content_dir / "capabilities").glob("*.yaml"))
        }
        if loaded != declared:
            raise CapabilityPackageError(
                "capability.yaml 声明的能力与 capabilities/ 清单不一致"
            )
        builtin = {definition.id for definition in CapabilityManifestLoader().load()}
        collisions = sorted(loaded & builtin)
        if collisions:
            raise CapabilityPackageError(
                f"外部能力包不能覆盖内置能力: {', '.join(collisions)}"
            )

        process_root = content_dir / "processes"
        if process_root.is_dir():
            from xiaomei_brain.processes import ProcessTemplateRegistry
            ProcessTemplateRegistry([process_root])

    def _validate_activation_collisions(
        self,
        candidate: InstalledPackage,
        lock: dict[str, Any],
    ) -> None:
        candidate_caps = self._package_capability_ids(candidate)
        candidate_plugins = self._package_plugin_ids(candidate)
        candidate_skills = self._package_skill_names(candidate)
        candidate_processes = self._package_process_ids(candidate)
        for package_id, entry in (lock.get("packages") or {}).items():
            if package_id == candidate.package_id or not isinstance(entry, dict) or entry.get("enabled") is not True:
                continue
            other = self.get_installed(package_id, str(entry.get("version") or ""))
            if other is None:
                continue
            conflicts = [
                ("能力", candidate_caps & self._package_capability_ids(other)),
                ("插件", candidate_plugins & self._package_plugin_ids(other)),
                ("Skill", candidate_skills & self._package_skill_names(other)),
                ("Process", candidate_processes & self._package_process_ids(other)),
            ]
            for label, values in conflicts:
                if values:
                    raise CapabilityPackageError(
                        f"能力包与已激活包 {other.name} 存在重复{label}: {', '.join(sorted(values))}"
                    )

        protected_skills = self._protected_skill_names()
        skill_collisions = sorted(candidate_skills & protected_skills)
        if skill_collisions:
            raise CapabilityPackageError(
                f"能力包不能覆盖 Agent 或内置 Skill: {', '.join(skill_collisions)}"
            )
        builtin_plugins = self._builtin_plugin_ids()
        plugin_collisions = sorted(candidate_plugins & builtin_plugins)
        if plugin_collisions:
            raise CapabilityPackageError(
                f"能力包不能覆盖内置插件: {', '.join(plugin_collisions)}"
            )

    @staticmethod
    def _package_capability_ids(installed: InstalledPackage) -> set[str]:
        return {str(item.get("id") or "") for item in installed.manifest.get("capabilities") or []}

    @staticmethod
    def _package_plugin_ids(installed: InstalledPackage) -> set[str]:
        from xiaomei_brain.plugin.manifest import PluginManifest

        result: set[str] = set()
        root = installed.content_dir / "plugins"
        if root.is_dir():
            for path in root.glob("*/plugin.yaml"):
                manifest = PluginManifest.from_yaml(path)
                if manifest is not None:
                    result.add(manifest.name)
        return result

    @staticmethod
    def _read_skill_name(path: Path) -> str:
        try:
            text = path.read_text(encoding="utf-8")
            if text.startswith("---"):
                end = text.find("\n---", 3)
                if end >= 0:
                    frontmatter = yaml.safe_load(text[3:end]) or {}
                    if isinstance(frontmatter, dict) and frontmatter.get("name"):
                        return str(frontmatter["name"]).strip()
        except Exception:
            pass
        return path.parent.name

    def _package_skill_names(self, installed: InstalledPackage) -> set[str]:
        root = installed.content_dir / "skills"
        return {
            self._read_skill_name(path)
            for path in root.rglob("SKILL.md")
        } if root.is_dir() else set()

    @staticmethod
    def _package_process_ids(installed: InstalledPackage) -> set[str]:
        from xiaomei_brain.processes import ProcessTemplateRegistry

        root = installed.content_dir / "processes"
        if not root.is_dir():
            return set()
        return {item.id for item in ProcessTemplateRegistry([root]).list()}

    def _protected_skill_names(self) -> set[str]:
        import xiaomei_brain.plugins as builtin_plugins

        roots = [
            self.base_dir / self.agent_id / "skills",
            Path(builtin_plugins.__file__).resolve().parent,
            *self._protected_skill_directories,
        ]
        result: set[str] = set()
        for root in roots:
            if root.is_dir():
                result.update(self._read_skill_name(path) for path in root.rglob("SKILL.md"))
        return result

    @staticmethod
    def _builtin_plugin_ids() -> set[str]:
        import xiaomei_brain.plugins as builtin_plugins
        from xiaomei_brain.plugin.manifest import PluginManifest

        result: set[str] = set()
        root = Path(builtin_plugins.__file__).resolve().parent
        for path in root.rglob("plugin.yaml"):
            manifest = PluginManifest.from_yaml(path)
            if manifest is not None:
                result.add(manifest.name)
        return result

    def _read_activation_lock(self) -> dict[str, Any]:
        if not self.lock_path.is_file():
            return {"schema_version": 1, "packages": {}, "hidden_skills": []}
        try:
            raw = json.loads(self.lock_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise CapabilityPackageError(f"Agent capabilities.lock 无法读取: {exc}") from exc
        if not isinstance(raw, dict) or raw.get("schema_version") != 1:
            raise CapabilityPackageError("Agent capabilities.lock 格式无效")
        if not isinstance(raw.get("packages", {}), dict):
            raise CapabilityPackageError("Agent capabilities.lock packages 必须是对象")
        raw.setdefault("packages", {})
        if not isinstance(raw.get("hidden_skills", []), list):
            raise CapabilityPackageError("Agent capabilities.lock hidden_skills 必须是列表")
        raw.setdefault("hidden_skills", [])
        return raw

    def _write_cache(self, data: bytes, sha256: str) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        target = self.cache_dir / f"{sha256}.xmcap"
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != sha256:
                raise CapabilityPackageError("共享缓存中的能力包校验失败")
            return
        handle, temporary = tempfile.mkstemp(prefix=f".{sha256}.", suffix=".tmp", dir=self.cache_dir)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    @staticmethod
    def _write_json(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
