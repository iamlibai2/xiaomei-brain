"""眼睛器官插件 — 将 Eyes + Camera 注册到 pending_senses。"""

from xiaomei_brain.body.sense import Eyes
from xiaomei_brain.body.device.mock import MockCamera
from .. import _refs


def register(ctx):
    _refs.pending_senses.append((Eyes(), MockCamera()))
    ctx.logger.info("眼睛器官已注册（待 Body 装配）")
