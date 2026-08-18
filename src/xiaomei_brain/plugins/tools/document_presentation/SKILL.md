---
name: presentation-documents
description: 创建、修改和验收 PowerPoint PPTX 演示文稿；按分析决策、商业提案、管理汇报、学术研究、教育培训、技术工程和品牌创意等场景规划叙事与页面设计
version: 1.0.0
tags: [presentation, powerpoint, pptx, slides]
requires_tools: [read, read_document, read_workspace_asset, write, write_document, list_workspace_assets, present_artifacts]
---

## Desktop 精确批注

Desktop 的 PPT 预览可能提供 `document_annotation kind="presentation"`。必须原样使用其中的
`slide`、`element_id`、`row`、`column`，不要按页面顺序重新猜测元素位置：

- `element_type="slide"`：使用 `update_slide` 修改整页背景、标题、正文或备注；只有用户明确要求时才使用 `move_slide` 或 `delete_slide`。
- `element_type="text"` 或 `shape`：使用 `update_element`；只有明确删除时才使用 `delete_element`。
- `element_type="table"` 且提供 `row`、`column`：使用 `update_table_cell`，行列号从 1 开始，可修改 `text`、`fill_color`、`text_color`、`font_size_pt`、`bold`。
- `element_type="image"`：替换图片时使用 `replace_image`，并提供当前消息中的 `attachment_id` 或受控工作区 `workspace_path`；只改大小和位置时使用 `update_element`。
- `element_type="chart"`：使用 `update_chart` 修改原生 PowerPoint 图表。可修改 `title`、`categories`、`series`、`show_legend` 和 `series_colors`；不要把原生图表转换成图片。修改数据时必须同时提供 `categories` 与 `series`，每个系列的 `values` 数量必须与分类数量一致。
- `element_type="line"`：使用 `update_element` 修改连接线。可修改 `line_color`、`line_width_pt`、`line_dash`、`start_arrow`、`end_arrow`、`line_transparency` 和位置；不要把连接线转换成图片或普通矩形。

始终把当前 PPT 附件的真实 ID 作为 `source_attachment_id` 传给 `write_document`。如果工具返回
`stale_presentation_selection`，说明预览所依据的版本已变化：停止修改，要求刷新预览后重新选择；不要绕过校验。

精确修改示例：

```json
{
  "operations": [
    {
      "type": "update_table_cell",
      "slide": 3,
      "element_id": "slide-3-shape-id-12",
      "row": 2,
      "column": 4,
      "text": "128 万元",
      "fill_color": "EAF2EC"
    },
    {
      "type": "replace_image",
      "slide": 5,
      "element_id": "slide-5-shape-id-9",
      "attachment_id": "attachment-2"
    },
    {
      "type": "update_chart",
      "slide": 6,
      "element_id": "slide-6-shape-id-14",
      "title": "季度销售额",
      "categories": ["Q1", "Q2", "Q3", "Q4"],
      "series": [{"name": "华东", "values": [120, 148, 172, 205]}],
      "show_legend": false,
      "series_colors": ["2F6B4F"]
    }
  ]
}
```

# 演示文稿工作流

用户要求创建或修改 PPTX 时使用本技能。先规划主题、页面结构、每页核心信息和
所需图片，再写 JSON specification，最后调用统一的 `write_document`。

## 场景规划

创建新演示文稿前，先读取 `references/slides_categories.md` 的通用规则与场景路由，
再根据受众、阅读任务和使用方式选择一个主场景，读取对应的场景文档：

- 分析与决策：`references/slides_categories/analysis-decision.md`
- 商业提案：`references/slides_categories/business-plan.md`
- 管理汇报：`references/slides_categories/management-report.md`
- 学术研究：`references/slides_categories/academic-research.md`
- 教育培训：`references/slides_categories/education-training.md`
- 技术工程：`references/slides_categories/tech-engineering.md`
- 品牌创意：`references/slides_categories/brand-creative.md`

只选择一个主场景；确有必要时可增加一个辅助场景，但主场景决定整份文稿的叙事、
信息密度和视觉语言。用户给出的模板、品牌规范、颜色、字体和风格参考始终优先。

场景文档是设计指导，不是固定工作流或页面模板。根据真实材料增删、合并和调整页面，
不要为了满足推荐页序而编造数据、案例、结论或来源。缺少事实时标为待补充、假设或示例。

默认根据场景自主设计，不自动套用固定主题。只有用户明确指定主题、模板或视觉风格时，
才将其映射到 specification 的 `theme`、页面结构和元素样式。场景文档中超出当前
`write_document` 能力的动画、自定义字体或复杂图形要求，应使用当前 writer 支持的
结构近似表达，不要输出 PPTD 专属语法。

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

`read_document` 的每页内容包含简洁的 `[元素索引]`，其中提供稳定的 `element_id`、
元素类型、名称、文字摘要和厘米坐标。用户没有在 Desktop 选中元素时，根据页码、
文字语义、元素类型和相对位置读取对应页面并自行判断目标；不要猜测元素序号。
若仍有多个同样合理的候选，再向用户确认，不要新增固定关键词匹配流程。

如果人物要求继续修改当前 Workspace 中以前生成的演示文稿，先用
`list_workspace_assets` 找到 working Asset，并把其 `asset_id` 作为
`source_asset_id` 传给 `write_document`。先用 `read_workspace_asset` 读取现有文稿，
再编写精确的修改 operations；不要猜测历史路径或要求人物重新上传。

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
      "type": "update_element",
      "slide": 2,
      "element_id": "slide-2-shape-3",
      "text": "更新后的文字",
      "text_color": "172033",
      "fill_color": "F7F9FC",
      "line_color": "2F6B4F",
      "line_width_pt": 2,
      "line_dash": "dash",
      "start_arrow": "none",
      "end_arrow": {"type": "triangle", "width": "med", "length": "lg"},
      "fill_transparency": 10,
      "line_transparency": 0,
      "font_size_pt": 20,
      "bold": true
    },
    {"type": "delete_element", "slide": 2, "element_id": "slide-2-shape-5"},
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

当 Desktop 提供 `document_annotation kind="presentation"` 时，必须原样使用其中的
`slide` 和 `element_id`，通过 `update_element` 精确修改该元素。支持修改 `text`、
`text_color`、`fill_color`、`line_color`、`font_size_pt`、`bold`、`x_cm`、`y_cm`、
`width_cm`、`height_cm`、`line_width_pt`、`line_dash`、`start_arrow`、`end_arrow`、
`fill_transparency` 和 `line_transparency`。`line_dash` 支持 `solid`、`dash`、`dot`、
`dash_dot`、`long_dash` 和 `long_dash_dot`；箭头支持 `none`、`triangle`、`stealth`、
`diamond`、`oval` 和 `open`。透明度范围为 0 到 100。只有人物明确要求删除选中元素时
才使用 `delete_element`。

## 完成标准

- 检查 `validation.valid`、页数、文字框数、图片数、备注页数和内容预览。
- 每页只保留一个清晰主题，避免把长文直接堆进幻灯片。
- JSON specification 不是最终产物。
- 最终只通过 `present_artifacts` 交付验收通过的 PPTX。
