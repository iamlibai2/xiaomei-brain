---
name: historical-quotation-onboarding
description: 将一批 Word Excel PDF 或扫描历史报价导入 Workspace，保留来源证据，发现稳定字段并形成可查询的报价业务数据
version: 0.1.0
tags: [quotation, import, history, workspace, onboarding]
requires_tools:
  - create_workspace
  - create_data_source
  - define_collection
  - add_collection_fields
  - import_tabular_data
  - record_observation
  - upsert_business_record
  - normalize_quotation_lines
  - read_workspace_asset
---

# 历史报价建库

本技能只负责首次导入、增量补充历史报价和形成报价业务画像。日常生成新报价使用 `automatic-quotation` Skill。

## 工作原则

1. 原始文件保留为 Workspace Asset，结构化数据不能取代原始证据。
2. 每条事实尽量保存 `source_asset_id` 和 `source_locator`，定位到页码、工作表及单元格、表格行或原文片段。
3. 不完整或低置信度内容保存为 Observation 或待确认项，不能补写成确定事实。
4. 几十份以上文件进入委托分批处理，每批保存进度；不要一次塞进模型上下文。
5. Excel/CSV 优先使用表格导入；Word/PDF 使用文档读取；扫描件需要 OCR 后才能提取。

## 第一版业务结构

创建或进入持续使用的“报价经营” Workspace，只先建立稳定的两个 Collection。

### historical_quotations

- quotation_number：报价编号，text
- customer_name：客户名称，text
- quoted_at：报价日期，date
- tax_mode：含税口径，enum
- tax_rate：税率，number
- shipping_fee：运费，money
- payment_terms：付款条件，text
- delivery_terms：交付条件，text
- validity：报价有效期，text
- source_asset_id：来源资产，text
- source_locator：来源位置，text
- extraction_confidence：提取置信度，number

### quotation_items

- quotation_number：报价编号，text
- product_name_raw：原产品名称，text
- product_name：标准产品名称，text
- specification：规格型号，text
- quantity：数量，number
- unit：单位，text
- unit_price：单价，money
- amount：金额，money
- source_asset_id：来源资产，text
- source_locator：来源位置，text

只有产品和客户归并已经产生真实价值时，再建立 products 和 customers。无法确定同名是否同物时保留原始名称，不要强行合并。

## 提取与写入

1. 从文件中提取报价头和明细。
2. 用 `normalize_quotation_lines` 转换金额、数量和常见字段格式。
3. 规范化成功不等于产品匹配成功；别名、简称和税费口径必须有证据或人物确认。
4. 先 `record_observation`，再把 observation_id 关联到写入的业务记录。
5. 稳定字段重复出现后才扩展 Collection；罕见内容可暂存 JSON 扩展字段。
6. 解析失败只标记当前文件，不得中止整批任务；重复执行应能识别已经导入的来源。

## 形成报价业务画像

每批处理后汇总：

- 成功、待确认和失败的文件数量；
- 常见产品与规格；
- 客户历史报价次数；
- 同产品价格区间和变化；
- 常见税率、含税口径、运费与付款条件；
- 疑似修订版、异常低价、重复报价和无法解析项；
- 值得确认但尚未成为规则的规律。

必须区分：

- “历史记录显示”：可以报告的事实或统计；
- “可能存在”：需要人物判断的规律；
- “以后默认”：只有人物明确确认后，才能保存为 Workspace Context。

价格、折扣、税率等如需对所有写入一致生效，应在确认后配置为可执行 Context；不要只在 Skill 中写一句规则假装已经执行。
