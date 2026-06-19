"""耳朵器官插件 — 将 Ears + MockMicrophone 注册到 Body。"""

from xiaomei_brain.body.sense import Ears
from .mock_microphone import MockMicrophone


def register(ctx):
    ctx.register_sense(Ears(), MockMicrophone())
