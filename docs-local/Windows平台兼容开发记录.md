# Windows 平台兼容开发记录

## 背景

xiaomei-brain 最初在 WSL2 上开发，架构设计时为多平台预留了位置（Linux/WSL2/Windows/macOS）。2026-06-29~30 在 Windows 原生（Windows 11 + Python 3.11）上完整验证，踩坑记录如下。

## 核心设计原则

1. **利用系统原生能力** — 不引入额外依赖（播放靠 `os.startfile()`，录音靠 PyAudio，不要 ffmpeg）
2. **VoxCPM 仅 GPU** — 没有 CUDA 就退出，不坑用户用 CPU 跑 3GB 模型
3. **TTS 默认走在线 API** — MiniMax 在线 TTS 零门槛，本地 VoxCPM 是可选离线方案
4. **代码兼容而非配置** — 尽量在代码层面处理平台差异，不让用户设环境变量

## 踩坑记录

### 1. 依赖安装

#### 1.1 PyPI 依赖不存在或版本不匹配

| 依赖 | 问题 | 解决 |
|------|------|------|
| `webrtcvad>=2.2.0` | PyPI 最高只有 2.0.10 | 换成 `webrtcvad-wheels>=2.0.11`，接口兼容 |
| `dlib` | Windows 无 wheel，源码编译 GBK 编码失败 | 用 `dlib-bin`（cp311-win_amd64 预编译 wheel）|
| `face_recognition` | 依赖 `dlib`，pip 拒绝安装 | 分步装：先装 `face-recognition-models click Pillow`，再 `--no-deps face_recognition` |
| `lance` | PyPI 上 `lance` 1.2.1 是另一个包（`lance.LanceDataset` 不存在） | 改用 `pylance`（lancedb 的正确 C++ 绑定）|
| `openai` | 仅为 Seedream 图片生成引入，太重 | 用 `requests` 直接调 API |

#### 1.2 PyTorch CUDA 版本

PyTorch 默认装 CPU 版，`torch.cuda.is_available()` 返回 `False`。有 NVIDIA GPU 需手动装 CUDA 版：

```powershell
pip install --reinstall torch torchaudio --index-url https://download.pytorch.org/whl/cu124
```

**注意**：`torchaudio` 也要一起重装，否则版本不匹配导致 `OSError [WinError 127]`。

#### 1.3 最终依赖分组

```toml
[project]
dependencies = [
    # 核心（跨平台零问题）
    "requests>=2.31.0",
    "sentence-transformers>=2.2.0",
    "lancedb>=0.4.0",
    "pylance",               # lancedb C++ 绑定
    ...
]

[project.optional-dependencies]
windows = [
    "pyreadline3>=3.4.0; sys_platform == 'win32'",
    "windows-curses>=2.3.0; sys_platform == 'win32'",
]
body = [
    "pyaudio>=0.2.11",
    "opencv-python-headless>=4.8.0",
    "dlib-bin",               # 非 dlib
    "sounddevice>=0.4.0",
    "funasr>=1.0.0",
    "webrtcvad-wheels>=2.0.11",  # 非 webrtcvad
    "voxcpm",
    "soundfile>=0.12.0",
    "speechbrain>=1.0.0",
]
```

### 2. 摄像头 (eyes/windows.py)

#### 2.1 多后端探测

cv2.VideoCapture 在 Windows 上有多个后端：

```python
_BACKENDS = [
    (cv2.CAP_DSHOW, "CAP_DSHOW"),   # DirectShow — 部分设备预热失败
    (cv2.CAP_MSMF,  "MSMF"),        # Media Foundation
    (cv2.CAP_ANY,   "默认"),         # 自动选择
]
```

依次尝试，任一成功即停止。CAP_DSHOW 在部分驱动上预热失败（返回空帧），自动 fallback 到下一个。

#### 2.2 预热机制

打开摄像头后需要 30 帧预热，否则前几帧可能是黑色的。`open()` 内建预热循环。

### 3. 麦克风 (ears/windows.py)

#### 3.1 流式录音 API

VoiceListener 需要麦克风支持流式读取（`start_stream() / read_chunk() / stop_stream()`），而非一次性录音。实现方案：

