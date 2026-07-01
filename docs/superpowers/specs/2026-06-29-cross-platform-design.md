# 多平台兼容设计

## 目标

xiaomei-brain 在 **Linux native / Windows / WSL2 / macOS** 四个平台上均能以"场景 A"（本地完整 Body 体验）运行。后续加新平台只需新增 Device 子类。

## 设计原则

- **Component-first**：文件夹按功能（eyes/ears/throat），文件按平台（linux.py / windows.py / wsl2.py / darwin.py）
- **核心逻辑零改动**：Sense 层、工具层、意识层不需要感知平台差异
- **WSL2 是独立平台**：内核是 Linux 但硬件访问方式与原生 Linux 完全不同（powershell 桥接 vs /dev 设备）
- **一次只做一个平台**：先 Windows 原生（有测试机），架构预留 macOS/Linux 位置

## 平台矩阵

| 平台 | sys.platform | WSL2 检测 | 摄像头 | 麦克风 | 音箱 |
|------|-------------|----------|--------|--------|------|
| Windows 原生 | `win32` | — | cv2 | PyAudio | SoundPlayer |
| WSL2 | `linux` | `/proc/version` 含 Microsoft | powershell CameraApp | powershell waveIn | ffplay |
| Linux 原生 | `linux` | 不是 WSL2 | cv2 | PyAudio | ffplay |
| macOS | `darwin` | — | cv2 | PyAudio | afplay |

## 目录结构

### CLI 层：包装平台差异

```
src/xiaomei_brain/cli/
├── platform_utils.py        # 新增 — 平台检测 + 跨平台函数
│   readline_import()        #   → readline / pyreadline3
│   get_single_char()        #   → termios.tty / msvcrt
│   select_stdin(timeout)    #   → select.select / msvcrt.kbhit
│   is_wsl2()                #   → WSL2 检测
│   send_signal(pid, sig)    #   → os.kill 兼容封装
└── ...
```

### Body 层：Component-first 重组

```
plugins/body/
├── eyes/
│   ├── adapter.py           # 不改
│   ├── linux.py             # 新增 — cv2 CameraDevice
│   ├── windows.py           # 新增 — cv2 CameraDevice
│   ├── wsl2.py              # 重命名自 real_camera.py
│   └── mock.py              # 重命名自 mock_camera.py
├── ears/
│   ├── adapter.py           # 不改
│   ├── linux.py             # 新增 — PyAudio MicrophoneDevice
│   ├── windows.py           # 新增 — PyAudio MicrophoneDevice
│   ├── wsl2.py              # 重命名自 real_microphone.py
│   └── mock.py              # 重命名自 mock_microphone.py
├── throat/
│   ├── adapter.py           # 不改
│   ├── linux.py             # 新增 — ffplay SpeakerDevice
│   ├── windows.py           # 新增 — SoundPlayer SpeakerDevice
│   ├── wsl2.py              # 从 real_speaker.py 拆出 WSL2 部分
│   └── mock.py              # 已有
├── touch/
│   ├── adapter.py           # 不改
│   ├── wsl2.py              # 现有 scroll_sensor + touchpad_sensor
│   └── mock.py              # 测试用
└── _refs.py                 # 不改
```

### 平台分发：adapter.py 负责

```python
# plugins/body/ears/adapter.py
from .._refs import body_ref, identity_mgr_ref

def register(ctx):
    import sys
    from xiaomei_brain.cli.platform_utils import is_wsl2

    if is_wsl2():
        from .wsl2 import RealMicrophone as Device
    elif sys.platform == "win32":
        from .windows import WindowsMicrophone as Device
    elif sys.platform == "darwin":
        from .linux import LinuxMicrophone as Device  # macOS 复用 Linux 实现
    else:
        from .linux import LinuxMicrophone as Device

    from xiaomei_brain.body.sense import Ears
    sense = Ears()
    device = Device()
    ctx.register_sense(sense, device)
```

## 实现阶段

### Phase 1: CLI 兼容层（P0）

新建 `cli/platform_utils.py`，封装所有平台差异：

| 函数 | Unix (Linux/macOS) | Windows | WSL2 |
|------|-------------------|---------|------|
| `readline_import()` | `import readline` | `import pyreadline3 as readline` | 同 Unix |
| `get_single_char()` | `termios` + `tty.setraw` | `msvcrt.getch()` | 同 Unix |
| `select_stdin(timeout)` | `select.select([sys.stdin])` | `msvcrt.kbhit()` + sleep loop | 同 Unix |
| `is_wsl2()` | `False` | `False` | 读 `/proc/version` |
| `send_signal(pid, sig)` | `os.kill(pid, sig)` | try/except `AttributeError` | 同 Unix |
| `register_signals()` | `signal.SIGTERM` + `SIGINT` | 仅 `SIGINT` | 同 Unix |

修改文件：
- `cli/run.py` — 用 `platform_utils` 替换直接的 `readline`/`termios`/`select`/`signal` 调用
- `cli/masked_input.py` — 用 `platform_utils.get_single_char()`
- `cli/lifecycle.py` — `send_signal()` 替代 `os.kill(SIGKILL)`
- `mcp/connection.py` — `send_signal()` 替代 `os.kill(SIGKILL)`
- `cli/curses_ui.py` — 不改逻辑，文档说明 Windows 需装 `windows-curses`

依赖更新 (`pyproject.toml`)：
```toml
[project.optional-dependencies]
windows = ["pyreadline3", "windows-curses"]
```

### Phase 2: Body Device 重组（P1）

