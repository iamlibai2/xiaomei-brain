# Body 身体感官层实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 分三阶段实现 Body 身体感官层——先通路 1（ReAct 工具调用），再替换真实硬件+多模态 LLM，最后扩展到背景感知+主动调用。

---

## 整体路线

```
Phase 1: 路径 1 — ReAct 工具调用（用户驱动）
  用户: "看看现场都有谁" → Agent → look_around tool → eyes.see() / eyes.recognize_faces()
  Mock 设备，管线真实，可测可用。

Phase 2: 真实实现
  Mock → OpenCV 摄像头 + 多模态 LLM 替换 see()
  管线不变，只换底层传感器。

Phase 3: 路径 2 + 路径 3
  L0 body.collect() → L1 sensory_change → L2 emergence
  inject_consciousness 感官渲染
  RawMessage.sensing + Gateway 感官 fallback
```

---

## Phase 1: 路径 1 — ReAct 工具调用

### 文件结构

```
新建:
  src/xiaomei_brain/body/
  ├── __init__.py              # Body 总管
  ├── sense.py                 # Sense ABC + Eyes + Ears + Throat
  ├── device.py                # Device ABC + Camera + Microphone + Speaker
  ├── tools.py                 # create_body_tools() — look_around/listen_to_environment/play_music
  └── device/
      ├── __init__.py
      └── mock.py              # Mock 设备 + Mock 感官

修改:
  src/xiaomei_brain/consciousness/conscious_living.py # Body 创建 + 工具注册 + 生命周期
  src/xiaomei_brain/consciousness/living_commands.py  # CLI: /eyes /ears /see /hear
  src/xiaomei_brain/cli/run.py                        # CLI completion

测试:
  tests/test_body.py
```

---

### Task 1: Device ABC + Camera / Microphone / Speaker 骨架

**Files:**
- Create: `src/xiaomei_brain/body/__init__.py`
- Create: `src/xiaomei_brain/body/device.py`
- Create: `src/xiaomei_brain/body/device/__init__.py`
- Create: `tests/test_body.py`

- [ ] **Step 1: 创建 body 包入口文件**

```python
# src/xiaomei_brain/body/__init__.py
"""Body — 身体感官层。

独立能力层，管理所有感官和物理设备。

三条使用路径（分阶段实现）：
  1. ReAct tool: Agent 主动调用 eyes.see() / eyes.recognize_faces()
  2. 背景感知: L0 body.collect() → L1 anomaly → L2 emergence
  3. 主动探索: L2 agent 工具集中的 body tools
"""

from __future__ import annotations

__all__ = [
    "Body",
    "Sense", "Eyes", "Ears", "Throat",
    "Device", "Camera", "Microphone", "Speaker",
]
```

- [ ] **Step 2: 创建 Device ABC + 三个设备骨架**

```python
# src/xiaomei_brain/body/device.py
"""Device — 物理设备抽象。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Device(ABC):
    """一个物理设备。"""

    device_type: str = ""

    def __init__(self, source: str = "") -> None:
        self.source = source  # "/dev/video0" / "rtsp://..." / "virtual"

    @abstractmethod
    def open(self) -> bool:
        """打开设备。返回 True 表示成功。"""
        ...

    @abstractmethod
    def close(self) -> None:
        """关闭设备。"""
        ...

    @abstractmethod
    def is_operational(self) -> bool:
        """设备是否正常运行。"""
        ...

    @abstractmethod
    def capture(self) -> Any:
        """采集一帧原始数据。"""
        ...


class Camera(Device):
    """摄像头设备。

    Phase 1: MockCamera
    Phase 2: OpenCV + 人脸检测
    """

    device_type = "camera"

    def open(self) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def is_operational(self) -> bool:
        raise NotImplementedError

    def capture(self) -> Any:
        raise NotImplementedError


class Microphone(Device):
    """麦克风设备。

    Phase 1: MockMicrophone
    Phase 4: 语音识别
    """

    device_type = "microphone"

    def open(self) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def is_operational(self) -> bool:
        raise NotImplementedError

    def capture(self) -> Any:
        raise NotImplementedError


class Speaker(Device):
    """扬声器设备。

    Phase 1: MockSpeaker
    Phase 4: 音频播放
    """

    device_type = "speaker"

    def open(self) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def is_operational(self) -> bool:
        raise NotImplementedError

    def capture(self) -> Any:
        raise NotImplementedError
```

- [ ] **Step 3: 创建 device 子包**

```python
# src/xiaomei_brain/body/device/__init__.py
"""Body device 子包。"""
```

- [ ] **Step 4: 编写 Device 基础测试**

