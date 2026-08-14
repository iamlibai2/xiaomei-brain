from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from xiaomei_brain.capabilities.loader import CapabilityManifestLoader
from xiaomei_brain.capability_packages import (
    CapabilityPackageBuilder,
    CapabilityPackageInspector,
    CapabilityPackageService,
)
from xiaomei_brain.plugin.loader import PluginLoader
from xiaomei_brain.plugin.registry import PluginRegistry
from xiaomei_brain.processes import ProcessTemplateRegistry


SOURCE = Path("capability-packages/automatic-quotation")


def _load_tool_module():
    path = SOURCE / "plugins/automatic_quotation/tool.py"
    spec = importlib.util.spec_from_file_location("automatic_quotation_package_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_automatic_quotation_package_exports_as_valid_xmcap(tmp_path):
    result = CapabilityPackageBuilder().pack(
        SOURCE,
        output_path=tmp_path / "automatic-quotation.xmcap",
    )

    package = Path(result["path"])
    inspection = CapabilityPackageInspector().inspect(
        package.read_bytes(),
        file_name=package.name,
    )

    assert inspection["valid"] is True
    assert inspection["manifest"]["package"]["id"] == "xiaomei.automatic-quotation"
    assert inspection["manifest"]["capabilities"][0]["id"] == "automatic_quotation"


def test_installed_automatic_quotation_package_loads_runtime(tmp_path):
    export = CapabilityPackageBuilder().pack(
        SOURCE,
        output_path=tmp_path / "automatic-quotation.xmcap",
    )
    archive = Path(export["path"])
    service = CapabilityPackageService(base_dir=tmp_path / "host", agent_id="test")
    installed = service.install(archive.read_bytes(), file_name=archive.name)
    service.activate(
        "xiaomei.automatic-quotation",
        "0.1.0",
        installed["package"]["sha256"],
    )

    directories = service.runtime_directories()
    registry = PluginRegistry()
    loaded = PluginLoader(registry, agent_id="test").boot(directories["plugins"])
    definitions = CapabilityManifestLoader(directories["capabilities"]).load()
    process_templates = ProcessTemplateRegistry(directories["processes"]).list()

    assert service.runtime_issues == {}
    assert len(loaded) == 1 and loaded[0].status == "loaded"
    assert {tool.name for tool in registry.get_agent_tools()} == {
        "normalize_quotation_lines",
        "summarize_price_evidence",
        "calculate_quotation",
    }
    assert [definition.id for definition in definitions] == ["automatic_quotation"]
    assert [(item.id, len(item.definition["stages"])) for item in process_templates] == [
        ("quotation-delivery", 3),
    ]
    skill_root = Path(directories["skills"][0])
    assert (skill_root / "automatic-quotation" / "SKILL.md").is_file()
    assert (skill_root / "historical-quotation-onboarding" / "SKILL.md").is_file()


def test_quote_calculation_uses_explicit_tax_semantics_and_decimal_rounding():
    module = _load_tool_module()

    result = json.loads(module.calculate_quotation(
        items=[
            {
                "product_name": "QY-80 离心泵",
                "quantity": 20,
                "unit": "台",
                "unit_price": 1000,
                "discount_rate": 5,
            },
            {
                "product_name": "安装服务",
                "quantity": 1,
                "unit": "项",
                "unit_price": 500,
            },
        ],
        tax_rate=13,
        price_mode="tax_exclusive",
        overall_discount_rate=10,
        shipping_fee=200,
    ))

    assert result["net_total"] == 17550
    assert result["tax_total"] == 2281.5
    assert result["grand_total"] == 20031.5
    assert result["rounding"] == "ROUND_HALF_UP"


def test_price_evidence_summary_preserves_source_citations():
    module = _load_tool_module()

    result = json.loads(module.summarize_price_evidence(
        records=[
            {
                "record_id": "record_old",
                "unit_price": 100,
                "quantity": 10,
                "quoted_at": "2025-01-01",
                "source_asset_id": "asset_old",
                "source_locator": "报价.xlsx!明细!B4:H4",
            },
            {
                "record_id": "record_new",
                "unit_price": 120,
                "quantity": 30,
                "quoted_at": "2026-07-01",
                "source_asset_id": "asset_new",
                "source_locator": "报价.pdf#page=2",
            },
        ],
        target_quantity=25,
    ))

    assert result["minimum_unit_price"] == 100
    assert result["maximum_unit_price"] == 120
    assert result["median_unit_price"] == 110
    assert result["latest_record"]["record_id"] == "record_new"
    assert result["closest_quantity_record"]["record_id"] == "record_new"
    assert {item["source_asset_id"] for item in result["citations"]} == {
        "asset_old",
        "asset_new",
    }
