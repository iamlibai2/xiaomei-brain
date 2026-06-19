"""MockCamera - 模拟摄像头，测试用。"""

from __future__ import annotations

from typing import Any

from xiaomei_brain.body.device import Camera


class MockCamera(Camera):
    """模拟摄像头：返回预设的人脸和场景数据。"""

    def __init__(self, source: str = "mock") -> None:
        super().__init__(source=source)
        self._opened = False
        self._face_ids: list[str] = ["face_mock_001"]
        self._scene_text: str = "一个安静的室内场景"
        self._frame_data: bytes = b"mock_frame_data"

    def open(self) -> bool:
        self._opened = True
        return True

    def close(self) -> None:
        self._opened = False

    def is_operational(self) -> bool:
        return self._opened

    def capture(self) -> Any:
        if not self._opened:
            return None
        return self._frame_data

    def set_faces(self, face_ids: list[str]) -> None:
        self._face_ids = face_ids

    def set_scene(self, text: str) -> None:
        self._scene_text = text
