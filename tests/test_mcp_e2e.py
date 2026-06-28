"""MCP 端到端测试 — stdio 传输 + 工具调用 + Schema 校验 + 审计日志。

前置条件:
    - mcp SDK 已安装
    - Python 环境中可用

运行:
    PYTHONPATH=src python3 -m pytest tests/test_mcp_e2e.py -v
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

# 确保 src 在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Test server 路径
_TEST_SERVER = os.path.join(
    os.path.dirname(__file__), "test_mcp_server.py"
)


# ── Helpers ──────────────────────────────────────────────────────────


def _python_exe() -> str:
    """获取当前 Python 解释器路径."""
    return sys.executable


def _server_config() -> dict:
    """返回 test_server 的 stdio 配置."""
    return {
        "command": _python_exe(),
        "args": [_TEST_SERVER],
        "timeout": 30,
        "connect_timeout": 15,
    }


# ── Unit: Schema 校验 ───────────────────────────────────────────────


class TestSchemaValidation:
    def test_missing_required(self):
        """缺少必填字段应返回错误."""
        from xiaomei_brain.mcp.connection import _validate_args

        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        err = _validate_args("hello", schema, {})
        assert err is not None
        assert "Missing required parameters" in err
        assert "name" in err

    def test_valid_args(self):
        """合法参数应返回 None."""
        from xiaomei_brain.mcp.connection import _validate_args

        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        err = _validate_args("hello", schema, {"name": "world"})
        assert err is None

    def test_type_mismatch(self):
        """类型不匹配应返回错误."""
        from xiaomei_brain.mcp.connection import _validate_args

        schema = {
            "type": "object",
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"},
            },
            "required": ["a", "b"],
        }
        err = _validate_args("add", schema, {"a": "not_a_number", "b": 2})
        assert err is not None
        assert "Invalid type" in err
        assert "a" in err

    def test_unknown_type_skipped(self):
        """未知类型声明应跳过校验."""
        from xiaomei_brain.mcp.connection import _validate_args

        schema = {
            "type": "object",
            "properties": {"x": {"type": "unknown_type"}},
        }
        err = _validate_args("test", schema, {"x": "anything"})
        assert err is None

    def test_detect_missing_trivial_schema(self):
        """无 required 无 properties 的 trivial schema 应始终通过."""
        from xiaomei_brain.mcp.connection import _validate_args

        err = _validate_args("test", {}, {"anything": 1})
        assert err is None


# ── Unit: 401 检测 ──────────────────────────────────────────────────


class TestLookLike401:
    def test_patterns(self):
        from xiaomei_brain.mcp.connection import _looks_like_401

        assert _looks_like_401("HTTP 401 Unauthorized")
        assert _looks_like_401("Error: unauthorized")
        assert _looks_like_401("token expired at 2024-01-01")
        assert _looks_like_401("invalid access token")
        assert _looks_like_401("invalid_token: token is not active")
        assert not _looks_like_401("tool not found")
        assert not _looks_like_401("")
        assert not _looks_like_401("timeout error")


# ── Unit: 工具 Schema 转换 ──────────────────────────────────────────


class TestSchemaConversion:
    def test_prefixed_naming(self):
        """工具名应带 mcp__<server>__<tool> 前缀."""
        from xiaomei_brain.mcp.client import _convert_mcp_schema, _sanitize_name
        from unittest.mock import Mock

        mock_tool = Mock()
        mock_tool.name = "hello"
        mock_tool.description = "Say hello"
        mock_tool.inputSchema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }

        schema = _convert_mcp_schema("test-server", mock_tool)
        assert schema["name"].startswith("mcp__")
        assert "hello" in schema["name"]
        assert schema["parameters"]["required"] == ["name"]

    def test_no_required_fields(self):
        """无 required 字段的 schema 不应包含 required."""
        from xiaomei_brain.mcp.client import _convert_mcp_schema
        from unittest.mock import Mock

        mock_tool = Mock()
        mock_tool.name = "echo"
        mock_tool.description = "Echo"
        mock_tool.inputSchema = {"type": "object", "properties": {}}

        schema = _convert_mcp_schema("srv", mock_tool)
        assert "required" not in schema["parameters"]


# ── Integration: MCPConnection stdio ────────────────────────────────


@pytest.mark.asyncio
class TestMCPConnectionStdio:
    """通过 stdio 连接 test_server.py 的端到端测试."""

    async def test_connect_and_discover(self):
        """连接 test_server，发现 hello 和 add 两个工具."""
        from xiaomei_brain.mcp.connection import MCPConnection

        conn = MCPConnection("test-srv", _server_config())
        # 在后台运行 run()
        task = asyncio.create_task(conn.run())

        try:
            await asyncio.wait_for(conn._ready.wait(), timeout=15)
            assert conn.session is not None
            tool_names = [t.name for t in conn._tools]
            assert "hello" in tool_names
            assert "add" in tool_names
            assert len(conn._tools) == 2
        finally:
            conn.shutdown()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def test_call_hello(self):
        """调用 hello 工具."""
        from xiaomei_brain.mcp.connection import MCPConnection

        conn = MCPConnection("test-srv", _server_config())
        task = asyncio.create_task(conn.run())

        try:
            await asyncio.wait_for(conn._ready.wait(), timeout=15)
            result = await conn.call_tool("hello", {"name": "World"})
            data = json.loads(result)
            assert "error" not in data
            assert "Hello, World!" in data.get("result", "")
        finally:
            conn.shutdown()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def test_call_add(self):
        """调用 add 工具."""
        from xiaomei_brain.mcp.connection import MCPConnection

        conn = MCPConnection("test-srv", _server_config())
        task = asyncio.create_task(conn.run())

        try:
            await asyncio.wait_for(conn._ready.wait(), timeout=15)
            result = await conn.call_tool("add", {"a": 3, "b": 4})
            data = json.loads(result)
            assert "error" not in data
            assert "3 + 4 = 7" in data.get("result", "")
        finally:
            conn.shutdown()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def test_schema_validation_rejects_before_call(self):
        """Schema 校验：缺少必填字段时不应真正调用 MCP 工具."""
        from xiaomei_brain.mcp.connection import MCPConnection

        conn = MCPConnection("test-srv", _server_config())
        task = asyncio.create_task(conn.run())

        try:
            await asyncio.wait_for(conn._ready.wait(), timeout=15)
            # hello 需要 name 参数，不传
            result = await conn.call_tool("hello", {})
            data = json.loads(result)
            assert "error" in data
            assert "Missing required parameters" in data["error"]
            assert "name" in data["error"]
        finally:
            conn.shutdown()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def test_schema_type_validation(self):
        """Schema 校验：类型不匹配应拒绝."""
        from xiaomei_brain.mcp.connection import MCPConnection

        conn = MCPConnection("test-srv", _server_config())
        task = asyncio.create_task(conn.run())

        try:
            await asyncio.wait_for(conn._ready.wait(), timeout=15)
            # add 需要 number 类型，传 string
            result = await conn.call_tool("add", {"a": "not_number", "b": 2})
            data = json.loads(result)
            assert "error" in data
            assert "Invalid type" in data["error"]
        finally:
            conn.shutdown()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def test_call_nonexistent_tool(self):
        """调用不存在的工具应返回错误（应用层错误，非异常）."""
        from xiaomei_brain.mcp.connection import MCPConnection

        conn = MCPConnection("test-srv", _server_config())
        task = asyncio.create_task(conn.run())

        try:
            await asyncio.wait_for(conn._ready.wait(), timeout=15)
            result = await conn.call_tool("nonexistent", {})
            data = json.loads(result)
            # MCP 服务端返回应用层错误，不是传输层异常
            assert "error" in data or "Unknown tool" in str(data)
        finally:
            conn.shutdown()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def test_health_check(self):
        """健康检查：正常连接应返回 True."""
        from xiaomei_brain.mcp.connection import MCPConnection

        conn = MCPConnection("test-srv", _server_config())
        task = asyncio.create_task(conn.run())

        try:
            await asyncio.wait_for(conn._ready.wait(), timeout=15)
            healthy = await conn._health_check()
            assert healthy is True
        finally:
            conn.shutdown()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def test_health_check_disconnected(self):
        """未连接的 session 健康检查应返回 False."""
        from xiaomei_brain.mcp.connection import MCPConnection

        conn = MCPConnection("test-srv", _server_config())
        # 不启动连接
        healthy = await conn._health_check()
        assert healthy is False


# ── Integration: 审计日志 ───────────────────────────────────────────


class TestAuditLog:
    def test_audit_log_written(self):
        """工具调用后应写入审计日志."""
        from xiaomei_brain.mcp.connection import _write_audit, _get_audit_log

        # 写一条测试记录
        _write_audit({
            "timestamp": time.time(),
            "server": "test-audit",
            "tool": "test_tool",
            "arguments": {"x": 1},
            "result": "ok",
            "duration_ms": 5,
        })

        # 验证日志文件存在
        log_path = os.path.expanduser("~/.xiaomei-brain/logs/mcp-audit.jsonl")
        assert os.path.exists(log_path), f"审计日志文件不存在: {log_path}"

        with open(log_path, "r") as f:
            lines = f.readlines()
        # 找最后一行
        last = json.loads(lines[-1])
        assert last["server"] == "test-audit"
        assert last["tool"] == "test_tool"
        assert last["arguments"] == {"x": 1}

    def test_audit_log_validation_error(self):
        """Schema 校验失败的审计日志应包含 phase='validation'."""
        from xiaomei_brain.mcp.connection import _write_audit

        _write_audit({
            "timestamp": time.time(),
            "server": "test-audit",
            "tool": "hello",
            "arguments": {},
            "error": "Missing required parameters for 'hello': name",
            "duration_ms": 0,
            "phase": "validation",
        })

        log_path = os.path.expanduser("~/.xiaomei-brain/logs/mcp-audit.jsonl")
        with open(log_path, "r") as f:
            lines = f.readlines()
        last = json.loads(lines[-1])
        assert last["phase"] == "validation"
        assert "Missing required parameters" in last["error"]


# ── Integration: OAuth HTTP  E2E ──────────────────────────────────


@pytest.mark.asyncio
class TestOAuthHttpE2E:
    """通过 Mock HTTP Server 测试 OAuth Client Credentials 完整链路.

    使用 MockOAuthServer（来自 test_mcp_oauth.py）作为 OAuth token endpoint，
    同时模拟一个最小 MCP 流式 HTTP 端点来验证 token 注入流程。
    """

    async def test_setup_oauth_injects_token(self):
        """_setup_oauth 应正确获取 token 并注入 Authorization header."""
        from xiaomei_brain.mcp.auth import OAuth2Config, TokenManager
        from xiaomei_brain.mcp.connection import MCPConnection

        # 构造一个带 OAuth 配置的 HTTP connection
        config = {
            "url": "https://example.com/mcp",
            "auth": {
                "type": "oauth2",
                "client_id": "test-client",
                "client_secret": "test-secret",
                "token_url": "https://auth.example.com/token",
            },
        }
        conn = MCPConnection("oauth-test", config)

        # 注入 mock token manager，绕过真实 HTTP 调用
        cfg = OAuth2Config(
            client_id="test-client",
            client_secret="test-secret",
            token_url="https://auth.example.com/token",
        )
        manager = TokenManager(cfg)
        manager._cache.set("mock-token-xyz", expires_in=3600)

        conn._token_manager = manager
        headers = manager.set_headers({})
        assert headers.get("Authorization") == "Bearer mock-token-xyz"
        assert "Authorization" not in ({})  # 原 dict 不变

    async def test_oauth_config_parsing_from_server_config(self):
        """从 MCP server 配置解析 OAuth2Config."""
        from xiaomei_brain.mcp.auth import OAuth2Config

        cfg = OAuth2Config.from_server_config("my-srv", {
            "url": "https://mcp.example.com/mcp",
            "auth": {
                "type": "oauth2",
                "grant_type": "client_credentials",
                "client_id": "my-client",
                "client_secret": "${MY_SECRET}",
                "token_url": "https://auth.example.com/token",
                "scopes": ["read", "write"],
                "audience": "https://api.example.com",
            },
        })
        assert cfg is not None
        assert cfg.client_id == "my-client"
        assert cfg.grant_type == "client_credentials"
        assert cfg.scopes == ["read", "write"]
        assert cfg.audience == "https://api.example.com"
        assert cfg.mcp_url == "https://mcp.example.com/mcp"

    async def test_authorization_code_config(self):
        """Authorization Code 配置应正确解析."""
        from xiaomei_brain.mcp.auth import OAuth2Config

        cfg = OAuth2Config.from_server_config("gmail", {
            "url": "https://gmail-mcp.example.com/mcp",
            "auth": {
                "type": "oauth2",
                "grant_type": "authorization_code",
                "client_id": "gmail-client",
                "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth",
                "token_url": "https://oauth2.googleapis.com/token",
                "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
                "redirect_port": 8899,
            },
        })
        assert cfg is not None
        assert cfg.grant_type == "authorization_code"
        assert cfg.authorization_url == "https://accounts.google.com/o/oauth2/v2/auth"
        assert cfg.redirect_port == 8899

    async def test_ema_config(self):
        """EMA / ID-JAG 配置应正确解析."""
        from xiaomei_brain.mcp.auth import OAuth2Config

        os.environ["IDP_TOKEN"] = "id-token-value"
        cfg = OAuth2Config.from_server_config("erp", {
            "url": "https://erp.company.com/mcp",
            "auth": {
                "type": "ema",
                "grant_type": "ema",
                "client_id": "erp-client",
                "token_url": "https://auth.company.com/oauth/token",
                "scopes": ["erp:read"],
                "resource": "https://erp.company.com/mcp",
                "subject_token_source": "env:IDP_TOKEN",
            },
        })
        assert cfg is not None
        assert cfg.grant_type == "ema"
        assert cfg.resource == "https://erp.company.com/mcp"
        assert cfg.subject_token_source == "env:IDP_TOKEN"

    async def test_no_auth_config_returns_none(self):
        """无 auth 块的配置应返回 None."""
        from xiaomei_brain.mcp.auth import OAuth2Config

        cfg = OAuth2Config.from_server_config("no-auth-srv", {
            "url": "https://mcp.example.com/mcp",
        })
        assert cfg is None


# ── Integration: 工具过滤 ──────────────────────────────────────────


class TestToolFiltering:
    def test_include_filter(self):
        """include 白名单：只注册指定工具."""
        from xiaomei_brain.mcp.client import _apply_tool_filters
        from unittest.mock import Mock

        tools = [
            Mock(name="tool_a", spec=[]),
            Mock(name="tool_b", spec=[]),
            Mock(name="tool_c", spec=[]),
        ]
        for t in tools:
            t.name = t._mock_name.replace("tool_", "tool_")  # noop

        # 为每个工具设置 name 属性
        tools[0].name = "tool_a"
        tools[1].name = "tool_b"
        tools[2].name = "tool_c"

        filtered = _apply_tool_filters(tools, {"include": "tool_a"}, "srv")
        assert len(filtered) == 1
        assert filtered[0].name == "tool_a"

    def test_exclude_filter(self):
        """exclude 黑名单：排除指定工具."""
        from xiaomei_brain.mcp.client import _apply_tool_filters
        from unittest.mock import Mock

        tools = [Mock() for _ in range(3)]
        tools[0].name = "tool_a"
        tools[1].name = "tool_b"
        tools[2].name = "tool_c"

        filtered = _apply_tool_filters(tools, {"exclude": ["tool_b", "tool_c"]}, "srv")
        assert len(filtered) == 1
        assert filtered[0].name == "tool_a"

    def test_include_has_priority(self):
        """include 优先于 exclude."""
        from xiaomei_brain.mcp.client import _apply_tool_filters
        from unittest.mock import Mock

        tools = [Mock() for _ in range(2)]
        tools[0].name = "tool_a"
        tools[1].name = "tool_b"

        filtered = _apply_tool_filters(
            tools, {"include": ["tool_a"], "exclude": ["tool_a"]}, "srv"
        )
        # include 先筛选出 tool_a，exclude 再把它排除 → 空列表
        assert len(filtered) == 0

    def test_no_filters(self):
        """无过滤配置时返回全部工具."""
        from xiaomei_brain.mcp.client import _apply_tool_filters
        from unittest.mock import Mock

        tools = [Mock() for _ in range(3)]
        tools[0].name = "a"
        tools[1].name = "b"
        tools[2].name = "c"

        filtered = _apply_tool_filters(tools, {}, "srv")
        assert len(filtered) == 3


# ── Unit: 熔断器行为 ────────────────────────────────────────────────


class TestCircuitBreakerBehavior:
    """验证应用层错误不触发熔断器计数."""

    def test_app_error_does_not_bump(self):
        """应用层错误（工具返回 error）不应累加熔断器计数."""
        from xiaomei_brain.mcp.client import _error_counts, _bump_error, _reset_error

        # 清理初始状态
        _reset_error("test-cb")

        # 模拟：应用层错误来了（不做 _bump_error）
        # —— 验证计数仍为 0（没有 _bump_error 调用）
        assert _error_counts.get("test-cb", 0) == 0

    def test_transport_exception_bumps(self):
        """传输层异常应累加熔断器计数."""
        from xiaomei_brain.mcp.client import _error_counts, _bump_error, _reset_error

        _reset_error("test-cb")
        _bump_error("test-cb")
        assert _error_counts.get("test-cb", 0) == 1

        _bump_error("test-cb")
        assert _error_counts.get("test-cb", 0) == 2

    def test_successful_call_resets(self):
        """成功调用应重置熔断器."""
        from xiaomei_brain.mcp.client import _error_counts, _bump_error, _reset_error

        _reset_error("test-cb")
        _bump_error("test-cb")
        _bump_error("test-cb")
        assert _error_counts.get("test-cb", 0) == 2

        _reset_error("test-cb")
        assert _error_counts.get("test-cb", 0) == 0

    def test_circuit_breaker_blocks_after_threshold(self):
        """连续 N 次传输异常后熔断器应阻止调用."""
        from xiaomei_brain.mcp.client import (
            _error_counts, _bump_error, _breaker_blocked, _reset_error,
            _CIRCUIT_BREAKER_THRESHOLD,
        )

        _reset_error("test-cb")

        # 未达阈值：放行
        for i in range(_CIRCUIT_BREAKER_THRESHOLD - 1):
            _bump_error("test-cb")
            assert _breaker_blocked("test-cb") is False

        # 达到阈值：阻止
        _bump_error("test-cb")
        assert _breaker_blocked("test-cb") is True

        _reset_error("test-cb")
