"""listen_to_environment 工具插件 — 调用 body.ears 听觉感知。"""


def register(ctx):
    from xiaomei_brain.body.tools import create_body_tools
    from xiaomei_brain.plugins.body._refs import body_ref, identity_mgr_ref

    tools = create_body_tools(body_ref=body_ref, identity_mgr_ref=identity_mgr_ref)
    for tool in tools:
        if tool.name == "listen_to_environment":
            tool.source = "plugin:listen_to_environment"
            tool.optional = True
            tool.category = "body"
            ctx.register_agent_tool(tool)
            break
