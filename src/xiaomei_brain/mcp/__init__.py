"""MCP (Model Context Protocol) Client — 连接外部 MCP Server，发现工具，注册到 Agent。

支持 stdio 和 HTTP/SSE 传输，安全连接在后台 asyncio 事件循环中。
参考 Hermes Agent 的 MCP 实现模式。
"""
