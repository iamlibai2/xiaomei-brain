"""Body 工具延迟绑定引用。

body_ref / identity_mgr_ref: 供 tools/ 插件使用，由 conscious_living 填充
pending_senses: 供 body/ 器官插件使用，由 conscious_living 消费后装配到 Body
"""

body_ref: list = [None]
identity_mgr_ref: list = [None]

# 器官插件在此注册 (Sense实例, Device实例)
# conscious_living 创建 Body 后遍历此列表装配器官
pending_senses: list = []
