"""喉咙器官插件 — 将 Throat + Speaker 注册到 pending_senses。"""

from xiaomei_brain.body.sense import Throat
from xiaomei_brain.body.device.mock import MockSpeaker
from .. import _refs


def register(ctx):
    _refs.pending_senses.append((Throat(), MockSpeaker()))
    ctx.logger.info("喉咙器官已注册（待 Body 装配）")
