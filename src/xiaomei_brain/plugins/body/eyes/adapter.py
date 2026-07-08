"""眼睛器官插件 — 将 Eyes + Camera 注册到 Body。

平台分发：
- WSL2  → powershell.exe Camera App 桥接
- Windows/macOS/Linux → cv2（Phase 3/4 实现，当前回落 MockCamera）
"""

import logging
import sys

from xiaomei_brain.body.sense import Eyes

logger = logging.getLogger(__name__)


def register(ctx):
    # 始终初始化摄像头，eyes.enabled 仅控制运行时 see()/recognize_faces()
    # 这样 /eyes on/off 同一会话无需重启。
    agent_id = getattr(ctx, 'agent_id', '') or ''
    eyes_enabled = True
    if agent_id:
        from xiaomei_brain.consciousness.living_commands import load_eyes_enabled
        eyes_enabled = load_eyes_enabled(agent_id)

    from xiaomei_brain.cli.platform_utils import is_wsl2

    if is_wsl2():
        from .wsl2 import RealCamera as Device
    elif sys.platform == "win32":
        from .windows import RealCamera as Device
    elif sys.platform == "darwin":
        from .linux import RealCamera as Device  # macOS 复用 Linux cv2 实现
    else:
        from .linux import RealCamera as Device

    eyes = Eyes()
    eyes.enabled = eyes_enabled

    cam = Device()
    if cam.open():
        ctx.register_sense(eyes, cam)
        logger.info("眼睛已就绪（%s）", Device.__name__)
    else:
        logger.warning("%s 不可用，回退 MockCamera", Device.__name__)
        from .mock import MockCamera
        ctx.register_sense(eyes, MockCamera())
