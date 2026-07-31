---
name: word-documents
description: 创建、修改和验收 Word DOCX 文档
version: 1.0.0
tags: [word, docx, document, report]
requires_tools: [read_document, write_file, write_document, present_artifacts]
---

# Word 文档工作流

用户要求创建或修改 DOCX 时使用本技能。

## 创建

先用 `write_file` 在当前 workspace 写一个 JSON specification，再调用 `write_document`：

```json
{
  "title": "报告标题",
  "subtitle": "可选副标题",
  "properties": {"author": "作者", "subject": "主题"},
  "default_style": {"font": "Microsoft YaHei", "size_pt": 11},
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
    {"type": "table", "headers": ["项目", "结果"], "rows": [["A", "完成"]]},
    {
      "type": "image",
      "attachment_id": "当前消息中的真实图片附件 ID",
      "width_cm": 12,
      "align": "center",
      "caption": "图片说明"
    },
    {"type": "quote", "text": "引用"},
    {"type": "page_break"}
  ]
}
```

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

图片必须引用当前消息中真实存在的图片 `attachment_id`，不要向 specification
写入任意本机文件路径。图片可用于新建文档，也可通过 `append_blocks` 或
`insert_blocks_after` 插入模板。

## 完成标准

- 查看 `write_document` 返回的 `validation.valid`、段落数、表格数及内容预览。
- 不要把 JSON specification 当作最终产物。
- 最终只用 `present_artifacts` 交付经过验收的 DOCX。
