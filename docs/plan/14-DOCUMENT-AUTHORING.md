# 文档生产系统

## 核心结论

插件化不等于所有能力共用一个庞大实现。核心只提供稳定执行边界；具体格式、参数和验收规则属于插件。

Agent 的统一入口是：

```text
write_document(format, specification_path, output_name, source_attachment_id?)
```

`write_document` 本身由 `document_io` 插件注册，不在 `AgentManager` 中硬编码。格式插件通过 `PluginContext` 注册 writer 和技能目录。

## 插件执行现场

`ToolExecutionContext` 提供通用且可信的：

- 当前输入附件快照；
- workspace 根目录；
- 最终 output 根目录；
- 原有 artifact 与 speech 回调。

实时对话使用 Agent workspace；委托使用自己的 `inputs/work/outputs` 隔离目录。插件只使用这个执行现场，不猜测 `~/.xiaomei-brain` 路径。

这是一项一次性基础设施。新增文档格式时，只需增加：

```text
document_<format>/
├─ extractor.py
├─ writer.py
├─ adapter.py
├─ plugin.yaml
└─ SKILL.md
```

不再修改 Gateway、Desktop、ConversationDriver 或 AgentManager。

## Word V1

Word 插件支持：

- 从 JSON specification 创建 DOCX；
- 标题、段落、列表、表格、引用和分页；
- 修改当前执行现场中的 DOCX 附件；
- 文字替换、追加结构块和修改核心属性；
- 原附件不可覆盖，只生成新的输出文件；
- 保存后用 `python-docx` 重开，再用 Word extractor 重新提取语义内容；
- 验收成功后交给现有 artifact 管线和 `present_artifacts`。

## Word V2：企业模板

第一阶段支持：

- 跨多个 Word Run 替换文字，同时保留未受影响的原格式；
- 批量替换正文、嵌套表格、页眉和页脚中的模板占位符；
- 缺少必需占位符时明确失败，避免悄悄生成不完整合同或报告；
- 在正文指定标记处插入标题、段落、列表和表格；
- 只通过当前轮受信任的图片附件 ID 插入图片和图注；
- 设置 A4/Letter、横纵向、页边距、默认字体、页眉、页脚和动态页码；
- 原模板不覆盖，最终文档继续经过结构和语义验收。

后续可增加模板库、目录、复杂图文布局和可选视觉验收，不把这些格式参数
加入 `write_document` 的稳定工具协议。

## Spreadsheet V1

Spreadsheet插件复用同一个 `write_document` 和执行现场，不增加格式专用RPC。

支持：

- 创建和非破坏性修改XLSX；
- 多工作表、单元格和二维行数据；
- 公式、日期/日期时间/时间类型及数字格式；
- 字体、填充、对齐、边框和区域样式；
- 合并单元格、冻结窗格、自动筛选、列宽和行高；
- 添加、重命名工作表和向已有工作表追加数据；
- 限制最大行列和单次区域操作规模，防止异常规格消耗过多资源；
- 保存后用 `openpyxl` 重开，校验工作表、公式和内容预览。

Writer只保存公式，不在服务端计算公式缓存值；最终数值由Excel、LibreOffice等
表格软件打开后重新计算。图表、数据验证、条件格式和数据透视表属于后续版本。

## Presentation V1

Presentation 插件复用同一 `write_document` 和执行现场，支持：

- 创建 wide（16:9）或 standard（4:3）PPTX；
- 统一页面背景、标题、正文、强调色、字体和字号；
- title、section、content、image 和 blank 五种基础页面；
- 分级要点、受控图片附件、workspace 图片、自定义文字框和演讲备注；
- 替换文字与模板占位符、更新页面、追加、删除和移动页面；
- 原附件不覆盖，保存后按真实页面关系顺序重新提取并验收文字、图片和备注。

## 后续顺序

1. PDF writer：从结构化内容创建 PDF；不原地编辑 PDF。
2. 可选视觉验收：存在 LibreOffice 等渲染后端时生成预览，不作为基础安装的硬依赖。

## 与视频等能力的关系

视频不进入 `write_document`。视频插件可直接注册自己的工具和 Skill，并复用插件执行现场、取消、进度与产物系统。只有时间轴、硬件编码或长任务预览成为多种视频插件共同需要的能力时，才增加一次视频领域扩展点。
