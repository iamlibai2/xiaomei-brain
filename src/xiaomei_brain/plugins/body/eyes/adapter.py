"""眼睛器官插件 — 将 Eyes + MockCamera 注册到 Body。"""

from xiaomei_brain.body.sense import Eyes
from .mock_camera import MockCamera


def register(ctx):
    ctx.register_sense(Eyes(), MockCamera())
