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
- `element_type="chart"`：使用 `update_chart` 修改原生 PowerPoint 图表。可修改 `title`、`categories`、`series`、`show_legend` 和 `series_colors`；不要把原生图表转换成图片。分类图修改数据时必须同时提供 `categories` 与 `series`，每个系列的 `values` 数量必须与分类数量一致；散点图不使用 `categories`，每个系列提供长度相同的 `x_values` 与 `values`。
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
        },
        {
          "type": "shape",
          "shape": "round_rect",
          "text": "方案确认",
          "x_cm": 3,
          "y_cm": 4,
          "width_cm": 7,
          "height_cm": 2.5,
          "fill_color": "EAF2EC",
          "line_color": "2F6B4F",
          "line_width_pt": 1.5,
          "text_color": "172033",
          "font_size_pt": 18,
          "bold": true,
          "align": "center",
          "vertical": "middle"
        },
        {
          "type": "line",
          "connector": "elbow",
          "x_cm": 10,
          "y_cm": 5.25,
          "to_x_cm": 14,
          "to_y_cm": 8,
          "line_color": "2F6B4F",
          "line_width_pt": 2,
          "end_arrow": "triangle"
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

`slide.elements` 可创建可继续编辑的 PowerPoint 原生元素：

- `text`：文字框，提供 `text`、`x_cm`、`y_cm`、`width_cm`、`height_cm`；
- `image`：图片，提供受控附件或 Workspace 路径；
- `shape`：基础形状。`shape` 支持 `rectangle`、`round_rect`、`ellipse`、
  `triangle`、`diamond`、`hexagon`、`chevron`、`pentagon`、`parallelogram`、
  `trapezoid`，可同时设置文字、填充、边线、透明度和旋转；
- `line`：原生连接线。以 `x_cm`、`y_cm` 为起点，以 `to_x_cm`、`to_y_cm`
  为终点；`connector` 支持 `straight`、`elbow`、`curve`，并支持虚线和箭头；
- `table`：原生表格。用非空二维数组 `data` 提供单元格；单元格可直接写值，也可写
  `{"text": "...", "fill_color": "...", "text_color": "...", "bold": true}`。
  可用 `cell_style`、`header_style` 和 `column_widths_cm` 设置公共样式；
- `chart`：原生图表。用 `categories` 和 `series` 提供数据；`chart_type` 支持
  `column`、`column_stacked`、`bar`、`line`、`line_markers`、`pie`、`doughnut`、
  `area`、`scatter`、`scatter_lines`、`scatter_lines_no_markers`、`radar`、
  `radar_markers`、`radar_filled`，可设置标题、图例位置、系列颜色和数值标签。
  散点图不提供 `categories`，而是在每个系列中提供长度相同的 `x_values` 和
  `values`；雷达图仍使用公共 `categories`。
- `formula`：PowerPoint 原生公式。提供 `expression` 和位置尺寸；表达式支持文字、
  数字以及 `fraction`、`superscript`、`subscript`、`subscript_superscript`、
  `radical`、`nary`、`delimiter`、`sequence` 等结构，可继续在 Office 中编辑；
- `media`：PowerPoint 内嵌音频或视频。`media_kind` 为 `audio` 或 `video`，媒体与
  可选封面分别使用受控的 `attachment_id` / `workspace_path` 和
  `poster_attachment_id` / `poster_workspace_path`，并提供位置尺寸。

需要流程图或结构图时，优先组合原生 `shape` 与 `line`，不要把整个图绘制成图片。
需要表达数据时，优先使用原生 `table` 或 `chart`，让后续修改仍可定位到具体元素。

原生表格和图表示例：

```json
{
  "type": "blank",
  "elements": [
    {
      "type": "table",
      "x_cm": 1.5, "y_cm": 3, "width_cm": 14, "height_cm": 7,
      "header_style": {
        "fill_color": "2F6B4F", "text_color": "FFFFFF", "bold": true
      },
      "data": [
        ["地区", "一季度", "二季度"],
        ["华东", 120, 148],
        ["华南", 98, 126]
      ]
    },
    {
      "type": "chart",
      "chart_type": "column",
      "x_cm": 17, "y_cm": 3, "width_cm": 15, "height_cm": 9,
      "title": "季度销售额",
      "categories": ["一季度", "二季度"],
      "series": [
        {"name": "华东", "values": [120, 148]},
        {"name": "华南", "values": [98, 126]}
      ],
      "show_legend": true,
      "legend_position": "bottom",
      "series_colors": ["2F6B4F", "C6F24E"],
      "show_values": true
    }
  ]
}
```

原生公式和媒体示例：

```json
{
  "type": "blank",
  "elements": [
    {
      "type": "formula",
      "x_cm": 2, "y_cm": 1.5, "width_cm": 14, "height_cm": 3,
      "expression": {
        "type": "fraction",
        "numerator": "x",
        "denominator": {
          "type": "superscript", "base": "y", "superscript": 2
        }
      }
    },
    {
      "type": "media",
      "media_kind": "video",
      "workspace_path": "outputs/demo.mp4",
      "poster_workspace_path": "work/poster.png",
      "x_cm": 17, "y_cm": 3, "width_cm": 15, "height_cm": 9
    }
  ]
}
```

公式结构可嵌套。求和示例为
  `{"type":"nary","operator":"∑","lower":"i=1","upper":"n","expression":"xᵢ"}`；
三次根式为 `{"type":"radical","degree":3,"radicand":"x"}`。

页面可以设置常用原生转场，`slide.transition` 支持 `cut`、`fade`、`push`、`wipe`、
`split`，速度支持 `fast`、`medium`、`slow`。`push` 和 `wipe` 可设置
`direction: left/right/up/down`；还可设置 `advance_on_click` 和
`advance_after_ms`：

```json
{
  "type": "blank",
  "transition": {"type": "fade", "speed": "medium"},
  "elements": [{
    "type": "text",
    "text": "关键结论",
    "x_cm": 3, "y_cm": 4, "width_cm": 16, "height_cm": 3,
    "animation": {
      "effect": "fly",
      "direction": "left",
      "trigger": "after_previous",
      "duration_ms": 600,
      "delay_ms": 100
    }
  }]
}
```

对象进入动画写在 `slide.elements[].animation`，也可提供数组。第一版支持 `fade`、
`fly`、`wipe`、`zoom`；触发方式支持 `on_click`、`with_previous`、
`after_previous`。只在确实有助于讲述节奏时使用动画，不要给每个对象机械添加效果。

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
    {
      "type": "update_formula",
      "slide": 2,
      "element_id": "slide-2-shape-id-7",
      "expression": {"type": "radical", "radicand": "x"}
    },
    {
      "type": "replace_media",
      "slide": 3,
      "element_id": "slide-3-shape-id-5",
      "media_kind": "video",
      "workspace_path": "outputs/new-demo.mp4",
      "poster_workspace_path": "work/new-poster.png"
    },
    {
      "type": "set_transition",
      "slide": 2,
      "transition": {"type": "wipe", "direction": "left", "speed": "fast"}
    },
    {
      "type": "add_animation",
      "slide": 2,
      "element_id": "slide-2-shape-id-7",
      "animation": {
        "effect": "fade", "trigger": "on_click", "duration_ms": 500
      }
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

## 现有文稿中的高级对象

读取和预览已有 PPTX 时，Desktop 会保留并展示：

- 页面转场及自动换页时间；
- 常见对象进入动画的目标、效果、延时和时长；
- SmartArt 的节点文字、连接关系和布局名称；
- 原生公式和内嵌音视频。

转场与动画在浏览器中按原始元数据近似播放，原始 PPTX 内容不会被改写。复杂动作路径、
触发器组合和 PowerPoint 专有动画仍以 Office 中的真实效果为准。SmartArt 预览优先保证
业务节点与关系可读，不承诺复现 PowerPoint 私有布局算法的每个像素。

## 完成标准

- 每次调用 `write_document` 后都读取 `validation`。`issues` 中每项都提供 `page`、`element_id`、`severity`、`reason` 和 `suggestion`。
- `delivery_ready=false` 表示存在阻断交付的确定性错误。根据问题定位修改 JSON specification，再次调用 `write_document`；不要交付未通过验收的 PPTX。
- `severity=warning` 是重叠、字号、文字溢出、对比度或内容密度的保守提示。结合页面意图判断并尽量修正；刻意叠放等合理设计不需要机械修改。
- 只有 `validation.delivery_ready=true` 后才调用 `present_artifacts`。系统自动产物交付也会遵守这一门禁。
- 检查 `validation.valid`、页数、文字框数、图片数、备注页数和内容预览。
- 每页只保留一个清晰主题，避免把长文直接堆进幻灯片。
- JSON specification 不是最终产物。
- 最终只通过 `present_artifacts` 交付验收通过的 PPTX。
