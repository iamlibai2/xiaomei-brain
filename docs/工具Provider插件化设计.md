# 工具 Provider 插件化设计

## 背景

TTS/图像/音乐三个能力当前硬编码在 `AgentManager.init_agent()` 里，API key/base_url 在 `xiaomei_brain.{tts,image,music}` 独立配置，跟 `models.providers` 重复。用户要换成豆包生成音乐就得改代码。

LLM Provider 已经走插件体系（`plugin.yaml` + `adapter.py` + `register(ctx)`），工具 Provider 应该用同一套机制。

## 设计

### 新增 3 个 plugin kind

| kind | 注册方法 | 用途 |
|------|---------|------|
| `tts-provider` | `ctx.register_tts_provider(profile)` | TTS |
| `music-provider` | `ctx.register_music_provider(profile)` | 音乐生成 |
| `image-provider` | `ctx.register_image_provider(profile)` | 图像生成 |

每个一个目录：
```
tools/tool_providers/
├── __init__.py
├── minimax_tts/       plugin.yaml + adapter.py
├── minimax_music/     plugin.yaml + adapter.py
├── minimax_image/     plugin.yaml + adapter.py
└── doubao_music/      (未来) plugin.yaml + adapter.py
```

### plugin.yaml

```yaml
name: minimax-tts
version: "1.0.0"
description: MiniMax TTS — T2A v2 API
kind: tts-provider
auth_provider: minimax       # ← 从 models.providers.minimax 取 apiKey/baseUrl
entry: adapter:register
requires_env:
  - MINIMAX_API_KEY
```

### adapter.py

```python
from xiaomei_brain.tools.provider import TTSProvider, VoiceConfig, AudioConfig
from xiaomei_brain.tools.provider.profiles import TTSProviderProfile, ToolModel

def register(ctx):
    ctx.register_tts_provider(TTSProviderProfile(
        name="minimax-tts",
        provider_class=TTSProvider,          # 已有的实现类
        auth_provider="minimax",
        base_url="https://api.minimaxi.com",
        env_vars=("MINIMAX_API_KEY",),
        models=[ToolModel(id="speech-2.8-hd", name="MiniMax T2A v2 HD")],
        defaults={"voice_config": VoiceConfig(...), "audio_config": AudioConfig(...)},
    ))
```

### 新类型 (tools/provider/profiles.py)

```python
@dataclass
class ToolModel:
    id: str; name: str; description: str = ""; params: dict = {}

@dataclass
class TTSProviderProfile:
    name: str; provider_class: type; auth_provider: str = ""
    base_url: str = ""; env_vars: tuple = ()
    models: list[ToolModel] = []; defaults: dict = {}

@dataclass
class MusicProviderProfile:
    name: str; provider_class: type; auth_provider: str = ""
    base_url: str = ""; env_vars: tuple = ()
    models: list[ToolModel] = []; defaults: dict = {}

@dataclass
class ImageProviderProfile:
    name: str; provider_class: type; auth_provider: str = ""
    base_url: str = ""; env_vars: tuple = ()
    models: list[ToolModel] = []; defaults: dict = {}
```

### 注册表扩展 (plugin/registry.py)

```
_tts_providers:  dict[str, TTSProviderProfile]
_music_providers: dict[str, MusicProviderProfile]
_image_providers: dict[str, ImageProviderProfile]
+ get_*_provider(), list_*_providers(), register_*_provider()
```

### 配置结构

**认证统一到 `models.providers`**:
```json
"models": { "providers": { "minimax": { "apiKey": "...", "baseUrl": "..." } } }
```

**选择模型统一到 `agents.defaults`**:
```json
"agents": { "defaults": {
    "ttsModel": "minimax-tts/speech-2.8-hd",
    "musicModel": "minimax-music/music-2.6",
    "imageModel": "minimax-image/image-01"
}}
```

**工具特有参数移到 `toolProviders`**:
```json
"toolProviders": {
    "tts":  { "enabled": true, "voiceId": "...", "speed": 1.0 },
    "music": { "enabled": true, "sampleRate": 44100 },
    "image": { "enabled": true, "aspectRatio": "1:1" }
}
```

旧 `xiaomei_brain.{tts,music,image}` 保留读取作回退兼容。

### AgentManager 改造

```
旧: TTSProvider(api_key=global_config.tts_api_key, ...)
新: profile = registry.get_tts_provider(name)
    api_key = resolve_auth(profile.auth_provider, models_providers)
    profile.provider_class(api_key, base_url, **profile.defaults)
```

认证解析链：`models.providers.{auth_provider}.apiKey` → env var → LLM api_key

## 实现步骤

### Phase 1: 基础设施（零行为变化）
1. `tools/provider/profiles.py` — 新建，ToolModel + 3 个 Profile 类型
2. `plugin/manifest.py` — VALID_KINDS 加 3 个 kind；加 `auth_provider` 字段
3. `plugin/registry.py` — 加 3 个 dict + get/list/register 方法
4. `plugin/context.py` — 加 `register_tts/music/image_provider()`
5. `plugin/loader.py` — `_default_dirs()` 加 `tools/tool_providers/`
6. `tools/tool_providers/__init__.py` — 新建空文件

### Phase 2: 创建 3 个 MiniMax 插件
7. `tools/tool_providers/minimax_tts/` — plugin.yaml + adapter.py
8. `tools/tool_providers/minimax_music/` — plugin.yaml + adapter.py
9. `tools/tool_providers/minimax_image/` — plugin.yaml + adapter.py

### Phase 3: 改造 AgentManager
10. `agent/agent_manager.py` `init_agent()` — TTS/音乐/图像改为从 registry 解析
11. 认证解析 helper
12. 兼容回退：`toolProviders` 不存在时读旧 `xiaomei_brain.*`

### Phase 4: 清理
13. 标记旧 Config 字段 deprecated
14. 去掉 `xiaomei_brain.*.api_key/base_url` 写入，保留读取

## 验证

```bash
# 1. 插件加载
PYTHONPATH=src python3 -c "
from xiaomei_brain.plugin.bootstrap import boot_plugins
reg = boot_plugins('xiaomei')
print('TTS:', reg.list_tts_providers())
print('Music:', reg.list_music_providers())
print('Image:', reg.list_image_providers())
"

# 2. 现有测试无回归
PYTHONPATH=src python3 -m pytest tests/ -x -q

# 3. 运行时
PYTHONPATH=src python3 examples/test_conscious_living.py
```
