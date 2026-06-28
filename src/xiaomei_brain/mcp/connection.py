"""MCP Connection — 管理单个 MCP Server 的连接生命周期。

- stdio / HTTP / SSE 传输
- 工具发现
- 工具调用
- keepalive 保活 + 健康检查（连续失败触发重连）
- 工具调用审计日志（JSONL）
- 工具参数 Schema 校验（调前验参）
- 凭证脱敏
- 子进程追踪与清理
- 环境变量过滤（安全）
- URL 校验
- stdio stderr 重定向
- 命令解析（npx/node/npm PATH fallback）
- mTLS 客户端证书
- 工具描述注入扫描
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import threading
import time
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_DEFAULT_TOOL_TIMEOUT = 120.0
_DEFAULT_CONNECT_TIMEOUT = 30.0
_KEEPALIVE_INTERVAL = 180.0
_KEEPALIVE_TIMEOUT = 30.0
_KEEPALIVE_MAX_FAILURES = 3

# ── 凭证脱敏 ─────────────────────────────────────────────────────────

# 匹配常见的 API key / token 模式
_CREDENTIAL_PATTERNS = [
    # Bearer tokens
    (re.compile(r"(?:Bearer|bearer)\s+([A-Za-z0-9._\-+=]+)"), "Bearer <redacted>"),
    # GitHub PAT: ghp_..., github_pat_...
    (re.compile(r"(ghp_[A-Za-z0-9]{36,})"), "<redacted-github-pat>"),
    (re.compile(r"(github_pat_[A-Za-z0-9_]{20,})"), "<redacted-github-pat>"),
    # OpenAI/API keys: sk-...
    (re.compile(r"(sk-[A-Za-z0-9]{20,})"), "<redacted-api-key>"),
    # Generic key=value patterns
    (re.compile(r"(?:api_key|apikey|api-key|token|secret|password)\s*[:=]\s*([^\s,}]+)", re.IGNORECASE),
     r"\1=<redacted>"),
    # URL credentials: https://user:pass@host
    (re.compile(r"://[^:]+:[^@]+@"), "://<redacted>:<redacted>@"),
]


def _sanitize_error(text: str) -> str:
    """从错误信息中移除凭证。"""
    for pattern, replacement in _CREDENTIAL_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _str_exc(exc: BaseException) -> str:
    """安全获取异常字符串，限制长度并脱敏。"""
    text = str(exc)
    if len(text) > 2000:
        text = text[:2000] + "..."
    return _sanitize_error(text)


# ── 环境变量过滤 ─────────────────────────────────────────────────────

# 白名单：允许从父进程传递给 stdio 子进程的环境变量
_SAFE_ENV_KEYS = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL",
    "LC_CTYPE", "TMPDIR", "TMP", "TEMP", "TERM", "COLORTERM",
    "DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS",
    "SYSTEMD_EXEC_PID", "JOURNAL_STREAM", "INVOCATION_ID",
    "NVM_DIR", "NODE_PATH", "PYTHONPATH", "VIRTUAL_ENV",
    "CONDA_PREFIX", "HOMEBREW_PREFIX", "SSL_CERT_FILE", "CURL_CA_BUNDLE",
    "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS",
})

# 大小写不敏感的键（Windows 兼容）
_SAFE_ENV_KEYS_CASE_INSENSITIVE = frozenset({
    "systemroot", "windir", "programfiles", "programfiles(x86)",
    "commonprogramfiles", "commonprogramfiles(x86)", "comspec",
    "appdata", "localappdata", "allusersprofile", "userprofile",
})


def _build_safe_env(user_env: dict | None) -> dict:
    """构建过滤后的环境变量，只传安全基线 + 用户显式指定。"""
    env = {}
    for key, value in os.environ.items():
        if (
            key in _SAFE_ENV_KEYS
            or key.upper() in _SAFE_ENV_KEYS_CASE_INSENSITIVE
            or key.startswith("XDG_")
        ):
            env[key] = value
    if user_env:
        env.update(user_env)
    return env


# ── 工具描述注入扫描 ────────────────────────────────────────────────

# Prompt injection 检测模式
_MCP_INJECTION_PATTERNS = [
    (re.compile(r"ignore\s+(all\s+)?(previous|prior|above|foregoing)\s+(instructions?|directives?|prompts?)", re.IGNORECASE),
     "suspicious 'ignore previous instructions' pattern"),
    (re.compile(r"you\s+(are|must|should|shall|will)\s+(now\s+)?(act\s+as|pretend|roleplay|behave)", re.IGNORECASE),
     "suspicious role-instruction pattern"),
    (re.compile(r"disregard\s+(your\s+)?(system\s+)?(prompt|instructions|rules|guidelines)", re.IGNORECASE),
     "suspicious 'disregard system prompt' pattern"),
    (re.compile(r"system\s*(prompt|message|instruction|directive)\s*(:|\n|is|was|has been)", re.IGNORECASE),
     "suspicious system prompt reference"),
]


def _scan_mcp_description(server_name: str, tool_name: str, description: str) -> list[str]:
    """扫描 MCP 工具描述中的 prompt injection 模式。只 warn，不 block。"""
    findings = []
    if not description:
        return findings
    for pattern, reason in _MCP_INJECTION_PATTERNS:
        if pattern.search(description):
            findings.append(reason)
    if findings:
        logger.warning(
            "MCP server '%s' tool '%s': suspicious description — %s. "
            "Description: %.200s",
            server_name, tool_name, "; ".join(findings), description,
        )
    return findings


# ── URL 校验 ─────────────────────────────────────────────────────────


class InvalidMcpUrlError(ValueError):
    """MCP URL 不合法（scheme 非 http/https、host 为空等）。"""


class NonMcpEndpointError(ConnectionError):
    """HTTP URL 返回非 MCP 响应（content-type 不是 application/json 或 text/event-stream）。

    这个错误跳过重连循环，因为每次请求都会返回同样的非 MCP 页面。
    """


# MCP Streamable HTTP / SSE 端点合法的 Content-Type
_MCP_CONTENT_TYPES = ("application/json", "text/event-stream")


def _validate_remote_mcp_url(server_name: str, url: Any) -> str:
    """校验并返回合法的 http(s) MCP URL。不合法的配置 fail-fast。"""
    if not isinstance(url, str):
        raise InvalidMcpUrlError(
            f"Invalid MCP URL for '{server_name}': expected a string, got "
            f"{type(url).__name__}"
        )
    stripped = url.strip()
    if not stripped:
        raise InvalidMcpUrlError(
            f"Invalid MCP URL for '{server_name}': empty url"
        )
    try:
        parsed = urlparse(stripped)
    except Exception as exc:
        raise InvalidMcpUrlError(
            f"Invalid MCP URL for '{server_name}': {stripped!r} ({exc})"
        ) from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise InvalidMcpUrlError(
            f"Invalid MCP URL for '{server_name}': scheme must be http or "
            f"https, got {parsed.scheme!r} ({stripped!r})"
        )
    if not parsed.netloc:
        raise InvalidMcpUrlError(
            f"Invalid MCP URL for '{server_name}': missing host ({stripped!r})"
        )
    if not parsed.hostname:
        raise InvalidMcpUrlError(
            f"Invalid MCP URL for '{server_name}': missing hostname ({stripped!r})"
        )
    return stripped


# ── mTLS 客户端证书 ──────────────────────────────────────────────────


def _resolve_client_cert(server_name: str, config: dict) -> Any:
    """解析 client_cert / client_key 配置，返回 httpx cert= 参数格式。

    支持:
        - (cert_path, key_path) 元组
        - 单个 PEM 文件路径（cert + key 合并）
        - ~ 展开
    """
    raw_cert = config.get("client_cert")
    raw_key = config.get("client_key")

    if raw_cert is None and raw_key is None:
        return None

    def _expand(path: Any, label: str) -> str:
        if not isinstance(path, str):
            raise InvalidMcpUrlError(
                f"Invalid MCP mTLS '{label}' for '{server_name}': expected a string"
            )
        expanded = os.path.expanduser(path)
        if not os.path.isfile(expanded):
            raise FileNotFoundError(
                f"MCP mTLS '{label}' for '{server_name}': file not found: {expanded}"
            )
        return expanded

    if raw_key is not None:
        # 分离的 cert + key
        cert_path = _expand(raw_cert or "", "client_cert")
        key_path = _expand(raw_key, "client_key")
        return (cert_path, key_path)

    if isinstance(raw_cert, (list, tuple)):
        return tuple(_expand(p, "client_cert") for p in raw_cert)

    return _expand(raw_cert, "client_cert")


# ── stderr 重定向 ────────────────────────────────────────────────────

_mcp_stderr_fh: Any = None
_mcp_stderr_lock = threading.Lock()


def _get_mcp_stderr_log() -> Any:
    """获取 MCP 子进程 stderr 共享日志文件句柄。

    stdio MCP Server 的 stderr 默认打到终端，会破坏 CLI 显示。
    重定向到日志文件，fallback 到 /dev/null。
    """
    global _mcp_stderr_fh
    with _mcp_stderr_lock:
        if _mcp_stderr_fh is not None:
            return _mcp_stderr_fh
        try:
            log_dir = os.path.expanduser("~/.xiaomei-brain/logs")
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, "mcp-stderr.log")
            fh = open(log_path, "a", encoding="utf-8", errors="replace", buffering=1)
            fh.fileno()  # 确认是真实 fd
            _mcp_stderr_fh = fh
        except Exception as exc:
            logger.debug("Failed to open MCP stderr log, using devnull: %s", exc)
            try:
                _mcp_stderr_fh = open(os.devnull, "w", encoding="utf-8")
            except Exception:
                import sys
                _mcp_stderr_fh = sys.stderr
        return _mcp_stderr_fh


# ── 审计日志 ─────────────────────────────────────────────────────────

_audit_fh: Any = None
_audit_lock = threading.Lock()


def _get_audit_log() -> Any:
    """获取 MCP 工具调用审计日志文件句柄（JSONL）。"""
    global _audit_fh
    with _audit_lock:
        if _audit_fh is not None:
            return _audit_fh
        try:
            log_dir = os.path.expanduser("~/.xiaomei-brain/logs")
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, "mcp-audit.jsonl")
            fh = open(log_path, "a", encoding="utf-8", errors="replace", buffering=1)
            _audit_fh = fh
        except Exception as exc:
            logger.debug("Failed to open MCP audit log, using devnull: %s", exc)
            try:
                _audit_fh = open(os.devnull, "w", encoding="utf-8")
            except Exception:
                import sys
                _audit_fh = sys.stderr
        return _audit_fh


def _write_audit(entry: dict) -> None:
    """写入一条审计记录。线程安全。"""
    try:
        fh = _get_audit_log()
        line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
        with _audit_lock:
            fh.write(line)
            fh.flush()
    except Exception:
        pass


# ── Schema 校验 ──────────────────────────────────────────────────────

_SCHEMA_TYPE_MAP = {
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _validate_args(tool_name: str, schema: dict, arguments: dict) -> str | None:
    """校验工具参数是否符合 inputSchema。返回错误信息或 None。

    只做轻量基础校验：required 字段存在、基本类型匹配。
    不做深层递归校验，不做 string pattern/number range 等约束。
    """
    properties = schema.get("properties", {})
    required = schema.get("required", [])

    # 1. 检查必填字段
    missing = [k for k in required if k not in arguments]
    if missing:
        return f"Missing required parameters for '{tool_name}': {', '.join(missing)}"

    # 2. 检查类型
    for key, value in arguments.items():
        prop = properties.get(key, {})
        expected_type = prop.get("type")
        if expected_type is None:
            continue  # 无类型声明则跳过

        expected_py_types = _SCHEMA_TYPE_MAP.get(expected_type)
        if expected_py_types is None:
            continue  # 不支持的类型声明

        if value is None:
            continue  # null 通常合法

        if not isinstance(value, expected_py_types):
            return (
                f"Invalid type for parameter '{key}' in '{tool_name}': "
                f"expected {expected_type}, got {type(value).__name__}"
            )

    return None


# ── 命令解析 ─────────────────────────────────────────────────────────


def _prepend_path(env: dict, directory: str) -> dict:
    """如果 PATH 中不存在则添加到最前面。"""
    updated = dict(env or {})
    if not directory:
        return updated
    existing = updated.get("PATH", "")
    parts = [p for p in existing.split(os.pathsep) if p]
    if directory not in parts:
        parts = [directory] + parts
    updated["PATH"] = os.pathsep.join(parts) if parts else directory
    return updated


def _resolve_stdio_command(command: str, env: dict) -> tuple[str, dict]:
    """解析 stdio 命令，处理 npx/npm/node 的 PATH 查找。

    在过滤后的 PATH 中可能找不到这些命令，需要多级 fallback。
    """
    resolved = os.path.expanduser(str(command).strip())
    resolved_env = dict(env or {})

    if os.sep not in resolved:
        path_arg = resolved_env.get("PATH")
        which_hit = shutil.which(resolved, path=path_arg)
        if which_hit:
            resolved = which_hit
        elif resolved in {"npx", "npm", "node"}:
            # 多级 fallback: HERMES_HOME/node/bin → ~/.local/bin → /usr/local/bin
            candidates = [
                os.path.join(os.path.expanduser("~"), ".local", "bin", resolved),
                os.path.join(os.sep, "usr", "local", "bin", resolved),
            ]
            for candidate in candidates:
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    resolved = candidate
                    break

    command_dir = os.path.dirname(resolved)
    if command_dir:
        resolved_env = _prepend_path(resolved_env, command_dir)

    return resolved, resolved_env


# ── 子进程追踪 ───────────────────────────────────────────────────────

# {pid: server_name}
_pids_lock = threading.Lock()
_stdio_pids: dict[int, str] = {}


def _snapshot_child_pids() -> set[int]:
    """获取当前进程的所有子进程 PID。（仅 Linux）"""
    try:
        import psutil
        proc = psutil.Process()
        return {child.pid for child in proc.children(recursive=True)}
    except ImportError:
        return set()


def get_stdio_pids() -> dict[int, str]:
    """返回当前追踪的 stdio 子进程。"""
    with _pids_lock:
        return dict(_stdio_pids)


# ── 401 检测 ────────────────────────────────────────────────────────

_401_PATTERNS = [
    re.compile(r"401", re.IGNORECASE),
    re.compile(r"unauthorized", re.IGNORECASE),
    re.compile(r"unauthenticated", re.IGNORECASE),
    re.compile(r"invalid.*token", re.IGNORECASE),
    re.compile(r"token.*expired", re.IGNORECASE),
]


def _looks_like_401(error_text: str) -> bool:
    """检测错误信息是否像 401/认证失败。"""
    if not error_text:
        return False
    return any(p.search(error_text) for p in _401_PATTERNS)


# ── MCPConnection ────────────────────────────────────────────────────


class MCPConnection:
    """管理单个 MCP Server 的连接生命周期。"""

    def __init__(self, name: str, config: dict):
        self.name = name
        self._config = config
        self._task: asyncio.Task | None = None
        self.session: Any = None
        self._tools: list = []
        self._ready = asyncio.Event()
        self._shutdown_event: asyncio.Event | None = None
        self._rpc_lock: asyncio.Lock | None = None
        self.tool_timeout = config.get("timeout", _DEFAULT_TOOL_TIMEOUT)
        self.supports_parallel = config.get("supports_parallel_tool_calls", False)
        self._pids_before: set[int] = set()
        self._new_pids: set[int] = set()
        self._token_manager: Any = None  # TokenManager | None

    def _is_http(self) -> bool:
        return "url" in self._config

    # ── OAuth 2.0 认证 ──────────────────────────────────────────────

    async def _setup_oauth(self, headers: dict) -> Any:
        """配置 OAuth 2.0 认证，获取初始 token 并注入 headers。

        Returns:
            (TokenManager, updated_headers) 或 (None, headers)
        """
        from .auth import OAuth2Config, TokenManager, MCPAuthDiscovery

        # ── MCP Auth Discovery ─────────────────────────────
        # 如果 auth 配置了但没有 token_url / oidc_discovery_url，
        # 尝试从 MCP Server 的 401 响应自动发现 OAuth 端点
        auth_cfg = self._config.get("auth", {})
        if isinstance(auth_cfg, dict):
            auth_type = auth_cfg.get("type", "").lower()
            if auth_type in ("oauth2", "ema"):
                has_token_url = bool(auth_cfg.get("token_url") or auth_cfg.get("oidc_discovery_url"))
                mcp_url = self._config.get("url", "")
                if not has_token_url and mcp_url:
                    logger.info(
                        "MCP server '%s': no token_url configured, trying auth discovery...",
                        self.name,
                    )
                    try:
                        discovery = MCPAuthDiscovery(mcp_url, server_name=self.name)
                        metadata = await discovery.discover()
                        if metadata.token_endpoint:
                            self._config.setdefault("auth", {})["token_url"] = metadata.token_endpoint
                            logger.info(
                                "MCP server '%s': discovered token_endpoint=%s",
                                self.name, metadata.token_endpoint,
                            )
                        if metadata.authorization_endpoint and not auth_cfg.get("authorization_url"):
                            self._config["auth"]["authorization_url"] = metadata.authorization_endpoint
                    except Exception as e:
                        logger.warning(
                            "MCP server '%s': auth discovery failed: %s", self.name, e,
                        )

        cfg = OAuth2Config.from_server_config(self.name, self._config)
        if cfg is None:
            return None

        logger.info("MCP server '%s': OAuth 2.0 enabled, obtaining token...", self.name)
        try:
            manager = TokenManager(cfg, server_name=self.name)
            await manager.ensure_token()
            new_headers = manager.set_headers(headers)
            logger.info(
                "MCP server '%s': OAuth token obtained (%d chars)", self.name,
                len(new_headers.get("Authorization", "")) - 7,  # "Bearer "
            )
            return manager, new_headers
        except Exception as e:
            logger.error("MCP server '%s': OAuth token failed: %s", self.name, e)
            raise

    # ── 传输层 ──────────────────────────────────────────────────────

    async def _run_stdio(self):
        """stdio 传输 — 启动子进程并通信。"""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        command = self._config["command"]
        args = self._config.get("args", [])
        env_vars = self._config.get("env", {}) or {}

        # 安全：过滤环境变量，防止泄露父进程 secret
        safe_env = _build_safe_env(env_vars if env_vars else None)

        # 解析命令（处理 npx/node/npm PATH fallback）
        command, safe_env = _resolve_stdio_command(command, safe_env)

        # stderr 重定向到日志文件，不污染终端
        errlog = _get_mcp_stderr_log()

        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=safe_env if env_vars else None,
        )

        self._pids_before = _snapshot_child_pids()
        self._new_pids = set()

        try:
            async with stdio_client(server_params, errlog=errlog) as (read, write):
                self._new_pids = _snapshot_child_pids() - self._pids_before
                with _pids_lock:
                    for pid in self._new_pids:
                        _stdio_pids[pid] = self.name
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self.session = session
                    await self._discover_tools()
                    self._ready.set()
                    await self._wait_shutdown()
        finally:
            self._cleanup_stdio_pids()

    async def _preflight_content_type(
        self, url: str, *,
        headers: dict | None = None,
        ssl_verify: bool = True,
        client_cert: Any = None,
        timeout: float = 5.0,
    ) -> None:
        """探测 URL 返回的 Content-Type 是否为 MCP 端点。

        Streamable HTTP MCP 端点应返回 application/json 或 text/event-stream。
        如果返回 HTML 或其他类型，说明 URL 指向的是普通网页而非 MCP 端点，
        直接 raise NonMcpEndpointError 跳过重连循环。

        只在 2xx 且 Content-Type 明确非 MCP 时拒绝。4xx/5xx、空 Content-Type、
        网络错误等都放行 — 预检只是 best-effort，真正的 MCP 握手才是权威。
        """
        try:
            import httpx as _httpx
        except ImportError:
            return

        client_kwargs: dict = {
            "verify": ssl_verify,
            "follow_redirects": True,
            "timeout": _httpx.Timeout(timeout),
        }
        if client_cert is not None:
            client_kwargs["cert"] = client_cert

        probe_headers = dict(headers) if headers else {}
        try:
            async with _httpx.AsyncClient(**client_kwargs) as client:
                # HEAD 最省流量；不支持时 fallback GET
                resp = await client.head(url, headers=probe_headers)
                if resp.status_code in (405, 501):
                    resp = await client.get(url, headers=probe_headers)
        except _httpx.HTTPError:
            return  # DNS/连接/超时错误 — 交给 SDK 处理

        # 只评判成功的响应。4xx/5xx 可能是 auth challenge 或临时错误
        if not (200 <= resp.status_code < 300):
            return

        ct_base = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        if not ct_base:
            return  # 没有 Content-Type — 不替 SDK 做判断
        if ct_base in _MCP_CONTENT_TYPES:
            return  # 确认是 MCP 端点

        raise NonMcpEndpointError(
            f"MCP server '{self.name}' at {url} returned Content-Type "
            f"'{ct_base}', not an MCP response (expected one of: "
            f"{', '.join(_MCP_CONTENT_TYPES)}). The URL most likely "
            "points at a web page rather than an MCP endpoint — check it "
            "resolves to a Streamable HTTP / SSE endpoint "
            "(e.g. https://host/mcp, not https://host/)."
        )

    async def _run_http(self):
        """HTTP/Streamable HTTP / SSE 传输。"""
        # URL 合法性校验（fail-fast）
        url = _validate_remote_mcp_url(self.name, self._config["url"])
        headers = dict(self._config.get("headers", {}))
        connect_timeout = self._config.get("connect_timeout", _DEFAULT_CONNECT_TIMEOUT)
        ssl_verify = self._config.get("ssl_verify", True)
        transport = self._config.get("transport", "http")

        # OAuth 2.0 认证
        oauth_result = await self._setup_oauth(headers)
        if oauth_result is not None:
            self._token_manager, headers = oauth_result

        # 预检：Streamable HTTP 首次连接前探测 Content-Type，防止把网页当 MCP
        # SSE 跳过 — 它的 text/event-stream 由自己的 client 处理
        # 重连跳过 — 首次已验证过，不需要重复探测
        if transport != "sse" and not self._ready.is_set():
            probe_headers = dict(headers) if headers else {}
            client_cert = _resolve_client_cert(self.name, self._config)
            await self._preflight_content_type(
                url, headers=probe_headers, ssl_verify=ssl_verify,
                client_cert=client_cert,
            )

        if transport == "sse":
            await self._run_sse(url, headers, connect_timeout)
        else:
            await self._run_streamable_http(url, headers, connect_timeout, ssl_verify)

    async def _run_sse(self, url: str, headers: dict, connect_timeout: float):
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        async with sse_client(
            url=url, headers=headers if headers else None,
            timeout=connect_timeout, sse_read_timeout=self.tool_timeout,
        ) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                self.session = session
                await self._discover_tools()
                self._ready.set()
                await self._wait_shutdown()

    async def _run_streamable_http(
        self, url: str, headers: dict, connect_timeout: float, ssl_verify: bool,
    ):
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        import httpx

        # 解析 mTLS 客户端证书
        client_cert = _resolve_client_cert(self.name, self._config)

        async with httpx.AsyncClient(
            verify=ssl_verify, follow_redirects=True,
            timeout=httpx.Timeout(connect_timeout, read=self.tool_timeout),
            cert=client_cert,
        ) as http_client:
            async with streamable_http_client(
                url, http_client=http_client, headers=headers if headers else None,
            ) as (read, write, _get_session_id):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self.session = session
                    await self._discover_tools()
                    self._ready.set()
                    await self._wait_shutdown()

    # ── 工具发现 ────────────────────────────────────────────────────

    async def _discover_tools(self):
        """发现服务器提供的工具，并扫描描述中的注入模式。"""
        if self.session is None:
            return
        try:
            async with self._rpc_lock:
                tools_result = await self.session.list_tools()
            self._tools = getattr(tools_result, "tools", []) or []
            logger.info(
                "MCP server '%s': discovered %d tool(s): %s",
                self.name, len(self._tools),
                ", ".join(t.name for t in self._tools),
            )
            # 安全扫描：检测 MCP 工具描述中的 prompt injection
            for tool in self._tools:
                _scan_mcp_description(
                    self.name, tool.name,
                    getattr(tool, "description", "") or "",
                )
        except Exception as e:
            logger.error("MCP server '%s': tool discovery failed: %s", self.name, e)
            self._tools = []

    # ── keepalive ────────────────────────────────────────────────────

    async def _wait_shutdown(self):
        """等待关闭信号，期间定期 keepalive 健康检查。

        连续 N 次 keepalive 失败 → 视为连接断开 → 退出传输循环，
        触发 run() 中的重连逻辑。
        """
        failures = 0
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(), timeout=_KEEPALIVE_INTERVAL,
                )
                return  # shutdown signal
            except asyncio.TimeoutError:
                pass  # keepalive interval elapsed

            # 执行 keepalive 健康检查
            if not await self._health_check():
                failures += 1
                logger.warning(
                    "MCP server '%s': health check failed (%d/%d)",
                    self.name, failures, _KEEPALIVE_MAX_FAILURES,
                )
                if failures >= _KEEPALIVE_MAX_FAILURES:
                    logger.error(
                        "MCP server '%s': %d consecutive health check failures, "
                        "reconnecting...", self.name, failures,
                    )
                    break  # 退出传输循环 → run() 重连
            else:
                if failures > 0:
                    logger.info(
                        "MCP server '%s': health check recovered", self.name,
                    )
                failures = 0

    async def _health_check(self) -> bool:
        """发送健康检查 ping。有 tools 用 list_tools，否则用 ping。

        Returns:
            True 表示连接健康，False 表示失败。
        """
        if self.session is None:
            return False
        try:
            async with self._rpc_lock:
                await asyncio.wait_for(
                    self.session.list_tools() if self._tools else self.session.send_ping(),
                    timeout=_KEEPALIVE_TIMEOUT,
                )
            return True
        except asyncio.TimeoutError:
            logger.debug("MCP server '%s': health check timed out", self.name)
            return False
        except Exception:
            logger.debug("MCP server '%s': health check failed", self.name, exc_info=True)
            return False

    # ── 生命周期 ────────────────────────────────────────────────────

    async def run(self):
        """主协程：连接 + 重连循环。"""
        self._shutdown_event = asyncio.Event()
        self._rpc_lock = asyncio.Lock()

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                if self._is_http():
                    await self._run_http()
                else:
                    await self._run_stdio()
                break  # 正常退出
            except asyncio.CancelledError:
                break
            except (InvalidMcpUrlError, NonMcpEndpointError, FileNotFoundError) as e:
                # 配置错误不应重试
                logger.error(
                    "MCP server '%s': configuration error: %s", self.name, e,
                )
                break
            except Exception as e:
                logger.error(
                    "MCP server '%s': connection failed (attempt %d/%d): %s",
                    self.name, attempt, max_retries, e,
                )
                if attempt < max_retries:
                    backoff = min(2 ** (attempt - 1), 30)
                    await asyncio.sleep(backoff)
                else:
                    logger.error(
                        "MCP server '%s': all connection attempts exhausted", self.name,
                    )
        self._ready.set()

    def start(self) -> bool:
        """启动连接（阻塞直到工具发现完成或失败）。"""
        from .client import _ensure_mcp_loop, _run_on_mcp_loop

        loop = _ensure_mcp_loop()
        self._task = asyncio.run_coroutine_threadsafe(self.run(), loop)

        try:
            _run_on_mcp_loop(self._ready.wait(), timeout=_DEFAULT_CONNECT_TIMEOUT)
            return bool(self.session and self._tools)
        except Exception as e:
            logger.error("MCP server '%s': start timeout/failed: %s", self.name, e)
            return False

    def shutdown(self):
        """关闭连接 + 强制杀子进程。"""
        from .client import _ensure_mcp_loop

        if self._shutdown_event:
            loop = _ensure_mcp_loop()
            loop.call_soon_threadsafe(self._shutdown_event.set)
            time.sleep(0.5)
        if self._task:
            try:
                self._task.cancel()
            except Exception:
                pass
        self._cleanup_stdio_pids()

    def _cleanup_stdio_pids(self):
        """清理 stdio 子进程：先 SIGTERM，2s 后 SIGKILL。"""
        if not self._new_pids:
            return
        import signal

        for pid in self._new_pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass

        if self._new_pids:
            time.sleep(2)

        for pid in self._new_pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass

        with _pids_lock:
            for pid in self._new_pids:
                _stdio_pids.pop(pid, None)
        self._new_pids = set()

    # ── 工具调用 ────────────────────────────────────────────────────

    def _get_tool_schema(self, tool_name: str) -> dict:
        """获取指定工具的 inputSchema。"""
        for tool in self._tools:
            if getattr(tool, "name", "") == tool_name:
                return getattr(tool, "inputSchema", None) or {}
        return {}

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """调用 MCP 工具，返回 JSON 字符串。错误已脱敏。

        当 supports_parallel_tool_calls=True 时，不使用 _rpc_lock，
        允许同一 Server 的多个工具并发执行。

        包含:
        - 调前 Schema 基础校验（required / type）
        - 调后审计日志（JSONL）
        """
        t0 = time.monotonic()

        # ── Schema 校验 ──────────────────────────────────
        schema = self._get_tool_schema(tool_name)
        if schema:
            validation_error = _validate_args(tool_name, schema, arguments)
            if validation_error:
                duration_ms = int((time.monotonic() - t0) * 1000)
                _write_audit({
                    "timestamp": time.time(),
                    "server": self.name,
                    "tool": tool_name,
                    "arguments": arguments,
                    "error": validation_error,
                    "duration_ms": duration_ms,
                    "phase": "validation",
                })
                return json.dumps({"error": validation_error}, ensure_ascii=False)

        # ── 调用 ─────────────────────────────────────────
        if self.session is None:
            return json.dumps({
                "error": f"MCP server '{self.name}' is not connected"
            }, ensure_ascii=False)

        try:
            if self.supports_parallel:
                result = await self.session.call_tool(tool_name, arguments=arguments)
            else:
                async with self._rpc_lock:
                    result = await self.session.call_tool(tool_name, arguments=arguments)
        except Exception as exc:
            duration_ms = int((time.monotonic() - t0) * 1000)
            _write_audit({
                "timestamp": time.time(),
                "server": self.name,
                "tool": tool_name,
                "arguments": arguments,
                "error": _str_exc(exc),
                "duration_ms": duration_ms,
                "phase": "call",
            })
            raise

        duration_ms = int((time.monotonic() - t0) * 1000)

        if getattr(result, "isError", False):
            error_text = ""
            for block in (result.content or []):
                if hasattr(block, "text"):
                    error_text += block.text
            error_text = error_text or "MCP tool returned an error"

            # 检测 401 → 作废 OAuth token，下次调用自动刷新
            if self._token_manager and _looks_like_401(error_text):
                logger.warning(
                    "MCP server '%s': received 401, invalidating OAuth token", self.name,
                )
                self._token_manager.invalidate()

            _write_audit({
                "timestamp": time.time(),
                "server": self.name,
                "tool": tool_name,
                "arguments": arguments,
                "error": _sanitize_error(error_text),
                "duration_ms": duration_ms,
                "phase": "call",
            })
            return json.dumps({
                "error": _sanitize_error(error_text)
            }, ensure_ascii=False)

        parts = []
        for block in (result.content or []):
            if hasattr(block, "text") and block.text:
                parts.append(block.text)
        text_result = "\n".join(parts)

        structured = getattr(result, "structuredContent", None)

        # 审计日志
        result_preview = text_result[:500] if text_result else str(structured)[:500]
        _write_audit({
            "timestamp": time.time(),
            "server": self.name,
            "tool": tool_name,
            "arguments": arguments,
            "result": result_preview,
            "duration_ms": duration_ms,
            "phase": "call",
        })

        if structured is not None:
            if text_result:
                return json.dumps({
                    "result": text_result,
                    "structuredContent": structured,
                }, ensure_ascii=False)
            return json.dumps({"result": structured}, ensure_ascii=False)

        return json.dumps({"result": text_result}, ensure_ascii=False)
