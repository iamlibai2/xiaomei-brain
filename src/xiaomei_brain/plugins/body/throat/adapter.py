"""喉咙器官插件 — 将 Throat + RealSpeaker 注册到 Body。"""

from xiaomei_brain.body.sense import Throat
from .real_speaker import RealSpeaker


def register(ctx):
    ctx.register_sense(Throat(), RealSpeaker())
