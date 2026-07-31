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

## 后续顺序

1. Spreadsheet writer：工作表、单元格、公式、样式和常用更新。
2. Presentation writer：主题、幻灯片、文本、图片、备注和常用修改。
3. PDF writer：从结构化内容创建 PDF；不原地编辑 PDF。
4. 可选视觉验收：存在 LibreOffice 等渲染后端时生成预览，不作为基础安装的硬依赖。

## 与视频等能力的关系

视频不进入 `write_document`。视频插件可直接注册自己的工具和 Skill，并复用插件执行现场、取消、进度与产物系统。只有时间轴、硬件编码或长任务预览成为多种视频插件共同需要的能力时，才增加一次视频领域扩展点。
