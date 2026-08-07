"""Person-scoped setup and execution support for the Feishu Office capability."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from xiaomei_brain.capabilities.runtime import CapabilityRuntimeState
from xiaomei_brain.channels.configuration import ChannelConfigurationService


_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_FOREIGN_AGENT_ENV = (
    "HERMES_HOME",
    "OPENCLAW_HOME",
    "OPENCLAW_CONFIG_PATH",
    "OPENCLAW_STATE_DIR",
    "OPENCLAW_SERVICE_MARKER",
    "LARK_CHANNEL",
    "LARK_CHANNEL_CONFIG",
)
_LARK_CLI_VERSION = "1.0.84"
_LARK_SKILLS = (
    "lark-shared",
    "lark-im",
    "lark-calendar",
    "lark-doc",
    "lark-drive",
    "lark-sheets",
    "lark-base",
    "lark-task",
    "lark-approval",
    "lark-wiki",
    "lark-mail",
    "lark-vc",
    "lark-okr",
)


@dataclass
class _SetupJob:
    id: str
    action: str
    person_id: str
    state: str = "running"
    output: str = ""
    error: str = ""
    urls: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    process: subprocess.Popen[str] | None = field(default=None, repr=False)
    cancel_requested: bool = field(default=False, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "state": self.state,
            "output": self.output[-12_000:],
            "error": self.error,
            "urls": list(self.urls),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class FeishuOfficeRuntime:
    """Manage the official lark-cli without turning it into an Agent Tool.

    The executable is shared by the host. Configuration and OAuth state are
    isolated under the current Agent and verified Person. Normal Agent shell
    calls receive the same directory through the execution environment.
    """

    capability_id = "feishu_office"
    _ACTIONS = frozenset({"install", "configure", "authorize", "disconnect"})

    def __init__(
        self,
        agent_dir: str | Path,
        *,
        skill_loader: Any = None,
        execution_environment: Any = None,
        app_config: dict[str, Any] | None = None,
    ) -> None:
        self.agent_dir = Path(agent_dir).resolve()
        self.workspace = self.agent_dir / "workspace"
        self.skill_loader = skill_loader
        self.app_config = dict(app_config or {})
        self.execution_backend = str(
            getattr(execution_environment, "backend", "protected_host")
        )
        self._jobs: dict[str, _SetupJob] = {}
        self._latest_job: dict[str, str] = {}
        self._lock = threading.RLock()
        # All profiles share one lark-cli configuration file. Configuration
        # and OAuth mutations are serialized, while normal API calls remain
        # free to run concurrently in separate CLI processes.
        self._configuration_lock = threading.Lock()
        self._status_cache: dict[str, tuple[float, CapabilityRuntimeState]] = {}
        register_provider = getattr(
            execution_environment,
            "register_environment_provider",
            None,
        )
        if callable(register_provider):
            register_provider(self._extend_tool_environment)

    def config_dir(self, _person_id: str = "") -> Path:
        """Return this Agent's shared lark-cli configuration directory."""
        return self.agent_dir / "integrations" / "feishu" / "lark-cli"

    @staticmethod
    def profile_name(person_id: str) -> str:
        """Derive a stable, non-ambiguous lark-cli profile for one Person."""
        normalized = str(person_id or "").strip()
        if not normalized:
            return "person-unidentified"
        readable = re.sub(r"[^A-Za-z0-9_.-]", "-", normalized).strip("-._")
        readable = readable[:36] or "person"
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:10]
        return f"person-{readable}-{digest}"

    def environment(self, person_id: str) -> dict[str, str]:
        root = self.config_dir(person_id)
        root.mkdir(parents=True, exist_ok=True)
        return {
            "LARKSUITE_CLI_CONFIG_DIR": str(root),
            "LARKSUITE_CLI_PROFILE": self.profile_name(person_id),
        }

    def _extend_tool_environment(
        self,
        environment: dict[str, str],
        _cwd: str,
        _command: str,
    ) -> None:
        """Bind arbitrary shell calls to the verified Person's profile."""
        from xiaomei_brain.tools.execution_context import current_tool_execution

        context = current_tool_execution()
        if context is None or not context.person_id:
            return
        self._remove_foreign_agent_context(environment)
        environment.update(self.environment(context.person_id))
        executable = self.executable()
        if not executable:
            return
        path_key = next((key for key in environment if key.lower() == "path"), "PATH")
        cli_dir = str(Path(executable).parent)
        entries = environment.get(path_key, "").split(os.pathsep)
        if not any(os.path.normcase(item) == os.path.normcase(cli_dir) for item in entries):
            environment[path_key] = os.pathsep.join([cli_dir, *entries])

    @staticmethod
    def executable() -> str | None:
        bundled = os.environ.get("XIAOMEI_BRAIN_LARK_CLI", "").strip()
        if bundled and Path(bundled).is_file():
            return str(Path(bundled).resolve())
        names = ("lark-cli.exe", "lark-cli.cmd", "lark-cli") if os.name == "nt" else ("lark-cli",)
        resolved = next((value for name in names if (value := shutil.which(name))), None)
        if resolved:
            return resolved
        home = Path.home()
        candidates = [home / ".local" / "bin" / name for name in names]
        if os.name == "nt":
            app_data = Path(os.environ.get("APPDATA", home / "AppData/Roaming"))
            candidates.extend(app_data / "npm" / name for name in names)
        else:
            candidates.extend(Path("/usr/local/bin") / name for name in names)
        # Source checkouts may start the Agent directly instead of through
        # Desktop, so also discover the Desktop development dependency.
        package_root = Path(__file__).resolve().parents[3]
        desktop_bin = package_root / "desktop" / "node_modules" / "@larksuite" / "cli" / "bin"
        candidates.extend(desktop_bin / name for name in names)
        return next((str(path) for path in candidates if path.is_file()), None)

    @staticmethod
    def _remove_foreign_agent_context(environment: dict[str, str]) -> None:
        """Prevent other installed Agents from capturing this CLI invocation."""
        for name in _FOREIGN_AGENT_ENV:
            environment.pop(name, None)

    def inspect(self, person_id: str = "") -> CapabilityRuntimeState:
        cache_key = person_id or "__anonymous__"
        cached = self._status_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < 3:
            return cached[1]

        executable = self.executable()
        skill_names = self._skill_names()
        lark_skills = sorted(name for name in skill_names if name.startswith("lark-"))
        details: dict[str, Any] = {
            "executable_installed": bool(executable),
            "executable": executable or "",
            "skills_installed": "lark-shared" in skill_names,
            "skill_count": len(lark_skills),
            "authenticated": False,
            "person_scoped": True,
            "profile": self.profile_name(person_id) if person_id else "",
            "execution_backend": self.execution_backend,
        }
        if self.execution_backend != "protected_host":
            state = CapabilityRuntimeState(
                False,
                "runtime_unavailable",
                "当前执行环境尚未接入飞书办公运行组件",
                details,
                (),
            )
        elif not executable:
            state = CapabilityRuntimeState(
                False,
                "runtime_missing",
                "飞书办公运行组件尚未安装",
                details,
                ("install",),
            )
        elif "lark-shared" not in skill_names:
            state = CapabilityRuntimeState(
                False,
                "skill_missing",
                "飞书官方 Skill 尚未安装",
                details,
                ("install",),
            )
        elif not person_id:
            state = CapabilityRuntimeState(
                False,
                "identity_required",
                "需要先确认当前人物身份",
                details,
                (),
            )
        else:
            auth = self._auth_status(executable, person_id)
            details.update(auth)
            if auth.get("authenticated"):
                actions = ("disconnect",)
                state = CapabilityRuntimeState(True, "ready", "飞书账户已连接", details, actions)
            elif auth.get("configured"):
                state = CapabilityRuntimeState(
                    False,
                    "authorization_required",
                    "当前人物尚未授权飞书账户",
                    details,
                    ("authorize",),
                )
            else:
                state = CapabilityRuntimeState(
                    False,
                    "configuration_required",
                    "需要配置飞书应用并完成账户授权",
                    details,
                    ("configure",),
                )
        self._status_cache[cache_key] = (time.monotonic(), state)
        return state

    def start(self, action: str, person_id: str) -> dict[str, Any]:
        normalized = str(action or "").strip().lower()
        if normalized not in self._ACTIONS:
            raise ValueError(f"不支持的飞书能力操作: {normalized}")
        if self.execution_backend != "protected_host":
            raise RuntimeError("当前执行环境尚未接入飞书办公运行组件")
        if normalized != "install" and not person_id:
            raise ValueError("当前连接没有经过验证的人物身份")
        with self._lock:
            if normalized == "install":
                previous = next(
                    (item for item in self._jobs.values() if item.action == "install" and item.state == "running"),
                    None,
                )
            else:
                previous_id = self._latest_job.get(person_id)
                previous = self._jobs.get(previous_id or "")
            if previous and previous.state == "running":
                raise RuntimeError("已有飞书配置操作正在进行")
            job = _SetupJob(uuid.uuid4().hex, normalized, person_id)
            self._jobs[job.id] = job
            self._latest_job[person_id] = job.id
        threading.Thread(target=self._run_job, args=(job,), daemon=True).start()
        return job.to_dict()

    def job_status(self, person_id: str, job_id: str = "") -> dict[str, Any] | None:
        with self._lock:
            selected = job_id or self._latest_job.get(person_id, "")
            job = self._jobs.get(selected)
            if job is None or job.person_id != person_id:
                return None
            return job.to_dict()

    def cancel(self, person_id: str, job_id: str = "") -> dict[str, Any] | None:
        with self._lock:
            selected = job_id or self._latest_job.get(person_id, "")
            job = self._jobs.get(selected)
            if job is None or job.person_id != person_id:
                return None
            process = job.process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
        with self._lock:
            job.cancel_requested = True
        return job.to_dict()

    def _run_job(self, job: _SetupJob) -> None:
        mutation_locked = False
        try:
            if job.action == "install":
                self._install_components(job)
                with self._lock:
                    job.state = "cancelled" if job.cancel_requested else "completed"
                    job.completed_at = time.time()
                return
            self._configuration_lock.acquire()
            mutation_locked = True
            command = self._command(job.action, job.person_id)
            env = os.environ.copy()
            self._remove_foreign_agent_context(env)
            if job.action != "install":
                env.update(self.environment(job.person_id))
            if job.action == "configure":
                # The profile does not exist yet; config init creates it by
                # name, so an active-profile override would be premature.
                env.pop("LARKSUITE_CLI_PROFILE", None)
            self.workspace.mkdir(parents=True, exist_ok=True)
            kwargs: dict[str, Any] = {
                "cwd": str(self.workspace),
                "env": env,
                "stdin": subprocess.PIPE if self._command_stdin(job.action) else subprocess.DEVNULL,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
            }
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                kwargs["start_new_session"] = True
            process = subprocess.Popen(command, **kwargs)
            with self._lock:
                job.process = process
            command_stdin = self._command_stdin(job.action)
            if command_stdin and process.stdin is not None:
                process.stdin.write(command_stdin)
                process.stdin.close()
            assert process.stdout is not None
            for line in iter(process.stdout.readline, ""):
                with self._lock:
                    job.output = (job.output + line)[-20_000:]
                    for url in _URL_RE.findall(line):
                        cleaned = url.rstrip(".,;)]}")
                        if cleaned not in job.urls:
                            job.urls.append(cleaned)
            return_code = process.wait()
            with self._lock:
                if job.cancel_requested:
                    job.state = "cancelled"
                else:
                    job.state = "completed" if return_code == 0 else "failed"
                if return_code != 0 and not job.cancel_requested:
                    job.error = f"操作退出码为 {return_code}"
                job.completed_at = time.time()
        except Exception as exc:
            with self._lock:
                job.state = "failed"
                job.error = str(exc)
                job.completed_at = time.time()
        finally:
            if mutation_locked:
                self._configuration_lock.release()
            self._status_cache.clear()
            if self.skill_loader is not None:
                try:
                    self.skill_loader.refresh_if_changed()
                except Exception:
                    pass

    def _command(self, action: str, person_id: str) -> list[str]:
        executable = self.executable()
        if not executable:
            raise RuntimeError("飞书办公运行组件尚未安装")
        profile = self.profile_name(person_id)
        if action == "configure":
            app_id = str(self.app_config.get("appId") or self.app_config.get("app_id") or "").strip()
            app_secret = str(
                self.app_config.get("appSecret")
                or self.app_config.get("app_secret")
                or ""
            ).strip()
            if app_id and app_secret:
                return [
                    executable,
                    "config",
                    "init",
                    "--name",
                    profile,
                    "--app-id",
                    app_id,
                    "--app-secret-stdin",
                ]
            return [executable, "config", "init", "--new", "--name", profile]
        if action == "authorize":
            return [executable, "--profile", profile, "auth", "login", "--recommend"]
        return [executable, "--profile", profile, "auth", "logout"]

    def _command_stdin(self, action: str) -> str:
        if action != "configure":
            return ""
        secret = str(
            self.app_config.get("appSecret")
            or self.app_config.get("app_secret")
            or ""
        ).strip()
        return f"{secret}\n" if secret else ""

    def _install_components(self, job: _SetupJob) -> None:
        """Install official Feishu Skills into this Agent.

        Desktop distributions carry the official executable. Source and CLI
        users may instead provide it through PATH or
        ``XIAOMEI_BRAIN_LARK_CLI``. Skills stay Agent-local so installing this
        capability for one Agent does not silently change every Agent.
        """
        if not self.executable():
            raise RuntimeError(
                "未找到飞书办公运行组件；请使用包含飞书组件的 Desktop，"
                "或先在系统中安装官方 lark-cli"
            )

        from xiaomei_brain.skills.sources.github import GitHubSourceAdapter

        destination_root = self.agent_dir / "skills"
        destination_root.mkdir(parents=True, exist_ok=True)
        adapter = GitHubSourceAdapter()
        for index, skill_name in enumerate(_LARK_SKILLS, start=1):
            if job.cancel_requested:
                return
            self._append_output(job, f"[{index}/{len(_LARK_SKILLS)}] 正在安装 {skill_name}…\n")
            identifier = f"larksuite/cli/skills/{skill_name}:v{_LARK_CLI_VERSION}"
            bundle = adapter.fetch(identifier)
            self._write_skill_bundle(destination_root, skill_name, bundle)
        if self.skill_loader is not None:
            self.skill_loader.scan()
        self._append_output(job, "飞书官方 Skills 安装完成。\n")

    @staticmethod
    def _write_skill_bundle(destination_root: Path, skill_name: str, bundle: Any) -> None:
        """Atomically replace one capability-owned Skill directory."""
        destination = destination_root / skill_name
        staging = destination_root / f".{skill_name}.install-{uuid.uuid4().hex}"
        staging.mkdir(parents=True, exist_ok=False)
        try:
            (staging / "SKILL.md").write_text(bundle.content, encoding="utf-8")
            for relative_name, content in bundle.files.items():
                relative = Path(relative_name)
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError(f"Skill 包含不安全路径: {relative_name}")
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(content, bytes):
                    target.write_bytes(content)
                else:
                    target.write_text(content, encoding="utf-8")
            if destination.exists():
                shutil.rmtree(destination)
            staging.replace(destination)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

    def _append_output(self, job: _SetupJob, value: str) -> None:
        with self._lock:
            job.output = (job.output + value)[-20_000:]

    def _auth_status(self, executable: str, person_id: str) -> dict[str, Any]:
        config_root = self.config_dir(person_id)
        configured = False
        env = os.environ.copy()
        self._remove_foreign_agent_context(env)
        env.update(self.environment(person_id))
        kwargs: dict[str, Any] = {
            "cwd": str(self.workspace),
            "env": env,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "timeout": 8,
            "check": False,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            completed = subprocess.run(
                [
                    executable,
                    "--profile",
                    self.profile_name(person_id),
                    "auth",
                    "status",
                    "--json",
                ],
                **kwargs,
            )
            output = completed.stdout.decode("utf-8", errors="replace").strip()
        except (OSError, subprocess.SubprocessError) as exc:
            return {"configured": configured, "auth_error": str(exc)}
        payload = self._parse_json(output)
        error = payload.get("error") if isinstance(payload, dict) else None
        subtype = str(error.get("subtype", "")) if isinstance(error, dict) else ""
        configured = bool(payload) and subtype not in {"not_configured", "profile_not_found"}
        identities = payload.get("identities") if isinstance(payload, dict) else None
        identities = identities if isinstance(identities, dict) else {}
        user_identity = identities.get("user")
        user_identity = user_identity if isinstance(user_identity, dict) else {}
        explicit_authenticated = payload.get("authenticated") if isinstance(payload, dict) else None
        identity_present = any(
            payload.get(key) not in (None, "")
            for key in ("user_id", "open_id", "email", "name")
        ) if isinstance(payload, dict) else False
        nested_user_ready = (
            user_identity.get("available") is True
            or str(user_identity.get("status") or "").lower() == "ready"
            or str(user_identity.get("tokenStatus") or "").lower() == "valid"
        )
        authenticated = completed.returncode == 0 and (
            explicit_authenticated is True
            or nested_user_ready
            or (explicit_authenticated is None and identity_present)
        )
        result: dict[str, Any] = {
            "configured": configured or authenticated,
            "authenticated": authenticated,
            "profile": self.profile_name(person_id),
        }
        if isinstance(payload, dict):
            for key in ("name", "email", "user_id", "tenant_name", "profile"):
                value = payload.get(key)
                if value not in (None, ""):
                    result[key] = value
            scopes = payload.get("scopes") or payload.get("granted_scopes")
            if isinstance(scopes, list):
                result["scopes"] = [str(item) for item in scopes]
        if user_identity:
            nested_fields = {
                "userName": "name",
                "openId": "user_id",
                "email": "email",
                "expiresAt": "expires_at",
            }
            for source_key, target_key in nested_fields.items():
                value = user_identity.get(source_key)
                if value not in (None, ""):
                    result[target_key] = value
            nested_scopes = user_identity.get("scope")
            if isinstance(nested_scopes, str) and nested_scopes.strip():
                result["scopes"] = nested_scopes.split()
        if output and not authenticated:
            result["auth_error"] = output[-1000:]
        return result

    @staticmethod
    def _parse_json(output: str) -> dict[str, Any]:
        candidates = [output, *re.findall(r"\{.*\}", output, flags=re.DOTALL)]
        for candidate in candidates:
            try:
                value = json.loads(candidate)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                data = value.get("data")
                return data if isinstance(data, dict) else value
        return {}

    def _skill_names(self) -> set[str]:
        if self.skill_loader is None:
            return set()
        try:
            return set(self.skill_loader.list_names())
        except Exception:
            return set()


def create_runtime(
    *,
    capability_id: str,
    agent_dir: str | Path,
    skill_loader: Any = None,
    execution_environment: Any = None,
) -> FeishuOfficeRuntime:
    """Create this capability runtime from generic platform dependencies."""

    if capability_id != FeishuOfficeRuntime.capability_id:
        raise ValueError(f"Unexpected capability id: {capability_id}")
    resolved_agent_dir = Path(agent_dir).resolve()
    # Reusing the channel application is optional convenience only. The
    # office capability owns its account authorization and CLI state.
    app_config = ChannelConfigurationService(
        resolved_agent_dir.name,
        base_dir=resolved_agent_dir.parent,
    ).raw_account("feishu")
    return FeishuOfficeRuntime(
        resolved_agent_dir,
        skill_loader=skill_loader,
        execution_environment=execution_environment,
        app_config=app_config,
    )
