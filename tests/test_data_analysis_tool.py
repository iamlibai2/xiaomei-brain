from __future__ import annotations

from pathlib import Path

from xiaomei_brain.plugins.tools.data_analysis.tool import analyze_data
from xiaomei_brain.tools.execution_context import bind_tool_execution


def _run(tmp_path: Path, attachment: Path, **arguments):
    outputs = tmp_path / "outputs"
    outputs.mkdir(exist_ok=True)
    with bind_tool_execution(
        tool_call_id="tool-1",
        tool_name="analyze_data",
        arguments={"attachment_id": "data-1", **arguments},
        artifact_callback=None,
        attachments=({
            "id": "data-1",
            "name": attachment.name,
            "kind": "document",
            "local_path": str(attachment),
        },),
        workspace_root=str(tmp_path),
        working_directory=str(tmp_path),
        output_root=str(outputs),
    ):
        return analyze_data(attachment_id="data-1", **arguments)


def test_profiles_and_groups_csv_then_creates_svg(tmp_path):
    source = tmp_path / "sales.csv"
    source.write_text(
        "地区,销售额,备注\n华东,10,正常\n华东,20,\n华南,15,正常\n",
        encoding="utf-8",
    )

    result = _run(
        tmp_path,
        source,
        group_by="地区",
        value_columns=["销售额"],
        chart_type="bar",
        output_name="sales.svg",
    )

    assert result["success"] is True
    assert result["row_count"] == 3
    columns = {item["name"]: item for item in result["columns"]}
    assert columns["销售额"]["numeric"]["mean"] == 15
    assert columns["备注"]["missing"] == 1
    assert result["group_summary"][0]["销售额"]["sum"] == 30
    chart = Path(result["chart"]["output_path"])
    assert chart.is_file()
    assert "<svg" in chart.read_text(encoding="utf-8")


def test_rejects_attachment_outside_current_turn(tmp_path):
    with bind_tool_execution(
        tool_call_id="tool-1",
        tool_name="analyze_data",
        arguments={"attachment_id": "missing"},
        artifact_callback=None,
        workspace_root=str(tmp_path),
        working_directory=str(tmp_path),
        output_root=str(tmp_path),
    ):
        result = analyze_data("missing")

    assert "不存在" in result["error"]


def test_profiles_selected_xlsx_sheet(tmp_path):
    from openpyxl import Workbook

    source = tmp_path / "sales.xlsx"
    workbook = Workbook()
    workbook.active.title = "说明"
    sheet = workbook.create_sheet("销售")
    sheet.append(["月份", "收入"])
    sheet.append(["一月", 12])
    sheet.append(["二月", 18])
    workbook.save(source)
    workbook.close()

    result = _run(tmp_path, source, sheet="销售")

    assert result["success"] is True
    assert result["sheet"] == "销售"
    assert result["row_count"] == 2
    assert result["columns"][1]["numeric"]["mean"] == 15
