"""MCP OAuth 2.0 / OIDC 认证支持。

支持三种授权模式:
- client_credentials — M2M，系统对系统
- authorization_code + PKCE — 用户代理访问个人资源（邮箱、日历等）
- ema (ID-JAG / Token Exchange) — 企业 SSO 静默授权

Token 内存缓存，提前 30s 刷新，支持 env var 引用 ""${VAR_NAME}""。

配置格式::

    # Client Credentials（已有）
    "auth": {
        "type": "oauth2",
        "grant_type": "client_credentials",
        "client_id": "xiaomei-brain",
        "client_secret": "${OAUTH_SECRET}",
        "token_url": "https://auth.company.com/oauth/token",
        "scopes": ["erp:read"]
    }

    # Authorization Code + PKCE（新增）
    "auth": {
        "type": "oauth2",
        "grant_type": "authorization_code",
        "client_id": "xiaomei-brain",
        "authorization_url": "https://auth.company.com/oauth/authorize",
        "token_url": "https://auth.company.com/oauth/token",
        "scopes": ["calendar:read", "gmail.read"]
    }

    # EMA / ID-JAG（新增）
    "auth": {
        "type": "ema",
        "grant_type": "ema",
        "client_id": "xiaomei-brain",
        "token_url": "https://auth.company.com/oauth/token",
        "scopes": ["erp:read"],
        "resource": "https://erp.company.com/mcp",
        "subject_token_source": "env:IDP_TOKEN"
    }
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# 提前刷新窗口（秒）：token 在 expires_at 前 30s 视为过期
_TOKEN_REFRESH_MARGIN = 30.0
_DEFAULT_EXPIRES_IN = 3600.0  # 默认 token 有效期 1 小时


# ── Env var 引用解析 ────────────────────────────────────────────────

_ENV_REF_RE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def _resolve_env_ref(value: str) -> str:
    """解析 ""${ENV_VAR}"" 格式的环境变量引用。

    匹配 ""${VAR_NAME}"" 完整字符串 → os.getenv(VAR_NAME)。
    不匹配则原样返回。
    """
    if not isinstance(value, str):
        return value
    m = _ENV_REF_RE.match(value)
    if m:
        env_val = os.getenv(m.group(1), "")
        if not env_val:
            logger.warning("OAuth: env var '%s' referenced but not set", m.group(1))
        return env_val
    return value


def _resolve_env_refs(data: dict[str, Any], *keys: str) -> None:
    """对 dict 的指定字段执行 env var 引用解析。原地修改。"""
    for key in keys:
        if key in data and isinstance(data[key], str):
            data[key] = _resolve_env_ref(data[key])


# ── PKCE ────────────────────────────────────────────────────────────

import base64
import hashlib
import secrets


def generate_code_verifier() -> str:
    """生成 S256 PKCE code_verifier（43 字符，unreserved chars）。"""
    return secrets.token_urlsafe(32)


def compute_code_challenge(verifier: str) -> str:
    """S256: base64url(sha256(ascii(verifier)))，去除 = padding。"""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# ── Subject Token 解析 ──────────────────────────────────────────────


def _resolve_subject_token(source: str) -> str:
    """从指定来源获取 EMA subject_token。

    - ``env:VAR_NAME`` → os.getenv()
    - ``file:/path`` → 读取文件内容（strip）
    - 纯字符串 → 直接用作 token
    """
    if source.startswith("env:"):
        var = source[4:]
        token = os.getenv(var, "")
        if not token:
            raise ValueError(f"EMA subject_token: env var '{var}' is not set")
        return token
    if source.startswith("file:"):
        path = os.path.expanduser(source[5:])
        if not os.path.isfile(path):
            raise FileNotFoundError(f"EMA subject_token: file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return source


# ── OAuth2Config ────────────────────────────────────────────────────


_VALID_GRANT_TYPES = frozenset({"client_credentials", "authorization_code", "ema"})


@dataclass
class OAuth2Config:
    """OAuth 2.0 认证配置，从 MCP server config 的 auth 块解析。

    支持三种 grant_type:
    - client_credentials: M2M，client_id + client_secret → access_token
    - authorization_code: 用户授权，PKCE → 浏览器回调 → code 换 token
    - ema: 企业 SSO，ID-JAG Token Exchange
    """

    client_id: str
    client_secret: str = ""
    token_url: str = ""
    grant_type: str = "client_credentials"
    scopes: list[str] = field(default_factory=list)
    audience: str = ""
    resource: str = ""

    # OIDC / OAuth 自动发现
    oidc_discovery_url: str = ""

    # authorization_code 专用
    authorization_url: str = ""
    redirect_port: int = 0  # 0 = 随机端口

    # EMA 专用
    subject_token_source: str = ""  # env:VAR / file:path / 裸 token

    # MCP server URL（用于 resource 参数）
    mcp_url: str = ""

    def __post_init__(self):
        if not self.client_id:
            raise ValueError("OAuth2Config: client_id is required")
        if self.grant_type not in _VALID_GRANT_TYPES:
            raise ValueError(
                f"OAuth2Config: unsupported grant_type '{self.grant_type}'. "
                f"Supported: {', '.join(sorted(_VALID_GRANT_TYPES))}"
            )

        if self.grant_type == "client_credentials":
            if not self.token_url and not self.oidc_discovery_url:
                raise ValueError(
                    "OAuth2Config: client_credentials requires token_url or "
                    "oidc_discovery_url"
                )
        elif self.grant_type == "authorization_code":
            if not self.authorization_url:
                raise ValueError(
                    "OAuth2Config: authorization_code requires authorization_url"
                )
            if not self.token_url and not self.oidc_discovery_url:
                raise ValueError(
                    "OAuth2Config: authorization_code requires token_url or "
                    "oidc_discovery_url"
                )
        elif self.grant_type == "ema":
            if not self.token_url:
                raise ValueError("OAuth2Config: ema requires token_url")
            if not self.subject_token_source:
                raise ValueError(
                    "OAuth2Config: ema requires subject_token_source "
                    "(e.g. env:IDP_TOKEN or file:~/.sso/token)"
                )

    @classmethod
    def from_server_config(cls, server_name: str, config: dict) -> OAuth2Config | None:
        """从 MCP server 配置中解析 OAuth 2.0 配置。"""
        auth_cfg = config.get("auth")
        if not auth_cfg or not isinstance(auth_cfg, dict):
            return None

        auth_type = auth_cfg.get("type", "").lower()
        grant_type = auth_cfg.get("grant_type", "client_credentials").lower()

        # EMA 类型也走这里，type 可以是 "ema" 或 "oauth2"
        if auth_type not in ("oauth2", "ema"):
            return None

        # 展开环境变量引用
        _resolve_env_refs(auth_cfg, "client_secret", "token_url", "oidc_discovery_url",
                          "authorization_url", "subject_token_source")

        return cls(
            client_id=auth_cfg.get("client_id", ""),
            client_secret=auth_cfg.get("client_secret", ""),
            token_url=auth_cfg.get("token_url", ""),
            grant_type=grant_type,
            scopes=list(auth_cfg.get("scopes", [])),
            audience=auth_cfg.get("audience", ""),
            resource=auth_cfg.get("resource", ""),
            oidc_discovery_url=auth_cfg.get("oidc_discovery_url", ""),
            authorization_url=auth_cfg.get("authorization_url", ""),
            redirect_port=auth_cfg.get("redirect_port", 0),
            subject_token_source=auth_cfg.get("subject_token_source", ""),
            mcp_url=config.get("url", ""),
        )


# ── TokenCache ──────────────────────────────────────────────────────


class TokenCache:
    """线程安全的内存 token 缓存。"""

    def __init__(self):
        self._lock = threading.Lock()
        self.access_token: str = ""
        self.expires_at: float = 0.0
        self.scope: str = ""

    def is_valid(self) -> bool:
        """token 是否存在且未过期（考虑提前刷新窗口）。"""
        with self._lock:
            if not self.access_token:
                return False
            return time.monotonic() < self.expires_at - _TOKEN_REFRESH_MARGIN

    def get(self) -> str | None:
        """获取有效 token，无效返回 None。"""
        with self._lock:
            if self.access_token and time.monotonic() < self.expires_at - _TOKEN_REFRESH_MARGIN:
                return self.access_token
            return None

    def set(self, access_token: str, expires_in: float = _DEFAULT_EXPIRES_IN,
            scope: str = "") -> None:
        """更新缓存。"""
        with self._lock:
            self.access_token = access_token
            self.expires_at = time.monotonic() + expires_in
            self.scope = scope

    def invalidate(self) -> None:
        """作废缓存（401 时调用）。"""
        with self._lock:
            self.access_token = ""
            self.expires_at = 0.0
            self.scope = ""


# ── MCP Auth Discovery ───────────────────────────────────────────────


@dataclass
class AuthorizationServerMetadata:
    """MCP 规范定义的 Authorization Server 元数据。"""

    issuer: str = ""
    authorization_endpoint: str = ""
    token_endpoint: str = ""
    registration_endpoint: str = ""
    scopes_supported: list[str] = field(default_factory=list)
    code_challenge_methods_supported: list[str] = field(default_factory=list)
    response_types_supported: list[str] = field(default_factory=list)


class MCPAuthDiscovery:
    """MCP 规范 Auth Discovery 流程。

    从 MCP Server URL 自动发现 OAuth metadata:
    1. 不带 auth 访问 MCP URL → 解析 401 + WWW-Authenticate
    2. GET resource_metadata → 提取 authorization_servers
    3. GET /.well-known/oauth-authorization-server → 端点元数据
    """

    def __init__(self, mcp_url: str, server_name: str = ""):
        self._mcp_url = mcp_url
        self._server_name = server_name

    async def discover(self) -> AuthorizationServerMetadata:
        """执行发现流程，返回 Authorization Server 元数据。"""
        import httpx

        # Step 1: 探测 MCP URL，解析 401 + WWW-Authenticate
        resource_md_url = None
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            try:
                resp = await client.get(self._mcp_url)
                # 如果 2xx 且正常的 MCP response，说明不需要 auth
                if 200 <= resp.status_code < 300:
                    ct = resp.headers.get("content-type", "")
                    if "json" in ct or "event-stream" in ct:
                        logger.info(
                            "MCP server '%s': no auth required (2xx MCP response)",
                            self._server_name,
                        )
                        return AuthorizationServerMetadata()
                elif resp.status_code == 401:
                    www_auth = resp.headers.get("WWW-Authenticate", "")
                    resource_md_url = self._parse_resource_metadata(www_auth)
                else:
                    raise ValueError(
                        f"MCP auth discovery: unexpected HTTP {resp.status_code} "
                        f"from {self._mcp_url}"
                    )
            except httpx.RequestError as e:
                raise ValueError(
                    f"MCP auth discovery: request failed: {e}"
                ) from e

        if not resource_md_url:
            logger.info(
                "MCP server '%s': no WWW-Authenticate with resource_metadata, "
                "continuing without auth discovery", self._server_name,
            )
            return AuthorizationServerMetadata()

        # Step 2: 获取 Protected Resource Metadata
        as_url = None
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.get(resource_md_url)
            resp.raise_for_status()
            resource_md = resp.json()
            as_list = resource_md.get("authorization_servers", [])
            if as_list:
                as_url = as_list[0]  # 取第一个
            else:
                raise ValueError(
                    f"MCP auth discovery: resource_metadata at {resource_md_url} "
                    "contains no authorization_servers"
                )

        # Step 3: 获取 Authorization Server Metadata
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.get(as_url)
            resp.raise_for_status()
            as_md = resp.json()

        metadata = AuthorizationServerMetadata(
            issuer=as_md.get("issuer", ""),
            authorization_endpoint=as_md.get("authorization_endpoint", ""),
            token_endpoint=as_md.get("token_endpoint", ""),
            registration_endpoint=as_md.get("registration_endpoint", ""),
            scopes_supported=list(as_md.get("scopes_supported", [])),
            code_challenge_methods_supported=list(
                as_md.get("code_challenge_methods_supported", [])
            ),
            response_types_supported=list(
                as_md.get("response_types_supported", [])
            ),
        )

        logger.info(
            "MCP server '%s': auth discovery OK — token_endpoint=%s",
            self._server_name, metadata.token_endpoint,
        )
        return metadata

    def _parse_resource_metadata(self, www_auth: str) -> str | None:
        """从 WWW-Authenticate header 解析 resource_metadata URL。

        格式: Bearer resource_metadata="https://...", ...
        """
        import re
        m = re.search(r'resource_metadata="([^"]+)"', www_auth)
        if m:
            return m.group(1)
        return None


# ── Authorization Callback Server ────────────────────────────────────

import asyncio
from urllib.parse import urlparse, parse_qs


class AuthorizationCallbackServer:
    """临时 HTTP 服务器接收 OAuth 2.0 回调。

    在随机端口启动，等待一次 GET /callback?code=...&state=... 请求，
    返回 HTML 确认页面后关闭。

    用法::

        server = AuthorizationCallbackServer()
        port = await server.start()
        redirect_uri = f"http://localhost:{port}/callback"
        # ... 构造授权 URL，打开浏览器 ...
        auth_code = await server.wait_for_code(timeout=120)
    """

    def __init__(self, expected_state: str = ""):
        self._expected_state = expected_state
        self._port: int = 0
        self._auth_code: str | None = None
        self._error: str | None = None
        self._received = asyncio.Event()
        self._server: asyncio.AbstractServer | None = None

    @property
    def port(self) -> int:
        return self._port

    async def start(self) -> int:
        """启动 HTTP 服务器，返回绑定的端口。"""
        async def _handler(reader: asyncio.StreamReader,
                          writer: asyncio.StreamWriter) -> None:
            try:
                request_line = await asyncio.wait_for(
                    reader.readline(), timeout=5.0
                )
                request_line = request_line.decode("utf-8", errors="replace").strip()
                # 读取 headers（跳过）
                while True:
                    line = await asyncio.wait_for(
                        reader.readline(), timeout=2.0
                    )
                    if not line or line in (b"\r\n", b"\n"):
                        break

                if not request_line:
                    self._send_response(writer, 400, "Bad Request")
                    return

                method, path, _ = request_line.split(" ", 2)
                parsed = urlparse(path)

                if method == "GET" and parsed.path == "/callback":
                    params = parse_qs(parsed.query)

                    # 验证 state
                    state = params.get("state", [""])[0]
                    if self._expected_state and state != self._expected_state:
                        self._error = f"state mismatch: expected {self._expected_state}, got {state}"
                        logger.error("OAuth callback: %s", self._error)
                        self._send_html(writer, 400, "Authorization Failed",
                                        f"<h1>Authorization Failed</h1><p>{self._error}</p>")
                        self._received.set()
                        return

                    code = params.get("code", [""])[0]
                    error = params.get("error", [""])[0]

                    if error:
                        error_desc = params.get("error_description", [""])[0]
                        self._error = f"{error}: {error_desc}"
                        self._send_html(writer, 400, "Authorization Failed",
                                        f"<h1>Authorization Failed</h1><p>{self._error}</p>")
                        self._received.set()
                        return

                    if code:
                        self._auth_code = code
                        self._send_html(
                            writer, 200, "Authorization Successful",
                            "<h1>Authorization Successful</h1>"
                            "<p>You may close this window and return to the application.</p>",
                        )
                        self._received.set()
                    else:
                        self._send_html(writer, 400, "Bad Request",
                                        "<h1>Bad Request</h1><p>No authorization code received.</p>")
                else:
                    self._send_response(writer, 404, "Not Found")

            except asyncio.TimeoutError:
                self._send_response(writer, 408, "Request Timeout")
            except Exception as e:
                logger.debug("OAuth callback handler error: %s", e)
            finally:
                try:
                    writer.close()
                except Exception:
                    pass

        # 绑定随机端口
        self._server = await asyncio.start_server(
            _handler, host="127.0.0.1", port=0,
        )
        self._port = self._server.sockets[0].getsockname()[1]
        logger.debug("OAuth callback server started on port %d", self._port)
        return self._port

    async def wait_for_code(self, timeout: float = 120.0) -> str:
        """等待授权回调，返回 authorization_code。

        Raises:
            TimeoutError: 超时
            ValueError: 授权失败（error 参数）
        """
        try:
            await asyncio.wait_for(self._received.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"OAuth authorization timeout after {timeout:.0f}s. "
                "User did not complete authorization in browser."
            ) from None

        if self._error:
            raise ValueError(f"OAuth authorization failed: {self._error}")
        if not self._auth_code:
            raise ValueError("OAuth authorization failed: no code received")

        return self._auth_code

    async def stop(self) -> None:
        """关闭服务器。"""
        if self._server:
            self._server.close()
            try:
                await asyncio.wait_for(self._server.wait_closed(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

    @staticmethod
    def _send_response(writer: asyncio.StreamWriter, status: int,
                       text: str) -> None:
        body = text.encode("utf-8")
        writer.write(
            f"HTTP/1.1 {status} {text[:20]}\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"\r\n".encode("utf-8")
        )
        writer.write(body)

    @staticmethod
    def _send_html(writer: asyncio.StreamWriter, status: int,
                   title: str, body_html: str) -> None:
        html = (
            f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{title}</title>"
            f"<style>body{{font-family:sans-serif;display:flex;justify-content:center;"
            f"align-items:center;min-height:100vh;margin:0;background:#f5f5f5}}"
            f".card{{background:white;padding:2rem;border-radius:8px;box-shadow:0 2px 8px "
            f"rgba(0,0,0,.1);text-align:center}}</style></head>"
            f"<body><div class='card'>{body_html}</div></body></html>"
        ).encode("utf-8")
        writer.write(
            f"HTTP/1.1 {status} {title}\r\n"
            f"Content-Type: text/html; charset=utf-8\r\n"
            f"Content-Length: {len(html)}\r\n"
            f"Connection: close\r\n\r\n".encode("utf-8")
        )
        writer.write(html)


# ── TokenManager ────────────────────────────────────────────────────


class TokenManager:
    """OAuth 2.0 Token 管理器。

    支持三种授权模式:
    - client_credentials: M2M 直接换 token
    - authorization_code + PKCE: 用户浏览器授权
    - ema: 企业 SSO Token Exchange (RFC 8693)

    负责:
    - Token 发现/获取/缓存/刷新
    - 401 时作废缓存
    """

    def __init__(self, config: OAuth2Config, server_name: str = ""):
        self._config = config
        self._server_name = server_name
        self._cache = TokenCache()
        self._discovery_done = False
        self._lock = threading.Lock()

    # ── 公共 API ────────────────────────────────────────────────

    async def ensure_token(self) -> str:
        """确保有有效 token，返回 access_token。

        Raises:
            ValueError: 获取 token 失败。
            TimeoutError: authorization_code 模式下用户超时未授权。
        """
        token = self._cache.get()
        if token:
            return token
        return await self._refresh()

    def invalidate(self) -> None:
        """作废当前 token（收到 401 时调用）。"""
        self._cache.invalidate()
        logger.info("MCP server '%s': OAuth token invalidated", self._server_name)

    def set_headers(self, headers: dict) -> dict:
        """同步方式注入 Authorization header（用于连接建立时）。

        从缓存获取 token，如果缓存为空则返回未修改的 headers。
        调用方应在连接建立前通过 ensure_token() 预取 token。

        Returns:
            更新后的 headers dict（新建，不修改原 dict）。
        """
        updated = dict(headers or {})
        token = self._cache.get()
        if token:
            updated["Authorization"] = f"Bearer {token}"
        return updated

    # ── 内部 ────────────────────────────────────────────────────

    async def _discover_if_needed(self) -> None:
        """如果配置了 oidc_discovery_url 且尚未发现，则执行 OIDC 发现。"""
        with self._lock:
            if self._discovery_done:
                return
            need_discovery = bool(self._config.oidc_discovery_url)
            if not need_discovery:
                self._discovery_done = True
                return
            discovery_url = self._config.oidc_discovery_url

        try:
            token_endpoint = await self._do_oidc_discovery(discovery_url)
            self._config.token_url = token_endpoint
            logger.info(
                "MCP server '%s': OIDC discovery OK — token_endpoint=%s",
                self._server_name, token_endpoint,
            )
        except Exception as e:
            logger.error(
                "MCP server '%s': OIDC discovery failed: %s", self._server_name, e,
            )
            raise
        finally:
            with self._lock:
                self._discovery_done = True

    async def _do_oidc_discovery(self, discovery_url: str) -> str:
        """执行 OIDC Discovery，返回 token_endpoint。"""
        try:
            import httpx
        except ImportError:
            raise RuntimeError("httpx is required for OIDC discovery") from None

        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.get(discovery_url)
            resp.raise_for_status()
            metadata = resp.json()

        token_endpoint = metadata.get("token_endpoint", "")
        if not token_endpoint:
            raise ValueError(
                f"OIDC discovery at {discovery_url} returned no token_endpoint. "
                f"Keys found: {list(metadata.keys())[:10]}"
            )
        return token_endpoint

    async def _refresh(self) -> str:
        """刷新 token：按 grant_type 分派到对应流程。"""
        await self._discover_if_needed()

        if self._config.grant_type == "client_credentials":
            return await self._refresh_client_credentials()
        elif self._config.grant_type == "authorization_code":
            return await self._refresh_authorization_code()
        elif self._config.grant_type == "ema":
            return await self._refresh_ema()
        else:
            raise ValueError(
                f"OAuth2Config: unsupported grant_type '{self._config.grant_type}'"
            )

    # ── client_credentials ──────────────────────────────────────

    async def _refresh_client_credentials(self) -> str:
        """Client Credentials: POST token_url 换 access_token。"""
        if not self._config.token_url:
            raise ValueError(
                f"OAuth2Config: no token_url for server '{self._server_name}'"
            )

        import httpx

        body: dict[str, str] = {
            "grant_type": "client_credentials",
            "client_id": self._config.client_id,
        }
        if self._config.client_secret:
            body["client_secret"] = self._config.client_secret
        if self._config.scopes:
            body["scope"] = " ".join(self._config.scopes)
        if self._config.audience:
            body["audience"] = self._config.audience
        if self._config.resource:
            body["resource"] = self._config.resource

        data = await self._post_token(body)
        return self._save_token(data)

    # ── authorization_code + PKCE ───────────────────────────────

    async def _refresh_authorization_code(self) -> str:
        """Authorization Code + PKCE: 浏览器跳转 → 回调 → code 换 token。"""
        import webbrowser

        if not self._config.authorization_url:
            raise ValueError(
                f"OAuth2Config: authorization_code requires authorization_url"
            )
        if not self._config.token_url:
            raise ValueError(
                f"OAuth2Config: authorization_code requires token_url"
            )

        # 1. 生成 PKCE
        code_verifier = generate_code_verifier()
        code_challenge = compute_code_challenge(code_verifier)
        state = secrets.token_urlsafe(16)

        # 2. 启动回调服务器
        callback = AuthorizationCallbackServer(expected_state=state)
        port = await callback.start()
        redirect_uri = f"http://localhost:{port}/callback"

        # 3. 构造授权 URL
        params: list[tuple[str, str]] = [
            ("response_type", "code"),
            ("client_id", self._config.client_id),
            ("redirect_uri", redirect_uri),
            ("code_challenge", code_challenge),
            ("code_challenge_method", "S256"),
            ("state", state),
        ]
        if self._config.scopes:
            params.append(("scope", " ".join(self._config.scopes)))
        if self._config.resource:
            params.append(("resource", self._config.resource))

        from urllib.parse import urlencode
        auth_url = f"{self._config.authorization_url}?{urlencode(params)}"

        # 4. 提示用户授权
        logger.info(
            "MCP server '%s': opening browser for OAuth authorization\n  %s",
            self._server_name, auth_url,
        )
        print(f"\n  ── OAuth 授权 ─────────────────────────────────────")
        print(f"  MCP Server: {self._server_name}")
        print(f"  Scopes: {' '.join(self._config.scopes) or '(none)'}")
        print(f"\n  请在浏览器中完成授权：\n  {auth_url}\n")

        try:
            webbrowser.open(auth_url)
        except Exception:
            pass  # 用户手动复制 URL

        # 5. 等待回调
        try:
            auth_code = await callback.wait_for_code(timeout=120)
        finally:
            await callback.stop()

        logger.info(
            "MCP server '%s': authorization code received", self._server_name,
        )

        # 6. 交换 token
        import httpx
        body = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
            "client_id": self._config.client_id,
        }

        data = await self._post_token(body)
        return self._save_token(data)

    # ── EMA / ID-JAG ───────────────────────────────────────────

    async def _refresh_ema(self) -> str:
        """EMA (ID-JAG): RFC 8693 Token Exchange。

        交换 SSO id_token / access_token 换取 MCP 专用 access_token。
        """
        if not self._config.subject_token_source:
            raise ValueError(
                f"OAuth2Config: ema requires subject_token_source"
            )

        subject_token = _resolve_subject_token(self._config.subject_token_source)
        logger.debug(
            "MCP server '%s': EMA subject_token obtained (%d chars)",
            self._server_name, len(subject_token),
        )

        import httpx

        body: dict[str, str] = {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": subject_token,
            "subject_token_type": "urn:ietf:params:oauth:token-type:id_token",
            "client_id": self._config.client_id,
        }
        if self._config.client_secret:
            body["client_secret"] = self._config.client_secret
        if self._config.scopes:
            body["scope"] = " ".join(self._config.scopes)
        if self._config.resource or self._config.mcp_url:
            body["resource"] = self._config.resource or self._config.mcp_url
        if self._config.audience:
            body["audience"] = self._config.audience

        data = await self._post_token(body)
        return self._save_token(data)

    # ── 公共辅助 ────────────────────────────────────────────────

    async def _post_token(self, body: dict) -> dict:
        """POST token endpoint，返回 JSON 响应。"""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                resp = await client.post(
                    self._config.token_url,
                    data=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            detail = ""
            try:
                detail = e.response.text[:500]
            except Exception:
                pass
            raise ValueError(
                f"OAuth 2.0 token request failed: HTTP {e.response.status_code} "
                f"from {self._config.token_url} — {detail}"
            ) from e
        except Exception as e:
            raise ValueError(
                f"OAuth 2.0 token request failed: {type(e).__name__}: {e}"
            ) from e

    def _save_token(self, data: dict) -> str:
        """保存 token 到缓存，返回 access_token。"""
        access_token = data.get("access_token", "")
        if not access_token:
            raise ValueError(
                f"OAuth 2.0 token response missing access_token. "
                f"Keys: {list(data.keys())[:10]}"
            )

        expires_in = float(data.get("expires_in", _DEFAULT_EXPIRES_IN))
        scope = data.get("scope", "")

        self._cache.set(access_token, expires_in, scope)
        logger.info(
            "MCP server '%s': OAuth token refreshed (grant_type=%s, expires_in=%ds, scope=%s)",
            self._server_name, self._config.grant_type, int(expires_in), scope or "(none)",
        )
        return access_token