不改逻辑，只做文件移动和重命名：

1. **创建新文件** — `eyes/linux.py`, `eyes/windows.py`, `ears/linux.py`, `ears/windows.py` 等，初始为空或带 `NotImplementedError`
2. **重命名现有文件**：
   - `real_camera.py` → `wsl2.py`
   - `real_microphone.py` → `wsl2.py`
   - `real_speaker.py` → `wsl2.py`
   - `mock_camera.py` → `mock.py`
   - `mock_microphone.py` → `mock.py`
   - `scroll_sensor.py` + `touchpad_sensor.py` → `touch/wsl2.py`
3. **更新 adapter.py** — 加平台分发逻辑
4. **更新所有 import 引用**

### Phase 3: Windows Device 实现（P2）

**Windows 原生摄像头** (`eyes/windows.py`)：
- 使用 `cv2.VideoCapture(0)`
- 实现 `Camera` ABC：`open()` / `capture()` / `close()` / `is_operational()`

**Windows 原生麦克风** (`ears/windows.py`)：
- 使用 `pyaudio` 或 `sounddevice` 流式录音
- 实现 `Microphone` ABC

**Windows 原生音箱** (`throat/windows.py`)：
- 整理现有的 `_play_windows()` 逻辑
- 用 `powershell -Command (New-Object Media.SoundPlayer ...).PlaySync()` 或直接用 winsound

### Phase 4: Linux 原生 Device 实现（P3）

与 Windows 几乎相同的 cv2 + PyAudio 代码，只是设备名称/索引不同。提取公共基类以减少重复。

### Phase 5: macOS 验证（社区）

Linux Device 实现的 darwin 路径做 CI 验证（GitHub Actions macOS runner）。Mac 用户实际体验靠社区反馈。

## 不变的部分

以下模块纯 Python + 跨平台库，不受影响：

- `consciousness/` — 意识系统
- `memory/` — 记忆系统（LanceDB / SQLite / sentence-transformers 均跨平台）
- `drive/` — 边缘系统
- `purpose/` — 目标管理
- `metacognition/` — 元认知
- `agent/` — Agent 核心
- `tools/` — 工具层（除 shell 工具中 Unix 命令外）
- `mcp/` — MCP 集成
- `skills/` — 技能系统
- `channels/` — 消息渠道（纯网络 I/O）
- `gateway/` — 入站门

## Shell 工具适配

`tools/builtin/shell.py` 中部分命令在 Windows 上不可用。采用白名单 + 文档说明的方式，不自动翻译命令。

## 依赖更新

```toml
[project]
dependencies = [
    # 现有依赖不变
    ...
    "psutil>=5.9.0",        # 跨平台进程管理（已在用，补声明）
]

[project.optional-dependencies]
windows = [
    "pyreadline3>=3.4.0; sys_platform == 'win32'",
    "windows-curses>=2.3.0; sys_platform == 'win32'",
]

body = [
    "opencv-python>=4.8.0",  # 摄像头
    "PyAudio>=0.2.11",       # 麦克风
    "sounddevice>=0.4.0",    # 麦克风备用
]
```

## 验证

```bash
# Windows 原生
python -m xiaomei_brain run xiaomei --cli

# WSL2（不变）
PYTHONPATH=src python3 -m xiaomei_brain run xiaomei --cli

# CI
GitHub Actions matrix: ubuntu-latest, windows-latest, macos-latest
```

## Windows 已知陷阱

### GBK 编码

Windows 默认系统编码是 GBK（cp936），`open()` 不带 `encoding` 参数时走系统编码，读 UTF-8 文件直接炸。

**解决**：`cli/platform_utils.py::ensure_utf8_output()` 中 monkey-patch `builtins.open`，文本模式默认 `encoding="utf-8"`。VoxCPM 等第三方库内部 `open()` 不带 encoding 的问题一并修复。

### TorchCodec / FFmpeg

sentence-transformers 5.x 在 `modality_types.py` 中无条件 `import torchcodec`（即使是纯文本 embedding 也用不到）。Windows 上 torchcodec 尝试加载 FFmpeg 的 `.dll`（`libtorchcodec_core{N}.dll` → `avcodec-*.dll` 等），Windows 没有系统级 FFmpeg shared library，加载失败。导致本地 embedding 回退（BGE-M3 无法用），向量搜索退化到关键词匹配。

WSL2/Linux 上 FFmpeg 是系统基础设施（`libavcodec.so` 等），不触发此问题。

**解决**：Windows 上卸载 torchcodec（`pip uninstall torchcodec`），sentence-transformers 对该 import 有 try/except 兜底，不影响文本 embedding。

### TTS 流式播放 — 音频回调阻塞

WASAPI 音频回调在高优先级线程中运行，必须在 ~20-30ms 内返回。回调中调用 `next(gen)` 会阻塞在 GPU 推理/HTTP 等待上，导致 output underflow（静音间隙）。

**解决**：`throat/windows.py::play_stream()` 采用 producer 线程 + `queue.Queue` + 预填充 3s + 回调 `get_nowait()` 非阻塞模式。GPU/HTTP 在 producer 线程中阻塞，WASAPI 回调永不等待。

详细调优记录见 `memory/tts_audio_pipeline.md`。

## 不做

- Touch 触控跨平台（无通用 API，标记 Linux-only 可选功能）
- Shell 命令自动翻译（Windows 用 WSL/PowerShell 自行处理）
- TTS 降级方案（`aplay` 仅为 Linux fallback，不阻塞）
