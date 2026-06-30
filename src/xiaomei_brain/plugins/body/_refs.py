"""Body 工具延迟绑定引用。

body_ref / identity_mgr_ref / living_ref: 供 tools/ 插件使用，由 conscious_living 填充。
器官注册已迁移到 ctx.register_sense()，见 plugin/context.py。
"""

body_ref: list = [None]
identity_mgr_ref: list = [None]
living_ref: list = [None]
