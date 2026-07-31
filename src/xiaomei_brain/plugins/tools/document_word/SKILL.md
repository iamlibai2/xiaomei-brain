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
  "blocks": [
    {"type": "heading", "level": 1, "text": "章节"},
    {"type": "paragraph", "text": "正文"},
    {"type": "list", "ordered": false, "items": ["第一项", "第二项"]},
    {"type": "table", "headers": ["项目", "结果"], "rows": [["A", "完成"]]},
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
    {"type": "append_blocks", "blocks": [{"type": "heading", "level": 1, "text": "补充"}]},
    {"type": "set_properties", "author": "作者"}
  ]
}
```

调用时传入当前消息中真实存在的 `source_attachment_id`。

## 完成标准

- 查看 `write_document` 返回的 `validation.valid`、段落数、表格数及内容预览。
- 不要把 JSON specification 当作最终产物。
- 最终只用 `present_artifacts` 交付经过验收的 DOCX。
