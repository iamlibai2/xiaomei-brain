# 能力包格式（D1）

`.xmcap` 是 ZIP 格式的只读能力归档。D1 只检查和预览，不安装、不解压到磁盘，也不执行包内代码。

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

只有 `capability.yaml` 和 `checksums.json` 是必需文件，其他目录按实际能力选择。

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

`contents` 中声明的每个文件必须真实存在。D1 对未知清单字段采取拒绝策略，避免拼写错误被静默忽略。

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

安装、启用、多版本、依赖环境与回滚属于 D2/D3。

## Desktop 手动测试

开发环境可以运行：

```powershell
python scripts/create_sample_capability_package.py
```

脚本会把一个不含可执行代码的有效样板包写入系统临时目录并输出路径。连接 Agent 后，在 Desktop 的“设置 → Agent → 能力”中点击“导入能力”，选择该文件即可查看 D1 预览。样板包不会被安装。
