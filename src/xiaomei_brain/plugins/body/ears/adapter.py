"""耳朵器官插件 — 将 Ears + RealMicrophone 注册到 Body。"""

from xiaomei_brain.body.sense import Ears
from .real_microphone import RealMicrophone

import logging
logger = logging.getLogger(__name__)


def register(ctx):
    mic = RealMicrophone()
    if mic.open():
        ctx.register_sense(Ears(), mic)
        logger.info("耳朵已就绪（RealMicrophone）")
    else:
        logger.warning("RealMicrophone 不可用")