```python
# tests/test_body.py
"""Body 身体感官层单元测试。"""
from __future__ import annotations


class TestDeviceABC:
    """Device 抽象基类测试。"""

    def test_camera_is_device(self):
        from xiaomei_brain.body.device import Camera, Device
        assert issubclass(Camera, Device)

    def test_microphone_is_device(self):
        from xiaomei_brain.body.device import Microphone, Device
        assert issubclass(Microphone, Device)

    def test_speaker_is_device(self):
        from xiaomei_brain.body.device import Speaker, Device
        assert issubclass(Speaker, Device)

    def test_camera_device_type(self):
        from xiaomei_brain.body.device import Camera
        assert Camera().device_type == "camera"

    def test_microphone_device_type(self):
        from xiaomei_brain.body.device import Microphone
        assert Microphone().device_type == "microphone"

    def test_speaker_device_type(self):
        from xiaomei_brain.body.device import Speaker
        assert Speaker().device_type == "speaker"

    def test_device_source(self):
        from xiaomei_brain.body.device import Camera
        c = Camera(source="/dev/video0")
        assert c.source == "/dev/video0"

    def test_abstract_methods_raise(self):
        from xiaomei_brain.body.device import Camera
        c = Camera()
        try:
            c.open()
            assert False, "should raise NotImplementedError"
        except NotImplementedError:
            pass

    def test_cannot_instantiate_device_abc(self):
        from xiaomei_brain.body.device import Device
        import pytest
        with pytest.raises(TypeError):
            Device()  # type: ignore[abstract]
```

- [ ] **Step 5: 运行测试**

Run: `PYTHONPATH=src python3 -m pytest tests/test_body.py::TestDeviceABC -v`
Expected: PASS (9 tests)

- [ ] **Step 6: Commit**

```bash
git add src/xiaomei_brain/body/ tests/test_body.py
git commit -m "feat(body): add Device ABC + Camera/Microphone/Speaker stubs"
```

---

### Task 2: Sense ABC + Eyes / Ears / Throat

**Files:**
- Create: `src/xiaomei_brain/body/sense.py`
- Modify: `tests/test_body.py`

- [ ] **Step 1: 创建 Sense ABC + Eyes / Ears / Throat**

核心设计：
- **see(prompt)** — 通用视觉：拍照 → 多模态 LLM 描述（看现场/看风景/看电影/OCR 统一一个方法）
- **recognize_faces()** — 专用识别：本地 CV 检测 → 特征库比对
- **listen(prompt)** — 通用听觉：录音 → 多模态 LLM 分析
- **recognize_voice()** — 专用识别：本地声纹匹配

```python
# src/xiaomei_brain/body/sense.py
"""Sense — 感官抽象。

两种能力模式：
  - 通用感知: see(prompt) / listen(prompt) → 多模态 LLM 描述
  - 专用识别: recognize_faces() / recognize_voice() → 本地特征库比对
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .device import Device


class Sense(ABC):
    """一个感官。"""

    name: str = ""

    def __init__(self) -> None:
        self._device: Device | None = None
        self.online: bool = False

    def setup(self, device: Device) -> None:
        """绑定物理设备。"""
        self._device = device

    def teardown(self) -> None:
        """解绑设备并清理。"""
        if self._device:
            self._device.close()
        self._device = None
        self.online = False

    def is_available(self) -> bool:
        """感官是否可用。"""
        return self.online and self._device is not None and self._device.is_operational()

    @property
    def device(self) -> Device | None:
        return self._device


class Eyes(Sense):
    """看的能力。

    - see(prompt): 通用视觉 → 拍照 → 多模态 LLM 描述
    - recognize_faces(): 人脸识别 → 本地 CV + 特征库比对
    """

    name = "eyes"

    def see(self, prompt: str = "描述这个画面") -> str | None:
        """通用视觉。拍照 → 多模态 LLM 根据 prompt 描述。

        一个方法覆盖所有视觉理解场景：
          - "描述现场环境和人数"    → 看现场
          - "这是什么风格的画面"    → 审美判断
          - "读出画面中的文字"      → OCR
          - "画面里发生了什么事"    → 理解场景

        Phase 1: 返回 mock 描述
        Phase 2: Camera.capture() → 多模态 LLM API
        """
        if not self.is_available():
            return None
        return None  # 子类覆盖

    def recognize_faces(self) -> list[dict]:
        """人脸识别。本地 CV 检测 → 特征提取 → 匹配已知身份。

        返回: [{"face_id": "feat_abc123", "bbox": [x,y,w,h]}, ...]
        face_id 从上层的 IdentityManager 解析为名字/关系。

        Phase 1: 返回 mock 数据
        Phase 2: Camera.capture() → OpenCV 人脸检测 → 特征提取
        """
        if not self.is_available():
            return []
        return []


class Ears(Sense):
    """听的能力。

    - listen(prompt): 通用听觉 → 录音 → 多模态 LLM 分析
    - recognize_voice(): 声纹识别 → 本地特征库比对
    """

    name = "ears"

    def listen(self, prompt: str = "分析这个音频") -> str | None:
        """通用听觉。录音 → 多模态 LLM 根据 prompt 分析。

          - "转写音频内容"           → 语音转文字
          - "说话人的情绪是什么"      → 语气分析
          - "这是什么声音"           → 环境音识别
        """
        if not self.is_available():
            return None
        return None

    def recognize_voice(self) -> str | None:
        """声纹识别。返回 voice_id 或 None。"""
        if not self.is_available():
            return None
        return None


class Throat(Sense):
    """说的能力。"""

    name = "throat"

    def speak(self, text: str) -> None:
        """TTS 朗读。"""
        if not self.is_available():
            return

    def play(self, audio_path: str) -> None:
        """播放音频文件。"""
        if not self.is_available():
            return
```

