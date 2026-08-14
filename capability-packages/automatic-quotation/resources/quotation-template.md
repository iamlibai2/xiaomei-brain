# {{company_name}}报价单

- 报价编号：{{quotation_number}}
- 客户名称：{{customer_name}}
- 报价日期：{{quoted_at}}
- 有效期至：{{valid_until}}

| 序号 | 产品名称 | 规格型号 | 数量 | 单位 | 单价 | 税率 | 含税金额 |
|---:|---|---|---:|---|---:|---:|---:|
| {{line_no}} | {{product_name}} | {{specification}} | {{quantity}} | {{unit}} | {{unit_price}} | {{tax_rate}} | {{gross_amount}} |

- 未税金额：{{net_total}}
- 税额：{{tax_total}}
- 运费：{{shipping_fee}}
- 含税总价：{{grand_total}}

## 商务条款

{{commercial_terms}}

## 报价说明与假设

{{assumptions}}

> 正式报价中的金额必须来自 `calculate_quotation`，历史价格依据应能追溯到 Workspace Asset 或业务记录。