- PyAudio 打开 `input=True` 流
- daemon 线程持续读取 → `queue.Queue`
- `read_chunk(timeout)` 从队列取数据

Linux/macOS 复用同一实现（PyAudio 跨平台）。

### 4. 音箱 (throat/windows.py)

#### 4.1 不要 ffmpeg

原始设计方案用 ffmpeg 将 MP3 转 WAV → winsound 播放。但 Windows 上 ffmpeg 不是标配。

**最终方案**：与 WSL2 一致，利用 Windows 原生能力。

```python
def play(self, audio_path):
    # WAV → winsound（轻量，无需外部播放器）
    if ext == ".wav":
        winsound.PlaySound(audio_path, winsound.SND_ASYNC | winsound.SND_FILENAME)
        return
    # 非 WAV → os.startfile() 调 Windows 默认播放器（零依赖）
    os.startfile(audio_path)
```

#### 4.2 numpy 2.x 兼容

`np.int16.name` 在 numpy 2.x 中被移除。`dtype.name` → `np.dtype(dtype).name`。

#### 4.3 sounddevice callback 字节/样本混用

`outdata[:available]` 切片用的是样本数（frames），但 `available` 算的是字节数。当 generator 返回的 chunk 大小与 sounddevice 要求的 frames 不一致时，reshape 失败。

修复：分离 `available_bytes` 和 `available_samples`。

```python
# 错误
available = min(frames * itemsize, len(buf))
outdata[:available] = np.frombuffer(buf[:available], dtype=dtype).reshape(-1, channels)

# 正确
available_bytes = min(frames * itemsize, len(buf))
available_samples = available_bytes // itemsize
outdata[:available_samples] = np.frombuffer(buf[:available_bytes], dtype=dtype).reshape(-1, channels)
```

### 5. 声纹识别 (speaker_id.py)

#### 5.1 Windows 符号链接权限

SpeechBrain 在 Windows 上多处尝试创建符号链接，但非管理员用户无此权限（`[WinError 1314]`）。

发生点：
- a) `from_hparams()` 从 HF 缓存 symlink 到 `savedir`
- b) `Pretrainer` 在 savedir 内部创建 `label_encoder.txt` → `label_encoder.ckpt`

修复（两层）：
1. `_resolve_savedir()` — 直接把 savedir 指到 HF 缓存快照目录，文件已就绪
2. `_precopy_symlink_targets()` — 把 `.txt` 硬拷贝为 `.ckpt`，Pretrainer 发现目标已存在跳过 symlink

```python
def _resolve_savedir(hf_dir_name, fallback):
    """savedir → HF 缓存快照，零拷贝"""
    snapshots = f"~/.cache/huggingface/hub/{hf_dir_name}/snapshots"
    # → ~/.cache/huggingface/hub/.../snapshots/<hash>/

def _precopy_symlink_targets(savedir):
    """label_encoder.txt → label_encoder.ckpt（硬拷贝，几 KB）"""
    for f in os.listdir(savedir):
        if f.endswith('.txt'):
            shutil.copy2(f, f[:-4] + '.ckpt')
```

#### 5.2 k2 懒加载

SpeechBrain 的 `load_audio()` 在 Windows 上触发 `k2` 懒加载 → `ImportError`。k2 是语音识别工具包，声纹识别不需要。

修复：用 `soundfile` 直接读 WAV，替代 `SpeechBrain._recognizer.load_audio()`。

```python
# 替代 SpeechBrain 内置 load_audio
import soundfile as sf
signal, sr = sf.read(wav_path, dtype="float32")
waveform = torch.from_numpy(signal).unsqueeze(0)
embedding = recognizer.encode_batch(waveform)
```

### 6. VoxCPM 本地 TTS

#### 6.1 仅支持 GPU

VoxCPM 1.5 模型 ~3GB，CPU 推理极慢（不可用级别）。策略：

- `voxcpm_server.py` — 检测无 CUDA → `sys.exit(1)`，提示"建议使用在线 TTS"
- `provider.py` — deviced 默认 `"cuda"` 而非 `"auto"`

```python
if not torch.cuda.is_available():
    logger.error("CUDA 不可用，VoxCPM 需要 GPU 推理以得到流畅体验，建议使用在线 TTS 代替")
    sys.exit(1)
```

#### 6.2 在线 TTS 兜底

