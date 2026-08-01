---
name: pdf-documents
description: 创建和验收具有稳定文本层的 PDF 文档
version: 1.0.0
tags: [pdf, report, document, printable]
requires_tools: [read_document, write, write_document, present_artifacts]
---

# PDF 文档工作流

用户要求创建正式报告、可打印材料或固定版式 PDF 时使用本技能。第一版只创建新的
PDF，不原地修改上传的 PDF。先规划页面、标题层级、正文、表格与图片，再在当前
workspace 写 JSON specification，最后调用 `write_document`。

```json
{
  "properties": {"title": "项目报告", "author": "小美", "subject": "阶段总结"},
  "page": {
    "size": "A4",
    "orientation": "portrait",
    "margins_cm": {"top": 2.2, "right": 2.2, "bottom": 2.2, "left": 2.2}
  },
  "theme": {
    "font": "STSong-Light",
    "title_color": "172033",
    "text_color": "354052",
    "accent_color": "4F6BED",
    "muted_color": "6B7280",
    "title_size_pt": 24,
    "body_size_pt": 10.5,
    "line_spacing": 1.45
  },
  "header": {"text": "项目报告"},
  "footer": {"text": "第", "page_number": true},
  "blocks": [
    {"type": "heading", "level": 1, "text": "项目报告"},
    {"type": "paragraph", "text": "这是报告摘要。", "align": "justify"},
    {"type": "heading", "level": 2, "text": "主要结论"},
    {"type": "list", "ordered": false, "items": ["结论一", "结论二"]},
    {
      "type": "table",
      "headers": ["指标", "结果"],
      "rows": [["完成率", "90%"], ["风险", "低"]],
      "column_widths": [5, 10]
    },
    {
      "type": "image",
      "attachment_id": "当前消息中的真实图片附件 ID",
      "width_cm": 12,
      "align": "center",
      "caption": "图 1：结果概览"
    },
    {"type": "quote", "text": "一段需要强调的内容。"},
    {"type": "page_break"},
    {"type": "heading", "level": 2, "text": "附录"}
  ]
}
```

```text
write_document(
  format="pdf",
  specification_path="work/report.json",
  output_name="项目报告.pdf"
)
```

图片来源只能是当前消息中的真实 `attachment_id`，或当前执行 workspace 中已有的
相对 `workspace_path`。两者不能同时提供。

默认 `STSong-Light` 支持中文。也可选择 `Helvetica`、`Times-Roman` 或 `Courier`，
但这些字体不适合中文正文。

## 完成标准

- 检查 `validation.valid`、页数、内容块数、图片数和文本层。
- PDF 必须能够重新打开，并能通过 `read_document` 提取正文。
- JSON specification 不是最终产物。
- 最终只通过 `present_artifacts` 交付验收通过的 PDF。
