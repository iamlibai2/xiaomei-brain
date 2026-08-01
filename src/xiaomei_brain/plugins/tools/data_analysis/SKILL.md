---
name: data-analysis
description: 分析 CSV、TSV 和 Excel 数据，形成可信的统计结论与基础图表
version: 1.0.0
tags: [data, analysis, csv, xlsx, chart, statistics]
requires_tools: [analyze_data, read_document, write_document, present_artifacts]
---

# 数据分析工作流

处理结构化表格数据时使用本技能。数据概览、缺失值和统计量必须来自
`analyze_data` 的实际结果，不能根据附件名称或局部预览猜测。

## 分析顺序

1. 先调用 `analyze_data(attachment_id=...)` 查看行列规模、字段类型、缺失值和数值分布。
2. 根据用户问题选择有业务意义的分组列与数值列，再调用分组汇总。
3. 需要图表时使用 `bar` 或 `line`；类别比较用柱状图，时间趋势用折线图。
4. 在回复中区分数据事实、计算结果和解释性判断，并说明截断或数据质量限制。
5. 需要正式 Excel、Word、PPT 或 PDF 报告时，再使用办公文档能力生成最终文件。

## 示例

```text
analyze_data(
  attachment_id="attachment-id",
  group_by="地区",
  value_columns=["销售额"],
  chart_type="bar",
  output_name="各地区销售额.svg"
)
```

## 完成标准

- 所有数字能追溯到工具结果。
- 明确缺失值、混合类型和截断情况。
- 不把相关性描述成因果关系。
- 图表标题、分组列和指标一致。
- 只有用户需要下载文件时才调用 `present_artifacts`。
