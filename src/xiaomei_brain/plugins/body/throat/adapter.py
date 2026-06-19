"""喉咙器官插件 — 将 Throat + RealSpeaker 注册到 pending_senses。"""

from xiaomei_brain.body.sense import Throat
from xiaomei_brain.body.device.real import RealSpeaker
from .. import _refs


def register(ctx):
    _refs.pending_senses.append((Throat(), RealSpeaker()))
    ctx.logger.info("喉咙器官已注册（RealSpeaker + ffplay）")