- [ ] **Step 2: 更新 body/__init__.py 导出 + Body 总管**

```python
# src/xiaomei_brain/body/__init__.py
"""Body — 身体感官层。"""

from __future__ import annotations

from .sense import Sense, Eyes, Ears, Throat
from .device import Device, Camera, Microphone, Speaker

__all__ = [
    "Body", "Sense", "Eyes", "Ears", "Throat",
    "Device", "Camera", "Microphone", "Speaker",
]


class Body:
    """身体层总管。独立生命周期，被 ConsciousLiving 持有。"""

    def __init__(self) -> None:
        self._senses: dict[str, Sense] = {}

    def register_sense(self, sense: Sense, device: Device) -> None:
        """注册一个感官及其关联设备。"""
        sense.setup(device)
        self._senses[sense.name] = sense

    def open(self) -> None:
        """全部感官上线。"""
        for sense in self._senses.values():
            if not sense.is_available():
                sense._device.open()
        for sense in self._senses.values():
            sense.online = True

    def close(self) -> None:
        """全部感官下线。"""
        for sense in self._senses.values():
            sense.teardown()

    @property
    def eyes(self) -> Eyes | None:
        return self._senses.get("eyes")  # type: ignore[return-value]

    @property
    def ears(self) -> Ears | None:
        return self._senses.get("ears")  # type: ignore[return-value]

    @property
    def throat(self) -> Throat | None:
        return self._senses.get("throat")  # type: ignore[return-value]

    def is_available(self, sense_name: str) -> bool:
        sense = self._senses.get(sense_name)
        return sense is not None and sense.is_available()
```

- [ ] **Step 3: 添加 Sense 基础测试**

```python
# 追加到 tests/test_body.py

class TestSenseABC:
    """Sense 抽象基类测试。"""

    def test_eyes_is_sense(self):
        from xiaomei_brain.body.sense import Eyes, Sense
        assert issubclass(Eyes, Sense)

    def test_ears_is_sense(self):
        from xiaomei_brain.body.sense import Ears, Sense
        assert issubclass(Ears, Sense)

    def test_throat_is_sense(self):
        from xiaomei_brain.body.sense import Throat, Sense
        assert issubclass(Throat, Sense)

    def test_eyes_name(self):
        from xiaomei_brain.body.sense import Eyes
        assert Eyes().name == "eyes"

    def test_ears_name(self):
        from xiaomei_brain.body.sense import Ears
        assert Ears().name == "ears"

    def test_throat_name(self):
        from xiaomei_brain.body.sense import Throat
        assert Throat().name == "throat"

    def test_cannot_instantiate_sense_abc(self):
        from xiaomei_brain.body.sense import Sense
        import pytest
        with pytest.raises(TypeError):
            Sense()  # type: ignore[abstract]

    def test_not_available_without_device(self):
        from xiaomei_brain.body.sense import Eyes
        e = Eyes()
        assert e.is_available() is False

    def test_see_returns_none_when_not_available(self):
        from xiaomei_brain.body.sense import Eyes
        e = Eyes()
        assert e.see() is None

    def test_recognize_faces_empty_when_not_available(self):
        from xiaomei_brain.body.sense import Eyes
        e = Eyes()
        assert e.recognize_faces() == []

    def test_listen_returns_none_when_not_available(self):
        from xiaomei_brain.body.sense import Ears
        e = Ears()
        assert e.listen() is None
```

- [ ] **Step 4: 运行测试**

Run: `PYTHONPATH=src python3 -m pytest tests/test_body.py -v`
Expected: PASS (20 tests)

- [ ] **Step 5: Commit**

```bash
git add src/xiaomei_brain/body/ tests/test_body.py
git commit -m "feat(body): add Sense ABC + Eyes/Ears/Throat with see/recognize_faces/listen API"
```

---

### Task 3: Mock 设备 + Mock 感官

**Files:**
- Create: `src/xiaomei_brain/body/device/mock.py`
- Modify: `tests/test_body.py`

- [ ] **Step 1: 创建 Mock 设备 + Mock 感官**

