# 能力包格式与安装（D1/D2）

`.xmcap` 是 ZIP 格式的不可变能力归档。D1 负责只读检查和预览；D2 在检查通过后支持安装到宿主机共享仓库，并由每个 Agent 独立启用。

## 归档结构

```text
sample-analysis.xmcap
├─ capability.yaml
├─ checksums.json
├─ capabilities/
├─ plugins/
├─ skills/
├─ scripts/
└─ resources/
```

`capability.yaml` 和 `checksums.json` 是归档必需文件。D2 可安装包还必须包含 `capabilities/` 能力清单，其他目录按实际能力选择。

## capability.yaml

```yaml
schema_version: 1
package:
  id: xiaomei.sample-analysis
  name: 样板分析能力
  version: 1.0.0
  description: 分析样板数据并形成报告
  publisher: xiaomei-brain
  license: Apache-2.0

capabilities:
  - id: sample_analysis
    name: 样板分析
    summary: 对结构化数据进行汇总和可视化

permissions:
  filesystem:
    - workspace_read
    - workspace_write
  network:
    - api.example.com
  process:
    - python_script
  secrets:
    - sample_api_key

requirements:
  xiaomei_brain: ">=0.1.0"
  python: ">=3.11"
  python_packages: []
  node_packages: []
  executables: []

contents:
  skills:
    - skills/sample-analysis/SKILL.md
  plugins:
    - plugins/sample_analysis/plugin.yaml
```

包 ID 可使用小写字母、数字、点号、短横线和下划线；能力 ID 不允许点号，以便与当前能力注册表保持一致。版本使用语义版本。

`contents` 中声明的每个文件必须真实存在。检查器对未知清单字段采取拒绝策略，避免拼写错误被静默忽略。

## checksums.json

```json
{
  "algorithm": "sha256",
  "files": {
    "capability.yaml": "<64位SHA-256>",
    "skills/sample-analysis/SKILL.md": "<64位SHA-256>"
  }
}
```

除 `checksums.json` 自身以外，归档中的每个普通文件都必须被校验清单覆盖；校验清单也不能引用归档外文件。

## D1 安全边界

- 归档上限 8 MB、文件数上限 512、解压后上限 128 MB；
- 拒绝绝对路径、`..`、Windows 盘符、反斜杠和重复路径；
- 拒绝符号链接、加密文件和异常压缩比；
- `capability.yaml` 必须是 UTF-8，且不超过 256 KB；
- Desktop 把文件和传输 SHA-256 交给目标 Agent，检查逻辑不在 React 中；
- 外部 Python、Node 和系统程序依赖只展示警告，不自动安装；
- 检查通过只代表格式与完整性有效，不代表来源可信，也不代表已经安装。

## D2 安装与启用边界

- 安装与启用是两个后端操作；Desktop 为常用流程提供“安装并启用”组合按钮；
- 安装内容按 SHA-256 缓存到宿主机共享仓库，同一 ID 和版本不允许对应不同内容；
- 每个 Agent 使用自己的 `capabilities.lock`，一个 Agent 启用不会影响其他 Agent；
- 归档解压到临时目录，验证完成后再原子移动到不可变安装目录；
- Agent 启动时重新校验文件集合和 SHA-256，损坏的能力包不会加载；
- 外部 Plugin 使用隔离模块命名空间加载，不把能力包目录加入全局 `sys.path`；
- Agent 自有 Skill、内置 Skill、内置 Plugin 和内置能力不能被能力包覆盖；
- 停用包后需要重启 Agent；重启时其运行时代码不再加载，已导入数据库的 Skill 也会被隐藏；
- D2 不自动安装 Python、Node 或系统程序依赖；声明这些依赖的包会被拒绝安装；
- D2 暂不提供卸载、升级、回滚、签名信任和大型归档分块传输，这些属于后续阶段。

默认目录结构：

```text
~/.xiaomei-brain/
├─ capability-packages/
│  ├─ cache/<sha256>.xmcap
│  └─ installed/<package-id>/<version>/
└─ <agent-id>/capabilities.lock
```

## Desktop 手动测试

开发环境可以运行：

```powershell
python scripts/create_sample_capability_package.py
```

脚本会把可运行的“文本统计”样板包写入系统临时目录并输出路径。连接 Agent 后：

1. 在 Desktop 的“设置 → Agent → 能力”中点击“导入能力”；
2. 选择 `text-statistics.xmcap`，确认预览无误后点击“安装并启用”；
3. 重启该 Agent；
4. 输入“统计这段文本的字符、行和词语数量：Hello 小美”；
5. 确认 Agent 调用了 `package_text_statistics`；
6. 切换到另一个 Agent，确认其能力包列表显示未启用，且不会加载该工具。
