# ONNX 模型导出与推理实践

## 背景

VoxCPM 1.5 PyTorch 原生推理在 Windows 上存在性能瓶颈（RTF ~0.76），且 `torch.compile` 依赖 Triton（仅 Linux），无法加速。尝试将模型导出为 ONNX 格式，用 ONNX Runtime 替代 PyTorch 原生推理。

## 核心概念

### PyTorch vs ONNX 的关系

```
模型层:
  VoxCPM 1.5 (~3GB, 44.1kHz TTS)
  BGE-M3 (1024维文本 embedding)

推理框架层:
  PyTorch → torch.nn.Linear, torch.matmul → CUDA kernel
  ONNX Runtime → 算子A → 算子B → 算子C → CUDA kernel / DML

框架边界:
  SentenceTransformer = PyTorch 的流程编排（tokenize → forward → pool → normalize）
  FunASR = PyTorch 的流程编排（Speech-to-Text）
  SpeechBrain = PyTorch 的流程编排（ECAPA-TDNN 声纹识别）
  dlib = C++ 推理（人脸识别，不走 PyTorch）
```

SentenceTransformer/FunASR/SpeechBrain 不做计算，只是**管流程**（tokenize、pooling、normalize），真正的矩阵运算全是 PyTorch 做的。

### ONNX 是什么

把 PyTorch 模型的计算图拍平，去掉训练框架包袱（autograd、动态图、Python 代码），只保留推理必需的计算。类比：PyTorch = 源代码+编译器，ONNX = 编译好的二进制。

### torch.onnx.export 做什么

```python
torch.onnx.export(model, dummy_input, "model.onnx")
# 1. 给模型喂 dummy 输入，trace 所有运算
# 2. 记录成静态计算图（if/for 全部展开）
# 3. 输出为 .onnx 文件（protobuf 格式）
```

**关键限制**：Python 循环在 trace 时被展开，循环次数硬编码在图里。`timesteps` 不能被设为动态输入是因为 `for step in range(10)` 这个 Python 循环被展开成了 10 个计算块，而非作为图循环。

### ONNX 推理后端

onnxruntime 有三种后端：

| 后端 | 包 | 需要 CUDA |
|---|---|---|
| CPU | `onnxruntime` | 不需要 |
| CUDA | `onnxruntime-gpu` | 需要 CUDA Toolkit |
| DirectML | `onnxruntime-directml` | 不需要（Windows DirectX 12） |

### FP32 vs FP16

```
FP32: 每个权重 4 bytes, Main 模型 1.8 GB
FP16: 每个权重 2 bytes, Main 模型 920 MB

精度损失极小（近似误差在 1e-4 级别），速度/显存双重收益。
ONNX 优化脚本通过 onnxruntime.transformers.optimizer 做 FP32→FP16 转换。
```

### CFG (Classifier-Free Guidance)

```
output = CFG_VALUE × 条件生成 + (1 - CFG_VALUE) × 无条件生成

CFG=1.0 → 最自然，可能偏离参考音色
CFG=2.0 → 平衡点
CFG=2.5 → 更像参考，但可能生硬/速度变慢
```

CFG_VALUE 是 ONNX 模型的输入，不需要重新导出即可修改。但 `timesteps` 是硬编码的，必须重新导出。

## 实验过程

### 1. 模型导出（DakeQQ/Text-to-Speech-TTS-ONNX）

基于 [DakeQQ/Text-to-Speech-TTS-ONNX](https://github.com/DakeQQ/Text-to-Speech-TTS-ONNX) 项目，支持 VoxCPM 1.5 的 ONNX 导出。

VoxCPM 1.5 拆成 8 个 ONNX 子模块：

| 模块 | 作用 |
|---|---|
| VAE_Encoder | 参考音频 → 隐空间向量 |
| Feat_Encoder_Cond | 融合特征编码 + CFG 条件 |
| Prefill | 文本嵌入 + 旋转位置编码 + 首次 KV 填充 |
| Rotary_Mask_Decode | 每步解码的位置编码 |
| Main | 主 Transformer 自回归解码 |
| Feat_Decoder | 扩散去噪（所有 timesteps 展开成一次调用） |
| VAE_Decoder | 隐空间 → 音频波形 |
| Concat | 流式模式双隐变量拼接 |

注意：Feat_Decoder 把 `for step in range(timesteps)` 的 Python 循环展开成了 N 个串行计算块，导出后 timesteps 固定不可变。原始 14 次 ORT 调用 / token 优化为 4 次（Main → Feat_Decoder → Feat_Encoder_Cond → Rotary_Mask_Decode）。

### 2. 踩坑记录

| 问题 | 解决 |
|---|---|
| HF 缓存路径 `models--xxx--VoxCPM1.5/` 无 config.json | 用 `snapshots/<hash>/` 子目录 |
| 输出路径硬编码 `/home/DakeQQ/...` | 改为 Windows 路径 `D:/workspace/...` |
| `onnx` 包缺失 | `uv pip install onnx` |
| `onnxslim` 包缺失 | `uv pip install onnxslim` |
| 推理脚本 `\b` 被当转义字符 | 字符串用 `r"..."` 前缀 |
| `onnxruntime-gpu 1.27` 要求 CUDA 13 | 降级到 1.21.0 适配 CUDA 12.4 |
| `matmul_nbits_quantizer` 导入失败（旧版无此模块） | try/except 包裹，FP16 优化不需要它 |

### 3. 性能对比

| 版本 | Timesteps | 精度 | CFG | 体积 | RTF |
|---|---|---|---|---|---|
| PyTorch 原生 | 6 | FP32 | 2.0 | ~3 GB | ~0.76 |
| ONNX 导出 | 10 | FP32 | 2.5 | 3.3 GB | ~1.09 |
| ONNX 导出 | 6 | FP32 | 2.0 | 3.3 GB | ~1.19 |
| **ONNX 优化** | **6** | **FP16** | **2.0** | **1.7 GB** | **~0.97** |

结论：ONNX FP16 版模型体积减半、推理稳定性好、不依赖 Triton（Windows 可用），但 RTF 仍不及 PyTorch 原生（因 `torch.compile` 的算子融合比 ONNX 图优化更激进）。

### 4. 流式播放架构

```
ONNX decode loop (generator)
  → yield audio chunk (每2个 latent)
    → data_q.put(bytes)
      → sounddevice callback get_nowait()
        → WASAPI 播放
```

预缓冲 3 秒 + FP16 + 6 步 + CFG=2.0 时 underflows 降到 1/1082，但 RTF 仍制约长文本流式体验。

## 扩展性

`DakeQQ/Text-to-Speech-TTS-ONNX` 项目还支持 IndexTTS、F5-TTS、Qwen3-TTS 等模型，导出流程统一：修改路径 → Export → Optimize → Inference。后续试 IndexTTS 可复用此流程。

## RTF 优化优先级

1. **减少 timesteps**（6→4，需重新导出，效果最显著）
2. **FP16 量化**（不需要重新导出，模型体积减半 + 带宽减半）
3. **降低 CFG_VALUE**（不需要重新导出，减少计算分支开销）
4. **换模型**（IndexTTS 可能更快）