MiniMax TTS 是在线 API，零门槛。VoxCPM 是可选的离线方案。系统同时注册两套工具（`speak` vs `vox_speak`），LLM 自行选择。

### 7. 其他

#### 7.1 torch.compile / triton

`Warning: torch.compile disabled - triton is not installed` — Triton 仅 Linux，Windows 不显示。功能不受影响。

#### 7.2 编码问题

##### 7.2.1 GBK 编码

Windows 默认系统编码是 GBK（cp936），`open()` 不带 `encoding` 参数时走系统编码，读 UTF-8 文件直接报错。

**影响范围**：VoxCPM 等第三方库内部 `open()` 不带 encoding，加载 `reference.txt` 等文件时 `'gbk' codec can't decode byte 0xaf`。

**解决**：`cli/platform_utils.py::ensure_utf8_output()` 中 monkey-patch `builtins.open`，文本模式默认 `encoding="utf-8"`。

```python
def _patch_open_utf8() -> None:
    import builtins
    _orig = builtins.open
    def _open(file, mode="r", buffering=-1, encoding=None, ...):
        if encoding is None and "b" not in mode:
            encoding = "utf-8"
        return _orig(file, mode, buffering, encoding, ...)
    builtins.open = _open
```

##### 7.2.2 WSL2 路径转换

WSL2 → Windows 路径转换（`\\wsl.localhost\Ubuntu\...`）在 GBK 编码环境下可能导致 `UnicodeDecodeError`。dlib 编译失败即此原因。

#### 7.3 Windows 控制台

Ctrl+C 按一次可能不够（跟 select/stdin 有关），双击 Ctrl+C 强制退出。

#### 7.4 TorchCodec / FFmpeg

sentence-transformers 5.x 在 `modality_types.py` 中无条件 `import torchcodec`，即使是纯文本 embedding（BGE-M3）也用不到。Windows 上 torchcodec 尝试加载 FFmpeg 的 `.dll`（`libtorchcodec_core{N}.dll` → `avcodec-*.dll`），Windows 没有系统级 FFmpeg shared library，加载失败。

**影响**：本地 embedding 无法正常工作（BGE-M3 加载失败），向量搜索退化到关键词匹配。

**根因**：Linux 上 FFmpeg 是系统基础设施（`libavcodec.so` 默认存在），Windows 上不是。

**解决**：卸载 torchcodec（`pip uninstall torchcodec`）。sentence-transformers 对该 import 有 try/except 兜底，卸载后文本 embedding 不受影响。如果确实需要 torchcodec（视频解码场景），装 FFmpeg shared 版本：`winget install ffmpeg`。

## 测试检查单

Windows 原生验证清单：

- [ ] `pip install -e .[windows,body]` 无报错
- [ ] PyTorch `torch.cuda.is_available()` 符合预期
- [ ] `pip install --no-deps face_recognition` 人脸识别可用
- [ ] 摄像头拍照正常（多后端 fallback 测试）
- [ ] 麦克风流式录音正常（VAD → STT 链路通）
- [ ] 音箱播放 WAV 正常（winsound）
- [ ] 音箱播放 MP3 正常（`os.startfile()` 调默认播放器）
- [ ] 声纹识别正常（绕过 symlink + k2）
- [ ] TTS speak 正常（MiniMax 在线 API）
- [ ] VoxCPM 有 GPU 时正常，无 GPU 时退出并提示
- [ ] —cli 交互模式长时间运行稳定

## 相关文件

| 文件 | 修改内容 |
|------|---------|
| `pyproject.toml` | 依赖分组、webrtcvad-wheels、dlib-bin、pylance |
| `plugins/body/eyes/windows.py` | 多后端摄像头 |
| `plugins/body/ears/windows.py` | 流式麦克风 |
| `plugins/body/throat/windows.py` | os.startfile() 播放、sounddevice callback 修复、numpy 2.x 兼容 |
| `body/perception/speaker_id.py` | Symlink 绕过、k2 绕过 |
| `scripts/voxcpm_server.py` | CUDA 检测 + 无 GPU 退出 |
| `plugins/tools/tts_voxcpm/provider.py` | device 默认 "cuda" |
| `README.md` | Windows 安装、GPU、人脸识别、TTS 说明 |
