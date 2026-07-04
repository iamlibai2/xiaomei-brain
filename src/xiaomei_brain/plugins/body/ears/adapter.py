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
    # 检查 ears_enabled 配置：禁用时不初始化麦克风
    agent_id = getattr(ctx, 'agent_id', '') or ''
    if agent_id:
        from xiaomei_brain.consciousness.living_commands import load_ears_enabled
        if not load_ears_enabled(agent_id):
            logger.info("ears_enabled=false，跳过耳朵初始化")
            return

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

        mic = Device()
        if mic.open():
            ctx.register_sense(Ears(), mic)
            logger.info("耳朵已就绪（%s）", Device.__name__)
        else:
            logger.warning("%s 不可用", Device.__name__)
    except Exception as e:
        logger.warning("耳朵插件初始化失败（%s），跳过", e)
