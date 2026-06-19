"""耳朵器官插件 — 将 Ears + Microphone 注册到 pending_senses。"""

from xiaomei_brain.body.sense import Ears
from xiaomei_brain.body.device.mock import MockMicrophone
from .. import _refs


def register(ctx):
    _refs.pending_senses.append((Ears(), MockMicrophone()))
    ctx.logger.info("耳朵器官已注册（待 Body 装配）")
