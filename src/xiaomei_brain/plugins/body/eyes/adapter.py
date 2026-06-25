"""眼睛器官插件 — 将 Eyes + RealCamera 注册到 Body。"""

from xiaomei_brain.body.sense import Eyes
from .real_camera import RealCamera

import logging
logger = logging.getLogger(__name__)


def register(ctx):
    cam = RealCamera()
    if cam.open():
        ctx.register_sense(Eyes(), cam)
        logger.info("眼睛已就绪（RealCamera）")
    else:
        logger.warning("RealCamera 不可用，回退 MockCamera")
        from .mock_camera import MockCamera
        ctx.register_sense(Eyes(), MockCamera())
