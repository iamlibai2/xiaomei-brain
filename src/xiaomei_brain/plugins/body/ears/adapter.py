"""耳朵器官插件 — 将 Ears + Microphone 注册到 Body。

平台分发：
- WSL2  → powershell.exe waveIn API 桥接
- Windows/macOS/Linux → PyAudio（Phase 4 实现，当前不可用）
"""

import logging
import sys

from xiaomei_brain.body.sense import Ears

logger = logging.getLogger(__name__)


def register(ctx):
    # 始终初始化麦克风，ears.enabled 仅控制运行时 contribute_to()/capture_raw()
    # 这样 /ears on/off 同一会话无需重启。
    agent_id = getattr(ctx, 'agent_id', '') or ''
    ears_enabled = True
    if agent_id:
        from xiaomei_brain.consciousness.living_commands import load_ears_enabled
        ears_enabled = load_ears_enabled(agent_id)

    try:
        from xiaomei_brain.cli.platform_utils import is_wsl2

        if is_wsl2():
            from .wsl2 import RealMicrophone as Device
        elif sys.platform == "win32":
            from .windows import RealMicrophone as Device
        elif sys.platform == "darwin":
            from .linux import RealMicrophone as Device  # macOS 复用 Linux PyAudio 实现
        else:
            from .linux import RealMicrophone as Device

        ears = Ears()
        ears.enabled = ears_enabled

        mic = Device()
        if mic.open():
            ctx.register_sense(ears, mic)
            logger.info("耳朵已就绪（%s）", Device.__name__)
        else:
            logger.warning("%s 不可用", Device.__name__)
    except Exception as e:
        logger.warning("耳朵插件初始化失败（%s），跳过", e)
