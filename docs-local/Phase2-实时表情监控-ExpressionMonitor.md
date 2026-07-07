# 实时表情监控 — ExpressionMonitor

## Context

Phase 1 的 FaceEmotionDetector（dlib 几何法）已就绪，但集成在 Eyes.recognize_faces() 里，只在主动调用时触发。需要独立后台线程做高频实时检测。

**已验证**：EmotiEffLib enet_b2_7 (ONNX) 替代几何法 — ~12ms 推理，7 类情绪（Anger/Disgust/Fear/Happiness/Neutral/Sadness/Surprise），准确率优于 dlib 几何法。

## 核心原则：「看到别人笑 ≠ 自己开心」

- **Drive 是 Agent 自身的内部状态**，不是观察到的情绪的镜像
- 观察到的情绪 → **SocialPerception 层** → 转换为社交信号 → 间接影响 Drive
- **身份感知**：熟悉的人笑 vs 陌生人生气，对 agent 的意义完全不同

## 双通道架构

```
ExpressionMonitor 线程（Windows cv2，~10 FPS）
  │
  ├─ cv2 取帧 → dlib face detection + landmarks
  │
  ├─ FaceID: 识别身份 → identity context (name/familiar/stranger)
  │
  ├─ EmotiEffLib enet_b2_7: 7-class emotion probability
  │
  ├─ Path B（社交感知，高频低量）────→ SocialPerception.observe()
  │   每帧推 identity + emotion → 社交信号
  │   "熟悉的人笑了" → social signal: familiar_user_happy
  │   "陌生人发怒"  → social signal: stranger_angry
  │   SocialPerception 内部逻辑决定 Drive 如何响应
  │   （不直接映射，agent 的反应取决于身份、关系、上下文）
  │
  └─ Path A（事件上报，低频高量）────→ SelfBody.observed_emotions → LLM
       阈值触发，不每帧惊动 LLM
       触发条件：
       - 情绪剧变（3秒内 Happiness→Anger，概率均 >0.6）
       - 极端情绪（Happiness >0.9 或 Anger >0.9）
       - 持续高强度（同一情绪保持 >10 秒且概率 >0.7）
       - 熟人 + 负面情绪（FaceID 匹配 + Sadness/Anger >0.7）
```

## 设计原则

- **Path B 高频低量**：每帧推原始观察（identity + emotion prob），由 SocialPerception 处理后间接影响 Drive。不做直接映射
- **Path A 低频高量**：只有"值得注意"的变化才推送到 SelfBody.observed_emotions，进入 LLM 上下文
- **不经过 Body.tick()**：独立线程，独立节奏，不影响现有感知周期
- **类比 VoiceListener**：后台持续监听 → VAD → 检测到有意义信号 → 推送

## 新增文件

### `body/perception/expression_monitor.py`

```python
class ExpressionMonitor:
    """后台线程：cv2 取帧 → dlib 人脸检测 → FaceID 身份 + EmotiEffLib 情绪 → 推送。

    双通道输出：
    - Path B: 每帧 → SocialPerception（高频，间接影响 Drive）
    - Path A: 阈值触发 → SelfBody.observed_emotions（低频，LLM 可见）

    用法：
        monitor = ExpressionMonitor(social_perception, self_image, face_id)
        monitor.start()
        monitor.stop()
    """

    def __init__(self, social_perception, self_image, face_id, interval=0.1, camera_id=0):
        self._sp = social_perception    # SocialPerception 实例
        self._si = self_image           # SelfImage 实例
        self._face_id = face_id         # FaceID 实例
        self._interval = interval       # 采样间隔（秒），~10 FPS
        self._emotion_start = None      # (emotion, timestamp)
        self._history = []              # 最近 N 帧情绪（用于突变检测）
        self._running = False

    def start(self): ...
    def stop(self): ...

    def _tick(self):
        """一帧处理"""
        # 1. cv2 取帧
        # 2. dlib face detection + landmarks
        # 3. FaceID: 识别身份 → identity context
        # 4. EmotiEffLib: enet_b2_7 7-class emotion probability
        # 5. Path B: _push_observation(identity, emotion) → SocialPerception
        # 6. Path A: _check_gate(identity, emotion) → SelfBody.observed_emotions
```

