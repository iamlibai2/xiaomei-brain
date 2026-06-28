"""MCP OAuth 2.0 集成测试 — 模拟 OAuth2 token endpoint 验证完整流程。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

# 确保 src 在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest


# ── Mock OAuth2 Server ────────────────────────────────────────────


class MockOAuthHandler(BaseHTTPRequestHandler):
    """模拟 OAuth2 token endpoint + MCP endpoint。"""

    # 类变量，由测试设置
    access_token: str = "test-token-abc123"
    expires_in: int = 3600
    expected_client_id: str = "test-client"
    expected_client_secret: str = "test-secret"
    token_request_count: int = 0
    mcp_call_count: int = 0
    should_return_401: bool = False
    enable_auth_discovery: bool = False  # 启用 MCP Auth Discovery 模拟

    @classmethod
    def reset(cls):
        cls.token_request_count = 0
        cls.mcp_call_count = 0
        cls.should_return_401 = False
        cls.enable_auth_discovery = False

    def do_POST(self):
        if self.path == "/oauth/token":
            MockOAuthHandler.token_request_count += 1

            # 读取请求体
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")

            # 解析 form 数据
            params = {}
            for pair in body.split("&"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    params[k] = v

            # 验证 client_credentials
            if params.get("grant_type") != "client_credentials":
                self._send_json(400, {"error": "unsupported_grant_type"})
                return
            if params.get("client_id") != self.expected_client_id:
                self._send_json(401, {"error": "invalid_client"})
                return

            self._send_json(200, {
                "access_token": self.access_token,
                "token_type": "Bearer",
                "expires_in": self.expires_in,
                "scope": params.get("scope", ""),
            })
        else:
            self._send_json(404, {"error": "not_found"})

    def do_GET(self):
        host = self.headers.get("Host", f"localhost:{self.server.server_address[1]}")

        if self.path == "/.well-known/openid-configuration":
            self._send_json(200, {
                "issuer": f"http://{host}",
                "token_endpoint": f"http://{host}/oauth/token",
            })
        elif self.path == "/.well-known/oauth-authorization-server":
            # MCP Auth Discovery Step 3: Authorization Server Metadata
            self._send_json(200, {
                "issuer": f"http://{host}",
                "authorization_endpoint": f"http://{host}/oauth/authorize",
                "token_endpoint": f"http://{host}/oauth/token",
                "scopes_supported": ["read", "write"],
                "code_challenge_methods_supported": ["S256"],
                "response_types_supported": ["code"],
            })
        elif self.path == "/resource-metadata":
            # MCP Auth Discovery Step 2: Protected Resource Metadata
            self._send_json(200, {
                "authorization_servers": [f"http://{host}/.well-known/oauth-authorization-server"],
            })
        elif self.path == "/mcp":
            if self.enable_auth_discovery:
                # MCP Auth Discovery Step 1: 返回 401 + WWW-Authenticate
                body = json.dumps({"error": "unauthorized"}).encode("utf-8")
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.send_header(
                    "WWW-Authenticate",
                    f'Bearer resource_metadata="http://{host}/resource-metadata", '
                    f'error="invalid_token"',
                )
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._send_json(200, {"status": "mcp-endpoint"})
        else:
            self._send_json(404, {"error": "not_found"})

    def _send_json(self, status: int, data: dict):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # 静默 HTTP 日志


class MockOAuthServer:
    """在独立线程中运行 Mock HTTPServer。"""

    def __init__(self):
        self.server = HTTPServer(("127.0.0.1", 0), MockOAuthHandler)
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self._thread: threading.Thread | None = None

    def start(self):
        MockOAuthHandler.reset()
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        self.server.shutdown()
        if self._thread:
            self._thread.join(timeout=2)


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def mock_server():
    srv = MockOAuthServer()
    srv.start()
    yield srv
    srv.stop()


# ── Unit Tests ────────────────────────────────────────────────────


class TestEnvRefResolution:
    def test_simple_ref(self):
        from xiaomei_brain.mcp.auth import _resolve_env_ref
        os.environ["MCP_TEST_VAR"] = "my-value"
        assert _resolve_env_ref("${MCP_TEST_VAR}") == "my-value"

    def test_plain_text_passthrough(self):
        from xiaomei_brain.mcp.auth import _resolve_env_ref
        assert _resolve_env_ref("plain-text") == "plain-text"
        assert _resolve_env_ref("${NOT_SET_ZZZ}") == ""  # unset → empty

    def test_partial_no_match(self):
        from xiaomei_brain.mcp.auth import _resolve_env_ref
        os.environ["MCP_TEST_VAR"] = "my-value"
        # 非完整匹配 — 不展开
        assert _resolve_env_ref("prefix-${MCP_TEST_VAR}") == "prefix-${MCP_TEST_VAR}"


class TestOAuth2Config:
    def test_parse_minimal(self):
        from xiaomei_brain.mcp.auth import OAuth2Config
        cfg = OAuth2Config.from_server_config("srv", {
            "auth": {
                "type": "oauth2",
                "client_id": "cli",
                "token_url": "https://auth.example.com/token",
            }
        })
        assert cfg is not None
        assert cfg.client_id == "cli"
        assert cfg.token_url == "https://auth.example.com/token"
        assert cfg.grant_type == "client_credentials"

    def test_parse_with_oidc_discovery(self):
        from xiaomei_brain.mcp.auth import OAuth2Config
        cfg = OAuth2Config.from_server_config("srv", {
            "auth": {
                "type": "oauth2",
                "client_id": "cli",
                "oidc_discovery_url": "https://auth.example.com/.well-known/openid-configuration",
            }
        })
        assert cfg is not None
        assert cfg.oidc_discovery_url == "https://auth.example.com/.well-known/openid-configuration"

    def test_no_auth_config(self):
        from xiaomei_brain.mcp.auth import OAuth2Config
        cfg = OAuth2Config.from_server_config("srv", {})
        assert cfg is None

    def test_non_oauth_type(self):
        from xiaomei_brain.mcp.auth import OAuth2Config
        cfg = OAuth2Config.from_server_config("srv", {
            "auth": {"type": "bearer", "client_id": "x"}
        })
        assert cfg is None

    def test_validation_no_url(self):
        from xiaomei_brain.mcp.auth import OAuth2Config
        with pytest.raises(ValueError, match="token_url or oidc_discovery_url"):
            OAuth2Config(client_id="test")

    def test_validation_bad_grant_type(self):
        from xiaomei_brain.mcp.auth import OAuth2Config
        with pytest.raises(ValueError, match="unsupported grant_type"):
            OAuth2Config(
                client_id="test", token_url="https://example.com",
                grant_type="password",
            )

    def test_env_var_in_secret(self):
        from xiaomei_brain.mcp.auth import OAuth2Config
        os.environ["OAUTH_SECRET"] = "env-secret"
        cfg = OAuth2Config.from_server_config("srv", {
            "auth": {
                "type": "oauth2",
                "client_id": "cli",
                "client_secret": "${OAUTH_SECRET}",
                "token_url": "https://auth.example.com/token",
            }
        })
        assert cfg.client_secret == "env-secret"

    def test_scopes_and_audience(self):
        from xiaomei_brain.mcp.auth import OAuth2Config
        cfg = OAuth2Config.from_server_config("srv", {
            "auth": {
                "type": "oauth2",
                "client_id": "cli",
                "client_secret": "sec",
                "token_url": "https://auth.example.com/token",
                "scopes": ["read", "write"],
                "audience": "https://api.example.com",
            }
        })
        assert cfg.scopes == ["read", "write"]
        assert cfg.audience == "https://api.example.com"


class TestTokenCache:
    def test_initial_empty(self):
        from xiaomei_brain.mcp.auth import TokenCache
        cache = TokenCache()
        assert not cache.is_valid()
        assert cache.get() is None

    def test_set_and_get(self):
        from xiaomei_brain.mcp.auth import TokenCache
        cache = TokenCache()
        cache.set("token-1", expires_in=3600)
        assert cache.is_valid()
        assert cache.get() == "token-1"

    def test_expired(self):
        from xiaomei_brain.mcp.auth import TokenCache
        cache = TokenCache()
        cache.set("token-1", expires_in=0.01)  # 10ms
        time.sleep(0.02)
        assert not cache.is_valid()

    def test_invalidate(self):
        from xiaomei_brain.mcp.auth import TokenCache
        cache = TokenCache()
        cache.set("token-1", expires_in=3600)
        cache.invalidate()
        assert not cache.is_valid()
        assert cache.get() is None


# ── Integration Tests ──────────────────────────────────────────────


class TestTokenManagerIntegration:
    def test_client_credentials_flow(self, mock_server):
        """完整 client_credentials 流程：获取 token → 缓存 → 复用。"""
        from xiaomei_brain.mcp.auth import OAuth2Config, TokenManager

        cfg = OAuth2Config(
            client_id="test-client",
            client_secret="test-secret",
            token_url=f"{mock_server.url}/oauth/token",
        )
        manager = TokenManager(cfg)

        async def _run():
            token = await manager.ensure_token()
            assert token == MockOAuthHandler.access_token
            assert MockOAuthHandler.token_request_count == 1
            return token

        asyncio.run(_run())

    def test_token_caching(self, mock_server):
        """第二次 ensure_token 不应重新请求 token endpoint。"""
        from xiaomei_brain.mcp.auth import OAuth2Config, TokenManager

        cfg = OAuth2Config(
            client_id="test-client",
            client_secret="test-secret",
            token_url=f"{mock_server.url}/oauth/token",
        )
        manager = TokenManager(cfg)

        async def _run():
            t1 = await manager.ensure_token()
            t2 = await manager.ensure_token()
            # 第二次应该走缓存
            assert t1 == t2
            assert MockOAuthHandler.token_request_count == 1

        asyncio.run(_run())

    def test_invalidate_then_refresh(self, mock_server):
        """作废缓存后，下次 ensure_token 应重新请求。"""
        from xiaomei_brain.mcp.auth import OAuth2Config, TokenManager

        MockOAuthHandler.access_token = "token-v1"
        cfg = OAuth2Config(
            client_id="test-client",
            client_secret="test-secret",
            token_url=f"{mock_server.url}/oauth/token",
        )
        manager = TokenManager(cfg)

        async def _run():
            t1 = await manager.ensure_token()
            assert t1 == "token-v1"
            assert MockOAuthHandler.token_request_count == 1

            # 换 token + 作废
            MockOAuthHandler.access_token = "token-v2"
            manager.invalidate()
            t2 = await manager.ensure_token()
            assert t2 == "token-v2"
            assert MockOAuthHandler.token_request_count == 2

        asyncio.run(_run())

    def test_oidc_discovery(self, mock_server):
        """OIDC Discovery 自动发现 token_endpoint。"""
        from xiaomei_brain.mcp.auth import OAuth2Config, TokenManager

        cfg = OAuth2Config(
            client_id="test-client",
            client_secret="test-secret",
            oidc_discovery_url=f"{mock_server.url}/.well-known/openid-configuration",
        )
        manager = TokenManager(cfg)

        async def _run():
            token = await manager.ensure_token()
            assert token == MockOAuthHandler.access_token
            assert MockOAuthHandler.token_request_count == 1
            # 验证 token_url 被自动填充
            assert cfg.token_url == f"{mock_server.url}/oauth/token"

        asyncio.run(_run())

    def test_set_headers(self):
        """set_headers 应注入 Authorization Bearer header。"""
        from xiaomei_brain.mcp.auth import OAuth2Config, TokenCache, TokenManager

        cache = TokenCache()
        cache.set("my-token", expires_in=3600)

        cfg = OAuth2Config(
            client_id="test-client",
            token_url="https://auth.example.com/token",
        )
        manager = TokenManager(cfg)
        manager._cache = cache  # 注入预设缓存

        headers = manager.set_headers({"X-Custom": "value"})
        assert headers["X-Custom"] == "value"
        assert headers["Authorization"] == "Bearer my-token"

    def test_set_headers_preserves_original(self):
        """set_headers 不应修改原 dict。"""
        from xiaomei_brain.mcp.auth import OAuth2Config, TokenCache, TokenManager

        cache = TokenCache()
        cache.set("my-token", expires_in=3600)

        cfg = OAuth2Config(client_id="test-client", token_url="https://a.com/token")
        manager = TokenManager(cfg)
        manager._cache = cache

        original = {"X-Custom": "value"}
        updated = manager.set_headers(original)
        assert "Authorization" not in original  # 原 dict 不变
        assert updated["Authorization"] == "Bearer my-token"


class TestLookLike401:
    def test_patterns(self):
        from xiaomei_brain.mcp.connection import _looks_like_401

        assert _looks_like_401("HTTP 401 Unauthorized")
        assert _looks_like_401("Error: unauthorized")
        assert _looks_like_401("token expired at 2024-01-01")
        assert _looks_like_401("invalid access token")
        assert not _looks_like_401("tool not found")
        assert not _looks_like_401("")
        assert not _looks_like_401("timeout error")


# ── Auth Discovery 集成测试 ──────────────────────────────────────


class TestMCPAuthDiscovery:
    def test_discover_from_401(self, mock_server):
        """完整 MCP Auth Discovery 流程：401 → resource_metadata → AS metadata."""
        from xiaomei_brain.mcp.auth import MCPAuthDiscovery

        MockOAuthHandler.enable_auth_discovery = True
        discovery = MCPAuthDiscovery(f"{mock_server.url}/mcp", server_name="test")

        async def _run():
            return await discovery.discover()

        metadata = asyncio.run(_run())
        assert metadata.token_endpoint == f"{mock_server.url}/oauth/token"
        assert metadata.authorization_endpoint == f"{mock_server.url}/oauth/authorize"
        assert "read" in metadata.scopes_supported
        assert "S256" in metadata.code_challenge_methods_supported

    def test_no_auth_required(self, mock_server):
        """MCP Server 返回 2xx → 不需要认证."""
        from xiaomei_brain.mcp.auth import MCPAuthDiscovery

        MockOAuthHandler.enable_auth_discovery = False  # 返回 200
        discovery = MCPAuthDiscovery(f"{mock_server.url}/mcp", server_name="test")

        async def _run():
            return await discovery.discover()

        metadata = asyncio.run(_run())
        assert metadata.token_endpoint == ""  # 空 metadata = 不需要认证

    def test_parse_resource_metadata(self):
        """解析 WWW-Authenticate header 中的 resource_metadata URL."""
        from xiaomei_brain.mcp.auth import MCPAuthDiscovery

        discovery = MCPAuthDiscovery("https://example.com/mcp")
        url = discovery._parse_resource_metadata(
            'Bearer resource_metadata="https://auth.example.com/rm", error="invalid_token"'
        )
        assert url == "https://auth.example.com/rm"

    def test_parse_resource_metadata_none(self):
        """WWW-Authenticate 不含 resource_metadata 时返回 None."""
        from xiaomei_brain.mcp.auth import MCPAuthDiscovery

        discovery = MCPAuthDiscovery("https://example.com/mcp")
        url = discovery._parse_resource_metadata('Bearer error="invalid_token"')
        assert url is None
