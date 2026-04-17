"""File Watcher - 跨平台文件监听，实现热重载"""

import os
import threading
import time
from typing import Callable


class FileWatcher:
    """文件监听器

    使用 polling 方式监听文件变化（兼容 Linux/macOS/Windows）
    相比 inotify/FSEvents 更简单，无需额外依赖

    Args:
        path: 要监听的文件路径
        callback: 文件变化时的回调函数
        poll_interval: 轮询间隔（秒），默认 1 秒
    """

    def __init__(
        self,
        path: str,
        callback: Callable[[], None],
        poll_interval: float = 1.0
    ):
        self.path = os.path.expanduser(path)
        self.callback = callback
        self.poll_interval = poll_interval
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_mtime: float = 0
        self._debounce_ms: int = 500
        self._last_trigger: float = 0

    def start(self) -> None:
        """启动文件监听"""
        if self._running:
            return

        self._running = True

        # 获取初始 mtime
        if os.path.exists(self.path):
            self._last_mtime = os.path.getmtime(self.path)

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """停止文件监听"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        """监听循环"""
        while self._running:
            try:
                self._check()
            except Exception:
                pass
            time.sleep(self.poll_interval)

    def _check(self) -> None:
        """检查文件是否有变化"""
        if not os.path.exists(self.path):
            return

        current_mtime = os.path.getmtime(self.path)

        if current_mtime != self._last_mtime:
            self._last_mtime = current_mtime

            # Debounce：防止短时间内多次触发
            now = time.time() * 1000
            if now - self._last_trigger < self._debounce_ms:
                return
            self._last_trigger = now

            # 触发回调
            try:
                self.callback()
            except Exception:
                pass
