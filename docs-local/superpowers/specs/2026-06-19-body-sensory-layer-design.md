# Body 身体感官层设计

## 背景

当前 xiaomei-brain 的身份识别完全依赖渠道 peer_id（飞书 open_id、CLI 登录名等），
无法像人类一样通过"看脸""听声"来识别说话人。此外，脑架构中也缺少"身体能力层"
——摄像头、麦克风、扬声器等硬件能力没有统一的抽象。

## 设计理念

Body 是独立的能力层，不是 Gateway 的附属。它管理所有感官（眼耳鼻舌身）和物理
设备（摄像头/麦克风/扬声器），供 Gateway、Consciousness、Channels 调用。

```
文字 channel（飞书/钉钉/微信）
  → 感官带宽：无
  → 识别方式：peer_id（账号）

语音 channel（电话/语音消息）
  → 感官带宽：声音
  → 识别方式：peer_id + 声纹 → 双重确认

当面 channel
  → 感官带宽：全感官
  → 识别方式：peer_id + 人脸 + 声纹 → 多重确认
```

## 架构

```
                        意识层 Consciousness
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
     Body (身体层)        Gateway (入站)       Channels (消息)
     ┌──────────┐        ┌──────────┐        ┌──────────┐
     │ Eyes     │        │ accept() │        │ feishu   │
     │ Ears     │        │          │        │ dingtalk │
     │ Throat   │        └──────────┘        │ ws       │
     │ (future) │                             │ cli      │
     └──────────┘                             └──────────┘
          │                                        │
     ┌──────────┐                                  │
     │ Devices  │    USB/树莓派/模拟               │
     │ Camera   │                                  │
     │ Mic      │                                  │
     │ Speaker  │                                  │
     └──────────┘                                  │
                                                   │
          ┌────────────────────────────────────────┘
          │
     IdentityManager (alias_ids)
          │
     face_id / voice_id → 身份
```

## 层次

```
Body
├── Body (总管)          — 注册/启停/健康检查
│   ├── Sense (抽象)     — 每个感官的 ABC
│   │   ├── Eyes         — 看
│   │   ├── Ears         — 听
│   │   └── Throat       — 说
│   └── Device (抽象)   — 每个物理设备的 ABC
│       ├── Camera       — USB / 树莓派
│       ├── Microphone   — 系统麦克风
│       └── Speaker      — 系统扬声器
```

## 核心类型

### Sense 抽象

```python
class Sense(ABC):
    """一个感官。"""
    name: str

    def setup(self, device: Device) -> None: ...
    def teardown(self) -> None: ...
    def is_available(self) -> bool: ...


class Eyes(Sense):
    """看的能力。"""
    name = "eyes"

    # 身份相关
    def see_face(self) -> str | None       # → face_id（用于识别）

    # 环境感知
    def see_scene(self) -> str | None      # → 场景描述

    # 文字识别
    def read_text(self) -> str | None      # → OCR 结果


class Ears(Sense):
    """听的能力。"""
    name = "ears"

    def hear_voice(self) -> str | None     # → voice_id（用于识别）
    def hear_speech(self) -> str | None    # → 转文字
    def hear_tone(self) -> str | None      # → 语气


class Throat(Sense):
    """说的能力。"""
    name = "throat"

    def speak(self, text: str) -> None     # → TTS 播放
```

### Device 抽象

```python
class Device(ABC):
    """一个物理设备。"""
    device_type: str
    source: str                            # /dev/video0 / 0 / rtsp://...

    def open(self) -> bool: ...
    def close(self) -> None: ...
    def is_operational(self) -> bool: ...
    def capture(self) -> Any: ...          # 采集一帧原始数据


class Camera(Device):
    device_type = "camera"


class Microphone(Device):
    device_type = "microphone"


class Speaker(Device):
    device_type = "speaker"
```

### Body 总管

```python
class Body:
    """身体层总管。独立生命周期，被 ConsciousLiving 持有。"""

    def __init__(self):
        self._senses: dict[str, Sense] = {}
        self._devices: dict[str, Device] = {}

    def register_sense(self, sense: Sense, device: Device) -> None: ...
    def open(self) -> None:          # 全部感官上线
    def close(self) -> None:         # 全部感官下线

    @property
    def eyes(self) -> Eyes | None: ...
    @property
    def ears(self) -> Ears | None: ...
    @property
    def throat(self) -> Throat | None: ...
```

