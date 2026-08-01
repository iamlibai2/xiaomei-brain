---
name: word-documents
description: 创建、修改和验收 Word DOCX 文档
version: 1.2.0
tags: [word, docx, document, report]
requires_tools: [read_document, write, write_document, preview_word_themes, present_artifacts, clarify]
---

## 主题选择交互

不要为了任何 Word 请求都打断用户。按以下顺序决定主题：

1. 用户已经指定主题、颜色或品牌规范时，直接采用，不再询问。
2. 修改已有文档或模板时，默认保持原文档风格，不再询问。
3. 简短、低风险文档可根据用途自动选择最合适的内置主题。
4. 新建正式文档且视觉方向会明显影响结果、用户又没有说明偏好时：
   - 调用 `preview_word_themes` 生成真实 Word 渲染的主题对比图；
   - 立即调用 `present_artifacts` 展示返回的 `output_path`；
   - 再调用 `clarify`，选项固定为“商务蓝、现代简约、暖色专业、科技风格”；
   - 将选择分别映射为 `business-blue`、`modern-minimal`、
     `warm-professional`、`technology`，写入 `theme.preset`。
5. 用户表示“你决定”“都可以”时自行选择，不再询问。

预览图片只用于选择主题，不作为最终文档产物再次交付。最终仍只交付验收后的 DOCX。

# Word 文档工作流

用户要求创建或修改 DOCX 时使用本技能。

## 创建

先用 `write` 在当前 workspace 写一个 JSON specification，再调用 `write_document`：

```json
{
  "title": "报告标题",
  "subtitle": "可选副标题",
  "properties": {"author": "作者", "subject": "主题"},
  "theme": {"preset": "business-blue"},
  "visual_validation": true,
  "page": {
    "size": "A4",
    "orientation": "portrait",
    "margins_cm": {"top": 2.54, "right": 2.54, "bottom": 2.54, "left": 2.54}
  },
  "header": {"text": "企业报告"},
  "footer": {"text": "第 ", "page_number": true},
  "blocks": [
    {"type": "heading", "level": 1, "text": "章节"},
    {"type": "paragraph", "text": "正文"},
    {"type": "list", "ordered": false, "items": ["第一项", "第二项"]},
    {
      "type": "table",
      "headers": ["项目", "结果"],
      "rows": [["A", "完成"]],
      "column_widths_cm": [8, 6]
    },
    {
      "type": "image",
      "attachment_id": "当前消息中的真实图片附件 ID",
      "width_cm": 12,
      "align": "center",
      "caption": "图片说明"
    },
    {
      "type": "image",
      "workspace_path": "work/generated-cover.png",
      "width_cm": 12,
      "align": "center"
    },
    {"type": "quote", "text": "引用"},
    {"type": "page_break"}
  ]
}
```

### 主题与排版

创建新文档时必须根据用途选择一个统一主题，不要为每个区块随机指定颜色：

- `business-blue`：企业报告、方案、报价和正式汇报，默认选择。
- `modern-minimal`：技术文档、产品规范和说明书。
- `warm-professional`：培训、人事和内部沟通材料。
- `technology`：AI、软件、数据和技术解决方案。

主题会统一标题层级、正文行距、段落间距、列表、引用、图注、页眉页脚及
表格样式。只有用户明确提供品牌规范时，才在 `theme` 中覆盖字体和颜色。

专业文档应遵循：

- 使用内置标题层级，不要用加粗正文冒充标题。
- 不要手工输入 `•`，列表必须使用 `list` block。
- 每个一级章节只表达一个主题，避免连续堆叠短标题。
- 表格应使用简洁表头、适当列宽和短句；复杂说明移到表格下方。
- 图片应有明确用途和图注，不要仅为装饰插入无关图片。
- 正式交付的新文档默认设置 `"visual_validation": true`。渲染后端不可用时
  文档仍可交付，但需要如实说明未完成本机渲染检查。

调用示例：

```text
write_document(
  format="word",
  specification_path="work/report.json",
  output_name="报告.docx"
)
```

## 修改附件

先用 `read_document` 理解原文，再写 operations specification。原附件不会被覆盖：

```json
{
  "operations": [
    {"type": "replace_text", "old": "旧内容", "new": "新内容", "all": true},
    {
      "type": "replace_placeholders",
      "values": {
        "customer_name": "星海科技",
        "project_name": "智能办公平台"
      }
    },
    {
      "type": "insert_blocks_after",
      "marker": "{{DETAILS}}",
      "remove_marker": true,
      "blocks": [
        {"type": "heading", "level": 1, "text": "项目详情"},
        {"type": "paragraph", "text": "正文"}
      ]
    },
    {
      "type": "set_page_layout",
      "size": "A4",
      "orientation": "landscape",
      "margins_cm": {"top": 2, "right": 1.5, "bottom": 2, "left": 1.5}
    },
    {
      "type": "set_header_footer",
      "header": {"text": "新页眉"},
      "footer": {"text": "第 ", "page_number": true}
    },
    {"type": "append_blocks", "blocks": [{"type": "heading", "level": 1, "text": "补充"}]},
    {"type": "set_properties", "author": "作者"}
  ]
}
```

调用时传入当前消息中真实存在的 `source_attachment_id`。

模板占位符可以位于正文、表格、页眉或页脚中。名称既可写成
`customer_name`，也可写成完整的 `{{customer_name}}`。默认情况下，
模板中缺少任一要求替换的占位符都会导致失败；确实允许模板没有该字段时，
显式设置 `"allow_missing": true`。

`insert_blocks_after` 当前只在 Word 正文中定位标记，适合在企业模板的指定
位置插入章节、段落、列表和表格。

图片使用以下两种受控来源之一：当前消息中真实存在的图片 `attachment_id`，
或当前执行 workspace 内已经生成的图片 `workspace_path`。`workspace_path` 必须
是相对路径（如 `work/chart.png`），禁止绝对路径和 `..`。不要同时填写两个字段。
图片可用于新建文档，也可通过 `append_blocks` 或 `insert_blocks_after` 插入模板。

只要 `write_document` 可用，就必须使用它生成或修改 Word；不要绕过它改用
`python-docx` 或临时脚本。若调用失败，应说明具体错误，不要声称工具不存在，
也不要静默换用另一套文档生成方式。

## 完成标准

- 查看 `write_document` 返回的 `validation.valid`、段落数、表格数及内容预览。
- 查看 `validation.render_validation`：`passed` 表示已由 Microsoft Office COM
  或 LibreOffice 成功渲染；`warning` 时检查空白页；`unavailable` 表示本机
  没有可用渲染后端，不能谎称已完成视觉检查。
- 不要把 JSON specification 当作最终产物。
- 最终只用 `present_artifacts` 交付经过验收的 DOCX。