```python
# src/xiaomei_brain/body/device/mock.py
"""Mock 设备 + Mock 感官 — 测试用，不依赖任何硬件。"""

from __future__ import annotations

from typing import Any

from ..device import Camera, Microphone, Speaker
from ..sense import Eyes, Ears, Throat


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


class MockMicrophone(Microphone):
    """模拟麦克风：返回预设的声纹和语音数据。"""

    def __init__(self, source: str = "mock") -> None:
        super().__init__(source=source)
        self._opened = False
        self._voice_id: str | None = "voice_mock_001"
        self._speech_text: str = "你好"
        self._tone: str = "neutral"
        self._audio_data: bytes = b"mock_audio_data"

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
        return self._audio_data

    def set_voice_id(self, voice_id: str | None) -> None:
        self._voice_id = voice_id

    def set_speech(self, text: str) -> None:
        self._speech_text = text

    def set_tone(self, tone: str) -> None:
        self._tone = tone


class MockSpeaker(Speaker):
    """模拟扬声器：记录最后播放的文本和音频路径。"""

    def __init__(self, source: str = "mock") -> None:
        super().__init__(source=source)
        self._opened = False
        self.last_spoken: str | None = None
        self.last_played: str | None = None

    def open(self) -> bool:
        self._opened = True
        return True

    def close(self) -> None:
        self._opened = False

    def is_operational(self) -> bool:
        return self._opened

    def capture(self) -> Any:
        return None

    def speak(self, text: str) -> None:
        self.last_spoken = text

    def play(self, audio_path: str) -> None:
        self.last_played = audio_path


class MockEyes(Eyes):
    """模拟眼睛：从 MockCamera 读取预设数据。"""

    def see(self, prompt: str = "描述这个画面") -> str | None:
        if not self.is_available():
            return None
        device = self.device
        if isinstance(device, MockCamera):
            return f"[mock vision] {device._scene_text}（prompt: {prompt[:50]}）"
        return "[mock vision] default"

    def recognize_faces(self) -> list[dict]:
        if not self.is_available():
            return []
        device = self.device
        if isinstance(device, MockCamera):
            return [{"face_id": fid, "bbox": [0, 0, 100, 100]}
                    for fid in device._face_ids]
        return []


class MockEars(Ears):
    """模拟耳朵：从 MockMicrophone 读取预设数据。"""

    def listen(self, prompt: str = "分析这个音频") -> str | None:
        if not self.is_available():
            return None
        device = self.device
        if isinstance(device, MockMicrophone):
            return f"[mock audio] speech={device._speech_text}, tone={device._tone}（prompt: {prompt[:50]}）"
        return "[mock audio] default"

    def recognize_voice(self) -> str | None:
        if not self.is_available():
            return None
        device = self.device
        if isinstance(device, MockMicrophone):
            return device._voice_id
        return None


class MockThroat(Throat):
    """模拟喉咙：将 TTS/播放文本记录到 MockSpeaker。"""

    def speak(self, text: str) -> None:
        if not self.is_available():
            return
        device = self.device
        if isinstance(device, MockSpeaker):
            device.speak(text)

    def play(self, audio_path: str) -> None:
        if not self.is_available():
            return
        device = self.device
        if isinstance(device, MockSpeaker):
            device.play(audio_path)
```

- [ ] **Step 2: 添加 Mock 设备 + Mock 感官 测试**

```python
# 追加到 tests/test_body.py

class TestMockDevices:
    """Mock 设备测试。"""

    def test_mock_camera_open_close(self):
        from xiaomei_brain.body.device.mock import MockCamera
        c = MockCamera()
        assert c.is_operational() is False
        assert c.open() is True
        assert c.is_operational() is True
        c.close()
        assert c.is_operational() is False

    def test_mock_camera_capture(self):
        from xiaomei_brain.body.device.mock import MockCamera
        c = MockCamera()
        c.open()
        assert c.capture() == b"mock_frame_data"

    def test_mock_camera_set_faces(self):
        from xiaomei_brain.body.device.mock import MockCamera
        c = MockCamera()
        c.set_faces(["face_a", "face_b"])
        assert c._face_ids == ["face_a", "face_b"]

    def test_mock_microphone_open_close(self):
        from xiaomei_brain.body.device.mock import MockMicrophone
        m = MockMicrophone()
        assert m.is_operational() is False
        assert m.open() is True
        assert m.is_operational() is True

    def test_mock_microphone_capture(self):
        from xiaomei_brain.body.device.mock import MockMicrophone
        m = MockMicrophone()
        m.open()
        assert m.capture() == b"mock_audio_data"

    def test_mock_speaker_record_text(self):
        from xiaomei_brain.body.device.mock import MockSpeaker
        s = MockSpeaker()
        s.open()
        s.speak("hello")
        s.play("/path/to/song.mp3")
        assert s.last_spoken == "hello"
        assert s.last_played == "/path/to/song.mp3"


class TestMockSenses:
    """Mock 感官测试。"""

    def test_mock_eyes_see(self):
        from xiaomei_brain.body import Body
        from xiaomei_brain.body.device.mock import MockCamera, MockEyes

        body = Body()
        body.register_sense(MockEyes(), MockCamera())
        body.open()
        result = body.eyes.see("描述这个画面")
        assert "mock vision" in result
        assert "安静的室内场景" in result

    def test_mock_eyes_recognize_faces(self):
        from xiaomei_brain.body import Body
        from xiaomei_brain.body.device.mock import MockCamera, MockEyes

        body = Body()
        camera = MockCamera()
        camera.set_faces(["face_doc", "face_li"])
        body.register_sense(MockEyes(), camera)
        body.open()

        result = body.eyes.recognize_faces()
        assert len(result) == 2
        assert result[0]["face_id"] == "face_doc"

    def test_mock_ears_listen(self):
        from xiaomei_brain.body import Body
        from xiaomei_brain.body.device.mock import MockMicrophone, MockEars

        body = Body()
        mic = MockMicrophone()
        mic.set_speech("你好我是博士")
        mic.set_tone("happy")
        body.register_sense(MockEars(), mic)
        body.open()

        result = body.ears.listen("分析情绪")
        assert "mock audio" in result
        assert "博士" in result
        assert "happy" in result

    def test_mock_ears_recognize_voice(self):
        from xiaomei_brain.body import Body
        from xiaomei_brain.body.device.mock import MockMicrophone, MockEars

        body = Body()
        body.register_sense(MockEars(), MockMicrophone())
        body.open()

        assert body.ears.recognize_voice() == "voice_mock_001"

    def test_mock_throat_speak_and_play(self):
        from xiaomei_brain.body import Body
        from xiaomei_brain.body.device.mock import MockSpeaker, MockThroat

        body = Body()
        speaker = MockSpeaker()
        body.register_sense(MockThroat(), speaker)
        body.open()

        body.throat.speak("hello")
        body.throat.play("/music/song.mp3")
        assert speaker.last_spoken == "hello"
        assert speaker.last_played == "/music/song.mp3"
```

