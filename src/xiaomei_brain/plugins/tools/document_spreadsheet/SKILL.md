---
name: spreadsheet-documents
description: 创建、修改和验收 Excel XLSX 工作簿
version: 1.0.0
tags: [spreadsheet, excel, xlsx, data]
requires_tools: [read_document, write, write_document, present_artifacts]
---

# 电子表格工作流

用户要求创建或修改 XLSX 时使用本技能。先规划工作表、字段、公式和格式，
再写 JSON specification，最后调用统一的 `write_document`。

## 创建

```json
{
  "properties": {"creator": "小美", "title": "销售统计"},
  "sheets": [
    {
      "name": "销售明细",
      "rows": [
        ["产品", "数量", "单价", "金额"],
        ["A", 2, 19.9, {"formula": "B2*C2", "number_format": "¥#,##0.00"}]
      ],
      "cells": {
        "A5": {"value": "统计日期"},
        "B5": {"value": "2026-07-31", "type": "date", "number_format": "yyyy-mm-dd"}
      },
      "merged_cells": ["A7:D7"],
      "styles": [
        {
          "range": "A1:D1",
          "style": {
            "font": {"bold": true, "color": "FFFFFF"},
            "fill": "2F5597",
            "alignment": {"horizontal": "center"},
            "border": {"style": "thin", "color": "D9E2F3"}
          }
        }
      ],
      "freeze_panes": "A2",
      "auto_filter": "A1:D3",
      "column_widths": {"A": 18, "B": 12, "C": 12, "D": 14},
      "row_heights": {"1": 24}
    }
  ]
}
```

```text
write_document(
  format="spreadsheet",
  specification_path="work/sales.json",
  output_name="销售统计.xlsx"
)
```

公式可写成以 `=` 开头的 value，也可使用 `{"formula": "B2*C2"}`。
Writer只保存并校验公式，不负责计算公式结果；Excel或其他表格软件打开后计算。

## 修改附件

先使用 `read_document` 阅读工作表，再针对当前附件编写 operations：

```json
{
  "operations": [
    {
      "type": "set_cells",
      "sheet": "销售明细",
      "cells": {
        "B2": 3,
        "D2": {"formula": "B2*C2", "number_format": "¥#,##0.00"}
      }
    },
    {
      "type": "append_rows",
      "sheet": "销售明细",
      "rows": [["B", 5, 9.9, {"formula": "B4*C4"}]]
    },
    {
      "type": "style_range",
      "sheet": "销售明细",
      "range": "A1:D1",
      "style": {"font": {"bold": true}, "fill": "D9EAF7"}
    },
    {
      "type": "set_sheet_layout",
      "sheet": "销售明细",
      "freeze_panes": "A2",
      "auto_filter": "A1:D4",
      "column_widths": {"A": 20}
    },
    {
      "type": "add_sheet",
      "specification": {
        "name": "说明",
        "rows": [["字段", "含义"], ["金额", "数量乘以单价"]]
      }
    },
    {
      "type": "rename_sheet",
      "sheet": "说明",
      "new_name": "数据说明"
    }
  ]
}
```

修改时传入当前消息中的真实 `source_attachment_id`。原工作簿不会被覆盖。

## 完成标准

- 检查 `validation.valid`、工作表名称、公式数和内容预览。
- 说明公式结果需要表格软件重新计算，不虚构计算后的缓存值。
- JSON specification不是最终产物。
- 最终只通过 `present_artifacts` 交付验收通过的XLSX。
