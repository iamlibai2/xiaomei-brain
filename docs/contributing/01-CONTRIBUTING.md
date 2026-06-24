# 贡献指南

> 欢迎参与 xiaomei-brain 的开发。

---

## 代码规范

### Python 风格

- 使用 `ruff` 进行代码格式化
- 类型注解：所有公共函数必须包含完整的类型注解
- 文档字符串：使用 Google 风格

```python
def extract_memory(
    conversation: str,
    user_id: str,
    *,
    top_k: int = 5
) -> list[Memory]:
    """从对话中提取长期记忆。
    
    Args:
        conversation: 对话文本
        user_id: 用户标识
        top_k: 返回的最大记忆条数
        
    Returns:
        记忆列表，按相关性降序排列
    """
    ...
```

### 命名规范

- 类名: `PascalCase`（`LongTermMemory`, `DriveEngine`）
- 函数/方法: `snake_case`（`extract_memory`, `check_stuck`）
- 常量: `UPPER_SNAKE_CASE`（`MAX_RETRY_COUNT`）
- 私有方法: 前导下划线（`_check_conversation`）
- 保护方法: 单前导下划线

### 文件结构

每个模块遵循一致的布局：

```python
"""模块文档字符串"""

# 标准库
import json
import time
from typing import Optional

# 第三方库
import lance

# 项目内部
from xiaomei_brain.memory.base import BaseMemory

# 常量
MAX_RETRY = 3

# 类定义
class MemoryManager:
    """类文档字符串"""
    
    # 公共方法
    def query(self, ...):
        ...
    
    # 私有方法
    def _internal_check(self, ...):
        ...
```

## 提交规范

### Commit Message

```
<type>(<scope>): <简短描述>

<详细描述（可选）>

<关联 Issue（可选）>
```

type:
- `feat`: 新功能
- `fix`: 修复
- `docs`: 文档
- `refactor`: 重构
- `test`: 测试
- `chore`: 构建/工具

例子：
```
feat(memory): 添加基于强度的记忆衰减机制

为记忆系统添加了 5 级衰减模型：Active → Normal → Weak → Fading → Extinct。
成功召回的强度提升 0.1，长期不用的逐渐衰减。

Closes #42
```

### PR 流程

1. Fork 仓库并创建分支
2. 修改代码并添加测试
3. 确保所有测试通过
4. 提交 PR，描述修改内容和动机
5. 等待 Review

## 测试

### 运行测试

```bash
# 运行所有测试
pytest

# 运行特定模块测试
pytest tests/test_memory.py

# 运行对照实验
python examples/run_experiment.py
```

### 测试规范

```python
# tests/test_memory/test_longterm.py
import pytest
from xiaomei_brain.memory import LongTermMemory

class TestLongTermMemory:
    def test_store_and_recall(self):
        memory = LongTermMemory("test_agent")
        memory.store("用户喜欢喝咖啡", user_id="user1")
        
        results = memory.recall("用户有什么喜好", top_k=5)
        assert len(results) >= 1
        assert "咖啡" in results[0].content
    
    def test_strength_decay(self):
        """验证记忆强度随时间衰减"""
        ...
    
    def test_cross_user_isolation(self):
        """验证不同用户的记忆相互隔离"""
        ...
```

## 发布流程

```bash
# 1. 更新版本号
vim pyproject.toml  # 修改 version

# 2. 更新 CHANGELOG

# 3. 打 Tag
git tag v0.2.0
git push origin v0.2.0

# 4. 构建并发布
python -m build
twine upload dist/*
```

## 项目布局

```
src/xiaomei_brain/
├── agent/                  # Agent 核心
│   └── core.py            # ReAct 循环、stream()
├── memory/                 # 记忆系统
│   ├── longterm.py        # 长期记忆
│   ├── dag.py              # DAG 摘要
│   ├── self_model.py      # 身份模型
│   └── conversation_db.py # 对话日志
├── consciousness/         # 意识层
│   ├── conscious_living.py # 主循环
│   ├── conversation_driver.py # 对话驱动
│   └── self_image_proxy.py  # 自我意象
├── drive/                 # 边缘系统
│   ├── engine.py          # Drive 引擎
│   ├── emotion.py         # 情绪
│   └── hormone.py         # 激素
├── purpose/               # 前额叶
│   ├── purpose_engine.py  # 目标引擎
│   └── intent.py          # 意图理解
├── metacognition/         # 元认知
│   ├── detectors.py       # 规则检测器
│   ├── scheduler.py       # 调度器
│   └── social_perception.py # 社交感知
├── gateway/               # 网关
│   └── router.py          # 消息路由
├── plugins/               # 插件
│   ├── channels/          # 渠道
│   ├── tools/             # 工具
│   └── providers/         # LLM Provider
├── cli/                   # CLI 命令
├── llm/                   # LLM 客户端
├── config/                # 配置系统
└── body/                  # 具身层
```

## 行为守则

1. **尊重**：尊重每一个贡献者和用户
2. **开放**：欢迎不同背景的贡献者
3. **质量**：代码质量优先，不为了快而凑合
4. **文档**：代码变更必须同步更新文档
5. **测试**：新功能必须包含测试
