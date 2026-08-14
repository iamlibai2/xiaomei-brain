---
name: automatic-quotation
description: 基于已经进入 Workspace 的历史报价证据和企业已确认规则，为一个新需求形成建议价格、精确计算并生成正式报价
version: 0.1.0
tags: [quotation, quote, pricing, sales, workspace, history]
requires_tools:
  - get_current_workspace
  - upsert_business_record
  - query_business_records
  - list_business_context
  - preserve_workspace_asset_as_evidence
  - summarize_price_evidence
  - calculate_quotation
  - write_document
  - present_artifacts
---

# 自动报价

本技能处理日常的新报价。历史文件首次批量导入和结构发现由 `historical-quotation-onboarding` Skill 负责；不要因为生成一份报价而加载整套导入工具。

## 基本原则

1. 原始文件始终保留为 Workspace Asset，结构化数据不能取代原始证据。
2. 每条报价事实尽量保存 `source_asset_id` 和 `source_locator`。定位可以是页码、工作表及单元格、表格行或原文片段。
3. 不完整或低置信度内容保留为 Observation 或待确认项，不能补写成确定事实。
4. 历史事实、统计规律、已确认规则必须分开：统计规律不能未经确认自动成为报价规则。
5. 正式金额必须调用 `calculate_quotation`，不得由语言模型口算。
6. 缺少关键的产品匹配、价格来源、含税口径、税率、运费、数量或交付条件时，使用 Clarify。
7. 能完成一次性报价时不强制建立 Project；只有人物明确要求正式项目管理或采用报价交付标准时，才创建 `quotation.production` Project。

## 生成一份新报价

1. 明确客户、产品、规格、数量、单位和交付目标。
2. 查询匹配产品、客户、时间范围及价格口径的历史记录。不要把所有历史记录都交给模型。
3. 将筛选后的记录传给 `summarize_price_evidence`，取得价格区间、最新记录、数量最接近记录及引用。
4. 结合已确认 Context 判断当前适用价格。以下情况必须 Clarify：
   - 产品或规格存在多个可能匹配；
   - 价格明显过期或历史差异过大；
   - 含税/未税口径不明；
   - 税率、折扣、运费或交付条件不明且显著影响结果；
   - 报价低于已确认下限或超出 Agent 可以自主决定的边界。
5. 调用 `calculate_quotation` 计算明细和总价。
6. 向人物说明建议价格的依据、关键假设和例外。不能用“系统价格”掩盖实际只是历史推断。
7. 人物确认或现有规则足以裁定后，保存 quotation 和 quotation_items 记录。
8. 使用 `write_document` 生成正式 Word 或 Excel 报价，随后 `present_artifacts` 交付。
9. 已发送、签署或被客户接受的报价应作为不可变业务证据保存；编辑中的草稿仍可直接修改。

## 正式报价最低内容

- 报价编号、客户、日期和有效期；
- 产品、规格、数量、单位、单价和金额；
- 含税口径、税率、未税金额、税额、运费和含税总价；
- 付款、交付、包装、质保等适用条款；
- 关键假设和待确认事项；
- 本次报价的历史证据或明确的人工定价来源。

## 不能做的事

- 不从历史平均值直接推出企业最低售价。
- 不把历史报价中的错价自动结晶为规则。
- 不把不同税费口径的价格直接比较。
- 不因文件格式相似就认定是同一客户或同一产品。
- 不在能力包内保存客户真实数据、历史文件、API Key、密码或 Token。
