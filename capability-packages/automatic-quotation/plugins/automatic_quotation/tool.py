"""Deterministic helpers for evidence-based quotation work."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import re
from statistics import median
from typing import Any

from xiaomei_brain.tools.base import Tool


_MONEY_CLEANER = re.compile(r"[^0-9.()\-]")


def _decimal(value: Any, *, field: str, allow_empty: bool = False) -> Decimal:
    if value is None or value == "":
        if allow_empty:
            return Decimal("0")
        raise ValueError(f"{field} 不能为空")
    if isinstance(value, bool):
        raise ValueError(f"{field} 必须是数字")
    text = str(value).strip().replace(",", "").replace("，", "")
    negative = text.startswith("(") and text.endswith(")")
    text = _MONEY_CLEANER.sub("", text)
    if negative:
        text = f"-{text.strip('()')}"
    try:
        result = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} 不是有效数字: {value}") from exc
    if not result.is_finite():
        raise ValueError(f"{field} 必须是有限数字")
    return result


def _rate(value: Any, *, field: str) -> Decimal:
    result = _decimal(value, field=field, allow_empty=True)
    if result > 1:
        result /= Decimal("100")
    if result < 0 or result > 1:
        raise ValueError(f"{field} 必须在 0～1 或 0～100 之间")
    return result


def _quantize(value: Decimal, precision: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP)


def _number(value: Decimal, precision: int = 6) -> int | float:
    normalized = value.quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP)
    if normalized == normalized.to_integral():
        return int(normalized)
    return float(normalized)


def _text(value: Any) -> str:
    return str(value or "").strip()


def normalize_quotation_lines(lines: list[dict[str, Any]]) -> str:
    """Normalize common historical quotation fields without inventing missing facts."""
    if not isinstance(lines, list) or not lines:
        raise ValueError("lines 必须包含至少一条报价明细")
    normalized: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for index, raw in enumerate(lines, start=1):
        if not isinstance(raw, dict):
            issues.append({"line": index, "field": "line", "message": "明细不是对象"})
            continue
        product = _text(raw.get("product_name") or raw.get("product") or raw.get("name"))
        specification = _text(raw.get("specification") or raw.get("model") or raw.get("spec"))
        unit = _text(raw.get("unit"))
        try:
            quantity = _decimal(raw.get("quantity"), field=f"第 {index} 行数量")
            unit_price = _decimal(raw.get("unit_price"), field=f"第 {index} 行单价")
            if quantity <= 0:
                raise ValueError("数量必须大于 0")
            if unit_price < 0:
                raise ValueError("单价不能小于 0")
        except ValueError as exc:
            issues.append({"line": index, "field": "number", "message": str(exc)})
            continue
        if not product:
            issues.append({"line": index, "field": "product_name", "message": "缺少产品名称"})
        normalized.append({
            "line_no": index,
            "product_name": product,
            "specification": specification,
            "quantity": _number(quantity),
            "unit": unit,
            "unit_price": _number(unit_price),
            "currency": _text(raw.get("currency")) or "CNY",
            "source_asset_id": _text(raw.get("source_asset_id")),
            "source_locator": _text(raw.get("source_locator")),
            "raw": raw,
        })
    return json.dumps({
        "normalized_lines": normalized,
        "issues": issues,
        "ready_count": len(normalized),
        "rejected_count": len(lines) - len(normalized),
        "warning": "规范化只转换格式，不证明产品归并、价格有效性或当前适用性。",
    }, ensure_ascii=False)


def summarize_price_evidence(
    records: list[dict[str, Any]],
    target_quantity: float = 0,
) -> str:
    """Summarize already-filtered historical price records and preserve citations."""
    if not isinstance(records, list) or not records:
        raise ValueError("records 必须包含查询得到的历史价格记录")
    accepted: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for index, raw in enumerate(records, start=1):
        if not isinstance(raw, dict):
            issues.append({"record": index, "message": "记录不是对象"})
            continue
        try:
            price = _decimal(raw.get("unit_price"), field=f"第 {index} 条单价")
            quantity = _decimal(raw.get("quantity"), field=f"第 {index} 条数量", allow_empty=True)
        except ValueError as exc:
            issues.append({"record": index, "message": str(exc)})
            continue
        if price < 0:
            issues.append({"record": index, "message": "单价不能小于 0"})
            continue
        quoted_at = _text(raw.get("quoted_at") or raw.get("date"))
        accepted.append({
            "unit_price": price,
            "quantity": quantity,
            "quoted_at": quoted_at,
            "customer_name": _text(raw.get("customer_name")),
            "product_name": _text(raw.get("product_name")),
            "source_asset_id": _text(raw.get("source_asset_id")),
            "source_locator": _text(raw.get("source_locator")),
            "record_id": _text(raw.get("record_id")),
        })
    if not accepted:
        raise ValueError("没有可用于汇总的有效历史价格")
    prices = sorted(item["unit_price"] for item in accepted)
    latest = max(accepted, key=lambda item: _date_sort_key(item["quoted_at"]))
    target = _decimal(target_quantity, field="target_quantity", allow_empty=True)
    closest = min(
        accepted,
        key=lambda item: abs(item["quantity"] - target),
    ) if target > 0 else None
    citations = [
        {
            "record_id": item["record_id"],
            "source_asset_id": item["source_asset_id"],
            "source_locator": item["source_locator"],
            "quoted_at": item["quoted_at"],
            "unit_price": _number(item["unit_price"]),
            "quantity": _number(item["quantity"]),
        }
        for item in accepted
    ]
    return json.dumps({
        "evidence_count": len(accepted),
        "minimum_unit_price": _number(prices[0]),
        "maximum_unit_price": _number(prices[-1]),
        "median_unit_price": _number(Decimal(str(median(prices)))),
        "latest_record": _public_evidence(latest),
        "closest_quantity_record": _public_evidence(closest) if closest else None,
        "citations": citations,
        "issues": issues,
        "warning": "这是历史证据摘要，不是自动批准的当前价格；时效、客户、税费和交付条件仍需判断。",
    }, ensure_ascii=False)


def _date_sort_key(value: str) -> tuple[int, str]:
    if not value:
        return (0, "")
    candidate = value[:10]
    try:
        return (1, date.fromisoformat(candidate).isoformat())
    except ValueError:
        try:
            return (1, datetime.fromisoformat(value).date().isoformat())
        except ValueError:
            return (0, value)


def _public_evidence(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_id": item["record_id"],
        "unit_price": _number(item["unit_price"]),
        "quantity": _number(item["quantity"]),
        "quoted_at": item["quoted_at"],
        "customer_name": item["customer_name"],
        "product_name": item["product_name"],
        "source_asset_id": item["source_asset_id"],
        "source_locator": item["source_locator"],
    }


def calculate_quotation(
    items: list[dict[str, Any]],
    tax_rate: float = 0,
    price_mode: str = "tax_exclusive",
    overall_discount_rate: float = 0,
    shipping_fee: float = 0,
    precision: int = 2,
) -> str:
    """Calculate a quotation with Decimal arithmetic and explicit tax semantics."""
    if not isinstance(items, list) or not items:
        raise ValueError("items 必须包含至少一条报价明细")
    if price_mode not in {"tax_exclusive", "tax_inclusive"}:
        raise ValueError("price_mode 必须是 tax_exclusive 或 tax_inclusive")
    if precision < 0 or precision > 6:
        raise ValueError("precision 必须在 0～6 之间")
    tax = _rate(tax_rate, field="tax_rate")
    overall_discount = _rate(overall_discount_rate, field="overall_discount_rate")
    shipping = _decimal(shipping_fee, field="shipping_fee", allow_empty=True)
    if shipping < 0:
        raise ValueError("shipping_fee 不能小于 0")

    calculated: list[dict[str, Any]] = []
    net_total = Decimal("0")
    tax_total = Decimal("0")
    gross_total = Decimal("0")
    for index, raw in enumerate(items, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"第 {index} 条明细不是对象")
        quantity = _decimal(raw.get("quantity"), field=f"第 {index} 行数量")
        unit_price = _decimal(raw.get("unit_price"), field=f"第 {index} 行单价")
        line_discount = _rate(raw.get("discount_rate", 0), field=f"第 {index} 行折扣率")
        if quantity <= 0 or unit_price < 0:
            raise ValueError(f"第 {index} 行数量必须大于 0，单价不能小于 0")
        original = quantity * unit_price
        discounted = original * (Decimal("1") - line_discount) * (Decimal("1") - overall_discount)
        if price_mode == "tax_exclusive":
            line_net = discounted
            line_tax = line_net * tax
            line_gross = line_net + line_tax
        else:
            line_gross = discounted
            line_net = line_gross / (Decimal("1") + tax) if tax else line_gross
            line_tax = line_gross - line_net
        line_net = _quantize(line_net, precision)
        line_tax = _quantize(line_tax, precision)
        line_gross = _quantize(line_gross, precision)
        net_total += line_net
        tax_total += line_tax
        gross_total += line_gross
        calculated.append({
            "line_no": index,
            "product_name": _text(raw.get("product_name")),
            "specification": _text(raw.get("specification")),
            "quantity": _number(quantity),
            "unit": _text(raw.get("unit")),
            "unit_price": _number(unit_price, precision),
            "line_discount_rate": _number(line_discount * 100),
            "net_amount": _number(line_net, precision),
            "tax_amount": _number(line_tax, precision),
            "gross_amount": _number(line_gross, precision),
        })
    net_total = _quantize(net_total, precision)
    tax_total = _quantize(tax_total, precision)
    gross_total = _quantize(gross_total + shipping, precision)
    return json.dumps({
        "items": calculated,
        "currency": "CNY",
        "price_mode": price_mode,
        "tax_rate": _number(tax * 100),
        "overall_discount_rate": _number(overall_discount * 100),
        "net_total": _number(net_total, precision),
        "tax_total": _number(tax_total, precision),
        "shipping_fee": _number(shipping, precision),
        "grand_total": _number(gross_total, precision),
        "rounding": "ROUND_HALF_UP",
    }, ensure_ascii=False)


LINE_SCHEMA = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "product_name": {"type": "string"},
        "product": {"type": "string"},
        "name": {"type": "string"},
        "specification": {"type": "string"},
        "model": {"type": "string"},
        "quantity": {"type": "string", "description": "数量，可包含千分位"},
        "unit": {"type": "string"},
        "unit_price": {"type": "string", "description": "单价，可包含货币符号和千分位"},
        "discount_rate": {"type": "string", "description": "0～100 的百分比或 0～1 的比例"},
        "currency": {"type": "string"},
        "source_asset_id": {"type": "string"},
        "source_locator": {"type": "string"},
    },
}

AUTOMATIC_QUOTATION_TOOLS = [
    Tool(
        name="normalize_quotation_lines",
        description=(
            "将从历史报价文件提取出的明细转换为稳定字段和数字格式，并保留 source_asset_id、"
            "source_locator 与原始值。它不负责猜测缺失价格，也不证明产品归并或价格有效性。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "lines": {"type": "array", "minItems": 1, "maxItems": 500, "items": LINE_SCHEMA},
            },
            "required": ["lines"],
        },
        func=normalize_quotation_lines,
    ),
    Tool(
        name="summarize_price_evidence",
        description=(
            "汇总已经由 query_business_records 按产品、规格和必要条件筛选出的历史单价证据。"
            "返回区间、中位数、最新记录、数量最接近记录和来源引用；不直接决定本次报价。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "records": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 500,
                    "items": {
                        "type": "object",
                        "additionalProperties": True,
                        "properties": {
                            "record_id": {"type": "string"},
                            "customer_name": {"type": "string"},
                            "product_name": {"type": "string"},
                            "quantity": {"type": "string"},
                            "unit_price": {"type": "string"},
                            "quoted_at": {"type": "string"},
                            "source_asset_id": {"type": "string"},
                            "source_locator": {"type": "string"},
                        },
                        "required": ["unit_price"],
                    },
                },
                "target_quantity": {"type": "number", "minimum": 0},
            },
            "required": ["records"],
        },
        func=summarize_price_evidence,
    ),
    Tool(
        name="calculate_quotation",
        description=(
            "使用 Decimal 精确计算报价明细、行折扣、整体折扣、税额、运费和含税总价。"
            "调用前必须明确单价是含税还是未税；不要让模型自行口算正式报价。"
        ),
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "items": {"type": "array", "minItems": 1, "maxItems": 500, "items": LINE_SCHEMA},
                "tax_rate": {"type": "number", "minimum": 0, "maximum": 100},
                "price_mode": {"type": "string", "enum": ["tax_exclusive", "tax_inclusive"]},
                "overall_discount_rate": {"type": "number", "minimum": 0, "maximum": 100},
                "shipping_fee": {"type": "number", "minimum": 0},
                "precision": {"type": "integer", "minimum": 0, "maximum": 6},
            },
            "required": ["items"],
        },
        func=calculate_quotation,
    ),
]