## 调用方集成

### Gateway — 识人

```python
def _resolve_identity(self, peer_id: str, sensing: dict | None = None):
    """先走 peer_id，再走 Body 感官线索。"""
    if peer_id and self._identity_mgr:
        entry = self._identity_mgr.resolve(peer_id)
        if entry:
            return entry["name"]

    if sensing:
        body = getattr(self._living, 'body', None)
        if body and body.eyes and body.eyes.is_available():
            face_id = sensing.get("face_id")
            if face_id and self._identity_mgr:
                entry = self._identity_mgr.resolve(face_id)
                if entry:
                    return entry["name"]

    return ""
```

### Channel — 采集感官数据附到消息上

```python
def on_message(self, text):
    body = self._living.body
    sensing = {}
    if body and body.eyes:
        sensing["face_id"] = body.eyes.see_face()
    if body and body.ears:
        sensing["voice_id"] = body.ears.hear_voice()

    self._gateway.accept(RawMessage(
        content=text, source="human", channel="camera-chat",
        peer_id=None,
        sensing=sensing,
    ))
```

### Consciousness — 感知环境

```python
def tick(self):
    if self.body and self.body.eyes:
        scene = self.body.eyes.see_scene()
        self.self_image.body.current_scene = scene
```

## RawMessage 扩展

```python
@dataclass
class RawMessage:
    content: str
    source: str = ""
    channel: str = "cli"
    peer_id: str = ""
    peer_type: str = "human"
    images: list[str] = field(default_factory=list)
    urgent: bool = False
    session_id: str = ""
    sensing: dict = field(default_factory=dict)  # 新增
    # sensing["face_id"]: str   — Eyes 识别结果
    # sensing["voice_id"]: str  — Ears 识别结果
```

## IdentityManager 扩展

alias_ids 映射已实现，Body 产出的 face_id / voice_id 就是 alias：

```yaml
people:
  - id: boshi
    name: 博士
    relation: 恋人
    alias_ids:
      - face_feat_abc123    # 人脸特征
      - voice_feat_def456   # 声纹特征
```

## 实现计划

### Phase 1: 框架（不依赖任何硬件）
1. `body/__init__.py` — Body 总管
2. `body/sense.py` — Sense ABC + Eyes / Ears / Throat 骨架
3. `body/device.py` — Device ABC + Camera / Microphone / Speaker 骨架
4. `body/device/mock.py` — MockCamera / MockMicrophone / MockSpeaker（测试用）
5. Body 接入 ConsciousLiving — 创建 + 启停

### Phase 2: 第一个真实设备（眼睛）
6. `body/device/camera.py` — OpenCV 实现，USB 摄像头
7. `body/sense/eyes.py` — 人脸检测 → embedding → 比对 → face_id
8. 已知人脸库（拍摄几张照片注册）

### Phase 3: Gateway + Channel 集成
9. RawMessage 加 sensing 字段
10. Gateway._resolve_identity() 支持感官 fallback
11. CLI 测试命令: `/eyes` `/ears` `/see`

### Phase 4: 其他感官
12. Ears — 麦克风 + 声纹
13. Throat — TTS 播放

## 验证

```bash
# 1. Body 生命周期
PYTHONPATH=src python3 -c "
from xiaomei_brain.body import Body
from xiaomei_brain.body.device.mock import MockCamera, MockMicrophone, MockSpeaker
from xiaomei_brain.body.sense import Eyes, Ears, Throat

body = Body()
body.register_sense(Eyes(), MockCamera())
body.register_sense(Ears(), MockMicrophone())
body.register_sense(Throat(), MockSpeaker())
body.open()
print('Eyes available:', body.eyes.is_available())
print('Ears available:', body.ears.is_available())
body.close()
"

# 2. Gateway 感官识别
PYTHONPATH=src python3 -m pytest tests/test_body.py -v

# 3. 现有测试无回归
PYTHONPATH=src python3 -m pytest tests/ -x -q
```

## 不做的事

- 人脸识别算法细节（具体用 opencv / insightface 等留到实现时决定）
- 声纹识别算法细节
- 树莓派硬件适配（Phase 2 之后）
- 鼻/舌/身（等有实际需求时再加）
- Body 的 LLM 自主调用（先暴露 API，人类通过命令手动使用）