- [ ] **Step 3: 运行全部 body 测试**

Run: `PYTHONPATH=src python3 -m pytest tests/test_body.py -v`
Expected: PASS (31 tests)

- [ ] **Step 4: Commit**

```bash
git add src/xiaomei_brain/body/device/mock.py tests/test_body.py
git commit -m "feat(body): add MockCamera/Microphone/Speaker + MockEyes/Ears/Throat"
```

---

### Task 4: Body 工具 — create_body_tools()

**Files:**
- Create: `src/xiaomei_brain/body/tools.py`
- Modify: `tests/test_body.py`

- [ ] **Step 1: 创建 body/tools.py**

```python
# src/xiaomei_brain/body/tools.py
"""Body 工具 — 注册给 Agent，使 LLM 可以通过工具调用使用身体感官。"""

from __future__ import annotations

from typing import Any


def create_body_tools(
    body: Any = None,
    body_ref: list[Any] | None = None,
    identity_mgr_ref: list[Any] | None = None,
) -> list:
    """创建 Body 相关工具。

    Args:
        body: Body 实例（直接绑定）
        body_ref: 延迟绑定的 [body]（和 purpose_ref 同模式，防止循环引用）
        identity_mgr_ref: 延迟绑定的 [identity_mgr]

    Returns:
        注册到 agent.tools 的工具列表
    """

    def _get_body() -> Any:
        if body is not None:
            return body
        if body_ref and body_ref[0] is not None:
            return body_ref[0]
        return None

    def _get_identity_mgr() -> Any:
        if identity_mgr_ref and identity_mgr_ref[0] is not None:
            return identity_mgr_ref[0]
        return None

    def look_around(prompt: str = "描述你看到的画面和现场情况") -> dict:
        """看看周围。使用眼睛观察当前场景。

        Args:
            prompt: 引导视觉关注什么（如 "看看现场都有谁" / "描述环境氛围"）
        Returns:
            {"faces": [{"face_id": ..., "name": ..., "relation": ...}], "scene": "..."}
        """
        b = _get_body()
        if not b or not b.eyes or not b.eyes.is_available():
            return {"error": "眼睛不可用"}

        # 1. 人脸识别（本地 CV，不需要 LLM）
        faces_raw = b.eyes.recognize_faces()
        mgr = _get_identity_mgr()
        faces = []
        for f in faces_raw:
            fid = f.get("face_id", "")
            info = {"face_id": fid}
            if mgr and fid:
                identity = mgr.resolve(fid)
                if identity:
                    info["name"] = mgr.get_display_name(fid)
                    info["relation"] = identity.get("relation", "未知")
                else:
                    info["name"] = "陌生人"
                    info["relation"] = "未知"
            faces.append(info)

        # 2. 场景描述（多模态 LLM）
        scene = b.eyes.see(prompt)

        return {"faces": faces, "scene": scene}

    def listen_to_environment(prompt: str = "分析听到的声音") -> dict:
        """听听周围。

        Args:
            prompt: 引导听觉关注什么（如 "转写说话内容" / "分析情绪"）
        Returns:
            {"speaker": {"voice_id": ..., "name": ...}, "audio": "..."}
        """
        b = _get_body()
        if not b or not b.ears or not b.ears.is_available():
            return {"error": "耳朵不可用"}

        voice_id = b.ears.recognize_voice()
        mgr = _get_identity_mgr()
        speaker_info = {"voice_id": voice_id}
        if mgr and voice_id:
            identity = mgr.resolve(voice_id)
            if identity:
                speaker_info["name"] = mgr.get_display_name(voice_id)

        audio_result = b.ears.listen(prompt)
        return {"speaker": speaker_info, "audio": audio_result}

    def play_music(audio_path: str) -> dict:
        """播放音频文件。

        Args:
            audio_path: 音频文件路径
        Returns:
            {"played": "..."}
        """
        b = _get_body()
        if not b or not b.throat or not b.throat.is_available():
            return {"error": "喉咙不可用"}
        b.throat.play(audio_path)
        return {"played": audio_path}

    tools = []

    from ..tools.registry import FunctionTool

    tools.append(FunctionTool(
        name="look_around",
        description="看看你周围的环境。识别画面中的人脸（如果熟悉的人会告诉你名字和关系），并描述场景。当你需要看看现场有谁、了解环境时使用。",
        parameters={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "引导视觉关注什么。例如：'看看现场都有谁'、'描述环境氛围'、'这是什么风格的画面'",
                },
            },
        },
        func=look_around,
    ))

    tools.append(FunctionTool(
        name="listen_to_environment",
        description="听听你周围的声音。识别说话人的声纹并转录内容。当你需要听清周围对话时使用。",
        parameters={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "引导听觉关注什么。例如：'转写说话内容'、'分析说话人的情绪'",
                },
            },
        },
        func=listen_to_environment,
    ))

    tools.append(FunctionTool(
        name="play_music",
        description="从本地播放音频文件或音乐。用于唱歌、播放背景音乐等场景。",
        parameters={
            "type": "object",
            "properties": {
                "audio_path": {
                    "type": "string",
                    "description": "音频文件的完整路径",
                },
            },
            "required": ["audio_path"],
        },
        func=play_music,
    ))

    return tools
```

