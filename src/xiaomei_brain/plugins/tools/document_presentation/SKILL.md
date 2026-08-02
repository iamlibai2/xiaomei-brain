---
name: presentation-documents
description: 创建、修改和验收 PowerPoint PPTX 演示文稿
version: 1.0.0
tags: [presentation, powerpoint, pptx, slides]
requires_tools: [read_document, write, write_document, present_artifacts]
---

# 演示文稿工作流

用户要求创建或修改 PPTX 时使用本技能。先规划主题、页面结构、每页核心信息和
所需图片，再写 JSON specification，最后调用统一的 `write_document`。

## 创建

```json
{
  "properties": {"author": "小美", "title": "项目介绍"},
  "page": {"size": "wide"},
  "theme": {
    "background_color": "F7F9FC",
    "title_color": "172033",
    "text_color": "354052",
    "accent_color": "4F6BED",
    "font_family": "Microsoft YaHei",
    "title_size_pt": 30,
    "body_size_pt": 18
  },
  "slides": [
    {
      "type": "title",
      "title": "项目介绍",
      "subtitle": "让工作自然流动",
      "notes": "开场介绍项目背景。"
    },
    {
      "type": "content",
      "title": "核心能力",
      "bullets": [
        "理解用户真实意图",
        {"text": "跨渠道保持连续关系", "level": 1},
        "交付可复用的工作产物"
      ]
    },
    {
      "type": "image",
      "title": "产品界面",
      "image": {
        "attachment_id": "当前消息中的真实图片附件 ID",
        "x_cm": 5,
        "y_cm": 3.5,
        "width_cm": 24
      },
      "notes": "说明主要交互区域。"
    },
    {
      "type": "blank",
      "elements": [
        {
          "type": "text",
          "text": "谢谢",
          "x_cm": 4,
          "y_cm": 7,
          "width_cm": 25,
          "height_cm": 3,
          "size_pt": 36,
          "bold": true,
          "align": "center",
          "vertical": "middle"
        }
      ]
    }
  ]
}
```

`page.size` 支持 `wide`（16:9）和 `standard`（4:3）。页面类型支持
`title`、`section`、`content`、`image` 和 `blank`。

图片使用当前消息中的真实 `attachment_id`，或当前执行 workspace 中已有的
相对 `workspace_path`。两者只能提供一个。自定义文字元素的位置与尺寸以厘米为单位。

调用示例：

```text
write_document(
  format="presentation",
  specification_path="work/deck.json",
  output_name="项目介绍.pptx"
)
```

## 修改附件

先使用 `read_document` 阅读原演示文稿，再通过当前消息中的真实
`source_attachment_id` 修改文稿。用户上传的附件会生成副本，不覆盖上传源文件；
Agent 自己生成并交付的产物会原位更新，继续使用同一个产物 ID：

```json
{
  "operations": [
    {"type": "replace_text", "old": "旧名称", "new": "新名称", "all": true},
    {
      "type": "replace_placeholders",
      "values": {"customer_name": "星海科技", "date": "2026-08-01"}
    },
    {
      "type": "update_slide",
      "slide": 2,
      "title": "更新后的标题",
      "body": "更新后的正文",
      "notes": "新的演讲备注"
    },
    {
      "type": "append_slides",
      "slides": [{"type": "section", "title": "下一阶段", "subtitle": "实施计划"}]
    },
    {"type": "move_slide", "slide": 4, "to": 2},
    {"type": "delete_slide", "slide": 3},
    {"type": "set_properties", "author": "小美", "title": "最终方案"}
  ]
}
```

`update_slide` 可更新由本工具生成的标题、副标题和正文；对于任意外部模板，优先使用
`replace_text` 或 `replace_placeholders`，避免猜测模板中的形状结构。

## 完成标准

- 检查 `validation.valid`、页数、文字框数、图片数、备注页数和内容预览。
- 每页只保留一个清晰主题，避免把长文直接堆进幻灯片。
- JSON specification 不是最终产物。
- 最终只通过 `present_artifacts` 交付验收通过的 PPTX。
