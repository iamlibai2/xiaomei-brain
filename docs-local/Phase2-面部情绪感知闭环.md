# 面部情绪感知闭环 — Phase 2: BodyState → SelfImage

## Context

Phase 1 已创建 FaceEmotionDetector 并集成到 Eyes.recognize_faces()，但情绪数据只在主动调用时返回（/who 或 look_around 工具），没有进入自动感知链路。

Phase 2 打通自动感知管道：让情绪数据通过 Body.tick() → BodyState → SelfImage → SelfBody，进入 LLM 的系统提示词上下文。

**不做 Drive 直接反应** — 让 LLM 通过 SocialCognition 自然处理视觉情绪信息（和现有社交感知路径一致）。

## 设计

```
Body.tick() (每 10 分钟)
  └─> Eyes.contribute_to(state)
        └─> state.visual_faces = recognize_faces()
        └─> state.facial_emotions = [提取的纯情绪数据]
              │
              └─> SelfImage.contribute_body_senses(state)
                    └─> SelfBody.visual_faces
                    └─> SelfBody.facial_emotions  ← 新增
                          │
                          └─> LLM 系统提示词 (SelfBody 注入)
                                → SocialCognition 处理
                                → 情绪感知闭环
```

## 修改文件

### 1. `body/state.py` — 新增 facial_emotions 字段

```python
facial_emotions: list[dict] = field(default_factory=list)
```

### 2. `body/sense.py` — 取消注释 Eyes.contribute_to()

```python
def contribute_to(self, state) -> None:
    faces = self.recognize_faces()
    state.visual_faces = faces
    state.facial_emotions = [
        {"name": f.get("name"), **f["emotion"]}
        for f in faces if f.get("emotion")
    ]
```

### 3. `consciousness/self_modules.py` — SelfBody 新增字段

- 添加 `facial_emotions: list = field(default_factory=list)` 到感官字段区域
- `to_dict()` 和 `from_dict()` 中加入 `"facial_emotions"`

### 4. `consciousness/self_image_proxy.py` — 添加拷贝行

```python
self.body.facial_emotions = list(state.facial_emotions)
```

## 不修改的文件

- `drive/engine.py` — LLM 通过 SocialCognition 自然处理，无需新 Drive 路径
- `consciousness/living_commands.py` — /who 和 look_around 已通过 recognize_faces() 拿到情绪
- `consciousness/layer0.py` — 调用链不变，contribute_body_senses() 已包含新字段

## 验证

```bash
# 1. 导入 + 静态检查
PYTHONPATH=src python3 -c "
from xiaomei_brain.body.state import BodyState
s = BodyState()
s.facial_emotions = [{'name': 'test', 'dominant': 'happy', 'indicators': {'smile': 0.8}}]
print('BodyState OK:', s.facial_emotions)
"

# 2. 端到端：启动 agent，等待 10 分钟自动 tick，
#    然后 /context 查看 SelfBody 是否包含 facial_emotions

# 3. look_around 工具仍正常工作（LLM 调用返回含 emotion 的人脸数据）
```