### 情绪识别模型

- **模型**: EmotiEffLib enet_b2_7 (ONNX Runtime)
- **推理速度**: ~12ms（纯模型），~100ms（含人脸检测），~10 FPS
- **7 类**: Anger, Disgust, Fear, Happiness, Neutral, Sadness, Surprise
- **输出**: 每类概率分布 (softmax)，不是单一标签
- **输入**: 260×260 RGB，ImageNet 归一化

### Path B：SocialPerception 社交信号

观察到的情绪通过 SocialPerception 处理（复用现有机制）：

| 观察 (identity + emotion) | 社交信号 | Drive 影响（由 SP 逻辑决定） |
|--------------------------|---------|---------------------------|
| 熟人 + Happiness >0.5 | familiar_happy | 视上下文而定 |
| 熟人 + Sadness >0.5 | familiar_sad | 视上下文而定 |
| 熟人 + Anger >0.5 | familiar_angry | 视上下文而定 |
| 陌生人 + Happiness | stranger_happy | 微弱正面 |
| 陌生人 + Anger | stranger_angry | 警觉信号 |
| Neutral | 无 | 无 |

> **不做 1:1 映射。** "看到用户笑 → dopamine +0.02" 是错误的——agent 可能因为其他原因不开心，或者用户的笑是讽刺的。SocialPerception 结合身份 + 上下文 + 历史来决定 agent 自身的情绪反应。

### Path A 阈值

| 条件 | 阈值 | 事件类型 |
|------|------|---------|
| 情绪剧变 | 3秒内 Happiness→Anger（概率均 >0.6） | "emotion_shift" |
| 极端情绪 | 任一情绪概率 >0.9 | "extreme_emotion" |
| 持续高强度 | 同一情绪 >0.7 持续 >10秒 | "sustained_emotion" |
| 熟人+负面 | FaceID 匹配 + Sadness/Anger >0.7 | "familiar_negative" |

## 修改文件

- `body/perception/expression_monitor.py` — **新增**，ExpressionMonitor 类
- `body/perception/face_emotion.py` — EmotiEffLib 替代 dlib 几何法
- `body/state.py` — 新增 `observed_emotions: list[dict]`（Path A 事件队列）
- `consciousness/self_modules.py` — SelfBody 新增 `observed_emotions`
- `consciousness/self_image_proxy.py` — contribute_body_senses() 拷贝 `observed_emotions`
- `consciousness/conscious_living.py` — 启动 ExpressionMonitor
- `metacognition/social_perception.py` — 新增 `observe()` 方法（接收视觉情绪输入）

## 不修改

- `drive/engine.py` — 由 SocialPerception 间接影响，ExpressionMonitor 不直接操作 Drive
- `body/sense.py` — Eyes 不变，ExpressionMonitor 是独立线程
- `body/__init__.py` — Body.tick() 不变

## 前置条件

- Windows 原生环境（cv2 直连摄像头，毫秒级取帧）
- WSL2 不适合——PowerShell 拍照延迟 1-2 秒，做不到高频
- EmotiEffLib ONNX 模型已下载到 `~/.cache/emotiefflib/enet_b2_7.onnx` (29.3MB)

## 验证

```bash
# Windows 上启动 agent，打开摄像头
PYTHONPATH=src python3 -m xiaomei_brain run xiaomei --cli

# /context 查看 SelfBody.observed_emotions（Path A 事件）
# 对着镜头做表情 → 极端表情 >10 秒应触发事件
# 熟人出现 + 负面表情 → 应触发 familiar_negative 事件
```