- [ ] **Step 2: 添加工具测试**

```python
# 追加到 tests/test_body.py

class TestBodyTools:
    """Body 工具测试。"""

    def test_look_around_with_mock(self):
        from xiaomei_brain.body import Body
        from xiaomei_brain.body.device.mock import MockCamera, MockEyes
        from xiaomei_brain.body.tools import create_body_tools

        body = Body()
        camera = MockCamera()
        camera.set_faces(["face_doc"])
        body.register_sense(MockEyes(), camera)
        body.open()

        tools = create_body_tools(body=body)
        look_around = [t for t in tools if t.name == "look_around"][0]

        result = look_around.func("描述现场")
        assert len(result["faces"]) == 1
        assert result["faces"][0]["face_id"] == "face_doc"
        assert "mock vision" in result["scene"]

    def test_look_around_with_identity_resolution(self):
        from xiaomei_brain.body import Body
        from xiaomei_brain.body.device.mock import MockCamera, MockEyes
        from xiaomei_brain.body.tools import create_body_tools
        from xiaomei_brain.contacts.manager import IdentityManager
        import tempfile, os

        # 设置身份：face_doc → 博士
        tmpdir = tempfile.mkdtemp()
        yaml_file = os.path.join(tmpdir, "identities.yaml")
        with open(yaml_file, "w") as f:
            f.write("""people:
  - id: boshi
    name: 博士
    relation: 恋人
    alias_ids:
      - face_doc
""")
        mgr = IdentityManager(tmpdir)

        body = Body()
        camera = MockCamera()
        camera.set_faces(["face_doc", "face_stranger"])
        body.register_sense(MockEyes(), camera)
        body.open()

        tools = create_body_tools(body=body, identity_mgr_ref=[mgr])
        look_around = [t for t in tools if t.name == "look_around"][0]

        result = look_around.func()
        assert result["faces"][0]["name"] == "博士"
        assert result["faces"][0]["relation"] == "恋人"
        assert result["faces"][1]["name"] == "陌生人"

    def test_look_around_unavailable(self):
        from xiaomei_brain.body.tools import create_body_tools

        tools = create_body_tools()
        look_around = [t for t in tools if t.name == "look_around"][0]

        result = look_around.func()
        assert "error" in result

    def test_play_music_with_mock(self):
        from xiaomei_brain.body import Body
        from xiaomei_brain.body.device.mock import MockSpeaker, MockThroat
        from xiaomei_brain.body.tools import create_body_tools

        body = Body()
        speaker = MockSpeaker()
        body.register_sense(MockThroat(), speaker)
        body.open()

        tools = create_body_tools(body=body)
        play = [t for t in tools if t.name == "play_music"][0]

        result = play.func("/music/chengdu.mp3")
        assert result["played"] == "/music/chengdu.mp3"
        assert speaker.last_played == "/music/chengdu.mp3"

    def test_listen_to_environment_with_mock(self):
        from xiaomei_brain.body import Body
        from xiaomei_brain.body.device.mock import MockMicrophone, MockEars
        from xiaomei_brain.body.tools import create_body_tools

        body = Body()
        mic = MockMicrophone()
        mic.set_speech("唱得真好")
        mic.set_tone("excited")
        body.register_sense(MockEars(), mic)
        body.open()

        tools = create_body_tools(body=body)
        listen = [t for t in tools if t.name == "listen_to_environment"][0]

        result = listen.func("分析情绪")
        assert "mock audio" in result["audio"]
        assert result["speaker"]["voice_id"] == "voice_mock_001"
```

- [ ] **Step 3: 运行测试**

Run: `PYTHONPATH=src python3 -m pytest tests/test_body.py::TestBodyTools -v`
Expected: PASS (5 tests)

- [ ] **Step 4: Commit**

```bash
git add src/xiaomei_brain/body/tools.py tests/test_body.py
git commit -m "feat(body): add create_body_tools() — look_around/listen_to_environment/play_music"
```

---

### Task 5: Body 生命周期接入 ConsciousLiving + 工具注册

**Files:**
- Modify: `src/xiaomei_brain/consciousness/conscious_living.py`

- [ ] **Step 1: 在 __init__ 末尾添加 Body 创建 + 工具注册**

在 `conscious_living.py` 的 `__init__()` 方法中，Gateway 创建之后（约第 504 行 `logger.info("[ConsciousLiving] Gateway 入站门已创建")` 之后）添加：

