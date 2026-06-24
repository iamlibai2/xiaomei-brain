# CONTRIBUTING.md — 贡献指南

欢迎贡献！本文说明如何参与 xiaomei-brain 的开发。

---

## 环境准备

```bash
# 1. 克隆仓库
git clone https://github.com/iamlibai2/xiaomei-brain.git
cd xiaomei-brain

# 2. 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 3. 安装开发依赖
pip install -e ".[dev]"
```

---

## 开发流程

### 分支

- `main` — 稳定分支
- `feature/<name>` — 功能分支
- `fix/<name>` — 修复分支

```bash
git checkout -b feature/your-feature
```

### 提交前检查

```bash
# 运行测试
PYTHONPATH=src python3 -m pytest tests/ -v

# 确认没有明显的 Python 语法错误
python3 -c "import ast; [ast.parse(open(f).read()) for f in ...]"  # 略
```

### Commit 风格

参考已有 commit：

```
feat: memory + channel CLI — 记忆管理和渠道连接向导
fix: cross-platform compatibility + Windows security hardening
```

格式：`type: 简短描述`

| type | 场景 |
|------|------|
| `feat` | 新功能 |
| `fix` | 修复 bug |
| `docs` | 文档 |
| `refactor` | 重构（不改行为） |
| `test` | 测试 |
| `chore` | 杂项（CI、构建、依赖） |

### Pull Request

1. 确保所有测试通过
2. PR 标题遵循上述格式
3. 描述中说明：做了什么、为什么这样做、测试方法
4. 重大改动（新层、新子系统）请附设计文档 `docs/<name>-design.md`

---

## 代码风格

### 基本原则

- 跟随已有代码风格，不要混用
- 类型标注：公共 API 需要，内部函数可省略
- Docstring：工具函数和公共 API 需要，简单的私有函数可省略
- 导入顺序：标准库 → 第三方 → 项目内部

### 文件组织

- 每个模块一个职责，不要一个文件做太多事
- 新功能优先放在对应的子系统中（agent/memory/drive/purpose/etc.）
- CLI 命令放在 `cli/`
- 配置定义放在 `config/`
- 工具放在 `tools/builtin/` 或 `plugins/tools/`

---

## 测试

```bash
# 运行所有测试（跳过 slow 标记的）
PYTHONPATH=src python3 -m pytest tests/ -v -m "not slow"

# 运行指定测试
PYTHONPATH=src python3 -m pytest tests/test_smoke.py -v

# 用覆盖率
PYTHONPATH=src python3 -m pytest tests/ -v --cov=src/xiaomei_brain
```

### 写测试的约定

- 测试文件放在 `tests/`，命名 `test_<module>.py`
- 不需要 LLM 调用的测试用 `tests/test_smoke.py` 的模式
- 需要 LLM 调用的测试标记 `@pytest.mark.slow`

---

## 架构指引

- [ARCHITECTURE.md](./docs/ARCHITECTURE.md) — 系统架构、启动流程、消息流程
- [CONFIG.md](./docs/CONFIG.md) — 配置系统
- [IDENTITY.md](./docs/IDENTITY.md) — Agent 身份定制
- [PLUGIN.md](./docs/PLUGIN.md) — 插件开发指南

---

## 获取帮助

- Issue: https://github.com/iamlibai2/xiaomei-brain/issues
