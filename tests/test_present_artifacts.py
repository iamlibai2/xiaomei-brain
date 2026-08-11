from xiaomei_brain.tools.builtin import file_ops
from xiaomei_brain.tools.builtin.artifacts import present_artifacts_tool
from xiaomei_brain.tools.execution_context import bind_tool_execution


def test_present_artifacts_resolves_final_files_in_agent_storage(tmp_path, monkeypatch):
    agent_root = tmp_path / "agent"
    workspace = agent_root / "workspace"
    images = workspace / "outputs" / "images"
    workspace.mkdir(parents=True)
    images.mkdir(parents=True)
    report = workspace / "report.docx"
    preview = images / "preview.png"
    report.write_bytes(b"report")
    preview.write_bytes(b"image")
    monkeypatch.setattr(file_ops, "_output_base", str(agent_root))

    result = present_artifacts_tool.execute(
        paths=["report.docx", "outputs/images/preview.png", "report.docx"],
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


def test_present_artifacts_rejects_oversized_visualization(tmp_path, monkeypatch):
    agent_root = tmp_path / "agent"
    workspace = agent_root / "workspace"
    workspace.mkdir(parents=True)
    visualization = workspace / "large.visualization.html"
    visualization.write_bytes(b"x" * (1024 * 1024 + 1))
    monkeypatch.setattr(file_ops, "_output_base", str(agent_root))

    result = present_artifacts_tool.execute(paths=[visualization.name])

    assert str(result).startswith("Error:")
    assert "1 MB" in str(result)


def test_present_artifacts_preserves_agent_artifact_identity(tmp_path, monkeypatch):
    agent_root = tmp_path / "agent"
    workspace = agent_root / "workspace"
    workspace.mkdir(parents=True)
    report = workspace / "report.docx"
    report.write_bytes(b"updated report")
    monkeypatch.setattr(file_ops, "_output_base", str(agent_root))
    artifact_id = "a" * 32
    attachment = {
        "id": artifact_id,
        "managed_artifact_path": str(report),
        "source_artifact": {
            "artifact_id": artifact_id,
            "session_id": "source-session",
        },
    }

    with bind_tool_execution(
        tool_call_id="call-present",
        tool_name="present_artifacts",
        arguments={},
        artifact_callback=None,
        attachments=(attachment,),
        workspace_root=str(workspace),
        output_root=str(workspace),
    ):
        result = present_artifacts_tool.execute(paths=["report.docx"])

    assert result["updated_artifacts"] == [{
        "artifact_id": artifact_id,
        "session_id": "source-session",
        "output_path": str(report.resolve()),
    }]