```python
        # ── Body 身体感官层（Phase 1: Mock 设备）─────────────────
        from ..body import Body
        from ..body.device.mock import MockCamera, MockMicrophone, MockSpeaker
        from ..body.device.mock import MockEyes, MockEars, MockThroat

        self.body = Body()
        self.body.register_sense(MockEyes(), MockCamera())
        self.body.register_sense(MockEars(), MockMicrophone())
        self.body.register_sense(MockThroat(), MockSpeaker())

        # 注册 Body 工具到 Agent（look_around / listen_to_environment / play_music）
        from ..body.tools import create_body_tools
        body_ref = [self.body]
        identity_mgr_ref = [self._identity_mgr]
        for body_tool in create_body_tools(body_ref=body_ref, identity_mgr_ref=identity_mgr_ref):
            self.agent.tools.register(body_tool)

        logger.info("[ConsciousLiving] Body 身体感官层已创建（Mock 模式），工具已注册")
```

- [ ] **Step 2: 在 _on_wake() 中打开 Body**

在 `_on_wake` 方法中 `# 火焰点燃` 行之后添加：

```python
        # 唤醒身体感官
        body = getattr(self, 'body', None)
        if body:
            body.open()
            logger.info("[ConsciousLiving] Body 感官已上线")
```

- [ ] **Step 3: 在 _on_stop() 中关闭 Body**

在 `_on_stop` 方法中，`self._gateway_inbound.close_channels()` 之后添加：

```python
        # 关闭身体感官
        body = getattr(self, 'body', None)
        if body:
            body.close()
            logger.info("[ConsciousLiving] Body 感官已下线")
```

- [ ] **Step 4: 验证语法**

Run: `python3 -c "import ast; ast.parse(open('src/xiaomei_brain/consciousness/conscious_living.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/xiaomei_brain/consciousness/conscious_living.py
git commit -m "feat: wire Body lifecycle into ConsciousLiving + register body tools"
```

---

### Task 6: CLI 测试命令 + 最终验证

**Files:**
- Modify: `src/xiaomei_brain/consciousness/living_commands.py`
- Modify: `src/xiaomei_brain/cli/run.py`

- [ ] **Step 1: 添加 CLI 命令 handler**

在 `living_commands.py` 末尾添加：

```python
def _cmd_eyes(living, args: str) -> None:
    """显示眼睛状态。"""
    body = getattr(living, 'body', None)
    if not body:
        print("\n\033[33mBody 层未加载\033[0m", flush=True)
        return
    eyes = body.eyes
    if not eyes:
        print("\n\033[33m眼睛未注册\033[0m", flush=True)
        return
    available = eyes.is_available()
    status = "\033[32m在线\033[0m" if available else "\033[31m离线\033[0m"
    print(f"\n眼睛 [{eyes.name}]: {status}", flush=True)
    if available:
        faces = eyes.recognize_faces()
        face_str = ", ".join(f.get("face_id", "?") for f in faces) if faces else "无人"
        print(f"  人脸: {face_str}", flush=True)


def _cmd_ears(living, args: str) -> None:
    """显示耳朵状态。"""
    body = getattr(living, 'body', None)
    if not body:
        print("\n\033[33mBody 层未加载\033[0m", flush=True)
        return
    ears = body.ears
    if not ears:
        print("\n\033[33m耳朵未注册\033[0m", flush=True)
        return
    available = ears.is_available()
    status = "\033[32m在线\033[0m" if available else "\033[31m离线\033[0m"
    print(f"\n耳朵 [{ears.name}]: {status}", flush=True)
    if available:
        voice_id = ears.recognize_voice()
        print(f"  voice_id: {voice_id or '未识别'}", flush=True)


def _cmd_see(living, args: str) -> None:
    """看当前场景。"""
    body = getattr(living, 'body', None)
    if not body or not body.eyes:
        print("\n\033[33m眼睛不可用\033[0m", flush=True)
        return
    if not body.eyes.is_available():
        print("\n\033[31m眼睛离线\033[0m", flush=True)
        return
    scene = body.eyes.see(args or "描述这个画面")
    faces = body.eyes.recognize_faces()
    print(f"\n场景: {scene or '无'}", flush=True)
    if faces:
        identity_mgr = getattr(living, '_identity_mgr', None)
        for f in faces:
            fid = f.get("face_id", "")
            name = identity_mgr.get_display_name(fid) if identity_mgr else ""
            print(f"  人脸: {name or fid}", flush=True)
    print(flush=True)


def _cmd_hear(living, args: str) -> None:
    """听周围声音。"""
    body = getattr(living, 'body', None)
    if not body or not body.ears:
        print("\n\033[33m耳朵不可用\033[0m", flush=True)
        return
    if not body.ears.is_available():
        print("\n\033[31m耳朵离线\033[0m", flush=True)
        return
    result = body.ears.listen(args or "分析音频")
    voice_id = body.ears.recognize_voice()
    print(f"\n音频: {result or '无'}", flush=True)
    print(f"声纹: {voice_id or '未识别'}", flush=True)
```

- [ ] **Step 2: 注册命令到 COMMAND_REGISTRY**

