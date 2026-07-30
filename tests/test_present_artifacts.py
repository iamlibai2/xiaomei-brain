from xiaomei_brain.tools.builtin import file_ops
from xiaomei_brain.tools.builtin.artifacts import present_artifacts_tool


def test_present_artifacts_resolves_final_files_in_agent_storage(tmp_path, monkeypatch):
    agent_root = tmp_path / "agent"
    workspace = agent_root / "workspace"
    images = agent_root / "images"
    workspace.mkdir(parents=True)
    images.mkdir()
    report = workspace / "report.docx"
    preview = images / "preview.png"
    report.write_bytes(b"report")
    preview.write_bytes(b"image")
    monkeypatch.setattr(file_ops, "_output_base", str(agent_root))

    result = present_artifacts_tool.execute(
        paths=["report.docx", str(preview), "report.docx"],
        message="最终文件",
    )

    assert result == {
        "type": "present_artifacts_result",
        "path": [str(report.resolve()), str(preview.resolve())],
        "message": "最终文件",
        "count": 2,
        "delivered": True,
    }


def test_present_artifacts_rejects_missing_or_external_files(tmp_path, monkeypatch):
    agent_root = tmp_path / "agent"
    (agent_root / "workspace").mkdir(parents=True)
    external = tmp_path / "external.txt"
    external.write_text("private", encoding="utf-8")
    monkeypatch.setattr(file_ops, "_output_base", str(agent_root))

    missing = present_artifacts_tool.execute(paths=["missing.docx"])
    outside = present_artifacts_tool.execute(paths=[str(external)])

    assert str(missing).startswith("Error:")
    assert str(outside).startswith("Error:")


def test_present_artifacts_schema_exposes_path_array():
    paths = present_artifacts_tool.parameters["properties"]["paths"]

    assert paths == {"type": "array", "items": {"type": "string"}}
    assert present_artifacts_tool.parameters["required"] == ["paths"]
