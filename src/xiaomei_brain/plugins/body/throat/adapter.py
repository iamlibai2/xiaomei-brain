"""喉咙器官插件 — 将 Throat + Speaker 注册到 Body。

平台分发：
- WSL2    → powershell.exe SoundPlayer / wmplayer 桥接
- Windows → winsound + SoundPlayer
- macOS   → afplay（内置，零依赖）
- Linux   → ffplay / PulseAudio
"""

import logging
import sys

from xiaomei_brain.body.sense import Throat

logger = logging.getLogger(__name__)


def register(ctx):
    from xiaomei_brain.cli.platform_utils import is_wsl2

    if is_wsl2():
        from .wsl2 import RealSpeaker as Device
    elif sys.platform == "win32":
        from .windows import RealSpeaker as Device
    elif sys.platform == "darwin":
        from .darwin import RealSpeaker as Device
    else:
        from .linux import RealSpeaker as Device

    ctx.register_sense(Throat(), Device())
    logger.info("喉咙已就绪（%s）", Device.__name__)