在 `COMMAND_REGISTRY` 字典末尾添加：

```python
    "/eyes": (_cmd_eyes, False),
    "/ears": (_cmd_ears, False),
    "/see": (_cmd_see, True),    # 支持 /see 描述这个画面
    "/hear": (_cmd_hear, True),  # 支持 /hear 分析情绪
```

- [ ] **Step 3: CLI completion 列表**

编辑 `src/xiaomei_brain/cli/run.py`，在 `_COMMANDS` 列表中添加：

```python
"/eyes", "/ears", "/see", "/hear",
```

- [ ] **Step 4: 运行全量 body 测试**

Run: `PYTHONPATH=src python3 -m pytest tests/test_body.py -v`
Expected: ALL PASS (36 tests)

- [ ] **Step 5: 运行现有测试套件确认无回归**

Run: `PYTHONPATH=src python3 -m pytest tests/ -x -q -k "not (llm or e2e or ws_ or feishu or integration or sleeping or wake or pace or goal_loop or pmm or phase2 or anthropic)" --ignore=tests/test_learning_queue.py 2>&1 | tail -10`
Expected: all pass

- [ ] **Step 6: Body 端到端验证**

Run:
```bash
PYTHONPATH=src python3 -c "
from xiaomei_brain.body import Body
from xiaomei_brain.body.device.mock import MockCamera, MockMicrophone, MockSpeaker, MockEyes, MockEars, MockThroat
from xiaomei_brain.body.tools import create_body_tools
from xiaomei_brain.contacts.manager import IdentityManager
import tempfile, os

# 1. Body 生命周期
body = Body()
body.register_sense(MockEyes(), MockCamera())
body.register_sense(MockEars(), MockMicrophone())
body.register_sense(MockThroat(), MockSpeaker())
body.open()
print('1. Body open: eyes=%s ears=%s throat=%s' % (
    body.is_available('eyes'), body.is_available('ears'), body.is_available('throat')
))

# 2. 感官调用
faces = body.eyes.recognize_faces()
scene = body.eyes.see('描述现场')
print('2. Eyes: faces=%s scene=%s' % (faces, scene[:50]))

# 3. 工具调用
# 3a. look_around（无身份管理器）
tools = create_body_tools(body=body)
look_around = [t for t in tools if t.name == 'look_around'][0]
result = look_around.func()
print('3a. look_around: faces=%d scene=%s' % (len(result['faces']), result['scene'][:50]))

# 3b. look_around（有身份管理器）
tmpdir = tempfile.mkdtemp()
yaml_file = os.path.join(tmpdir, 'identities.yaml')
with open(yaml_file, 'w') as f:
    f.write('''people:
  - id: boshi
    name: 博士
    relation: 恋人
    alias_ids:
      - face_mock_001
''')
mgr = IdentityManager(tmpdir)
tools2 = create_body_tools(body=body, identity_mgr_ref=[mgr])
look_around2 = [t for t in tools2 if t.name == 'look_around'][0]
result2 = look_around2.func()
print('3b. look_around with identity: faces=%s' % result2['faces'])

# 3c. play_music
play = [t for t in tools if t.name == 'play_music'][0]
r = play.func('/music/chengdu.mp3')
print('3c. play_music: %s' % r)

body.close()
print('4. Body closed: eyes=%s' % body.is_available('eyes'))
print()
print('ALL VERIFICATIONS PASSED')
"
```
Expected: `ALL VERIFICATIONS PASSED`

- [ ] **Step 7: Commit**

```bash
git add src/xiaomei_brain/consciousness/living_commands.py src/xiaomei_brain/cli/run.py
git commit -m "feat: add /eyes /ears /see /hear CLI commands for Body sensory inspection"
```

---

## Phase 2: 真实实现（后续）

Phase 1 全部 Mock 跑通后，Phase 2 替换底层：

1. **RealCamera** (OpenCV) — 继承 Camera，open() 打开摄像头，capture() 返回 frame
2. **Eyes.see() 真实版** — frame → base64 → 多模态 LLM API（GPT-4o / Claude Vision / 智谱 GLM-4V）
3. **Eyes.recognize_faces() 真实版** — OpenCV 人脸检测 + 特征提取
4. **替换 Mock** — `conscious_living.py` 中 Mock → Real 3 行

管线零改动。`see()` 接口不变，只是底层从 `return f"[mock] {preset}"` 变成 `return multimodal_llm.chat(image, prompt)`。

---

## Phase 3: 路径 2 + 路径 3（后续）

Phase 2 跑通后，扩展背景感知和主动调用：

1. **SelfPerception.sensory_perceptions** — 新字段 + `contribute_sensory_perception()`
2. **L0 body.collect()** — 每秒采样，变化检测，推入 SelfImage
3. **L1 detect_anomaly()** — 加 `sensory_change` 检测
4. **inject_consciousness** — 加 `_render_sensory_perception()` 渲染段
5. **L2 EXPLORE_TOOL_NAMES** — 加 `look_around` 让 L2 主动探索
6. **RawMessage.sensing** — Gateway 感官 fallback

设计已在之前的 spec 中完整定义，Phase 1 的真实代码为 Phase 3 提供了所有基础接口。
