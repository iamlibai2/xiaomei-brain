from pathlib import Path

from xiaomei_brain.plugins.tools.image_minimax import tool as minimax_tool
from xiaomei_brain.plugins.tools.image_seedream import tool as seedream_tool
from xiaomei_brain.tools.execution_context import bind_tool_execution


class _ImageProvider:
    def generate_to_files(self, *, output_dir, **kwargs):
        target = Path(output_dir) / "generated.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"image")
        return [str(target)]


def _run_in_workspace(tool, tmp_path, **arguments):
    workspace = tmp_path / "workspace"
    outputs = workspace / "outputs"
    workspace.mkdir()
    with bind_tool_execution(
        tool_call_id="call-image",
        tool_name=tool.name,
        arguments=arguments,
        artifact_callback=None,
        workspace_root=str(workspace),
        working_directory=str(workspace / "work"),
        output_root=str(outputs),
    ):
        return tool.execute(**arguments), workspace, outputs


def test_minimax_image_is_created_in_execution_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(minimax_tool, "_image_provider", _ImageProvider())

    result, workspace, outputs = _run_in_workspace(
        minimax_tool.image_generate_tool,
        tmp_path,
        prompt="cover",
    )

    assert (outputs / "images" / "generated.png").is_file()
    assert result["success"] is True
    assert result["output_paths"] == [str(outputs / "images" / "generated.png")]
    assert result["workspace_paths"] == ["outputs/images/generated.png"]
    assert str(workspace.parent) not in result["workspace_paths"][0]


def test_seedream_image_is_created_in_execution_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(seedream_tool, "_image_provider", _ImageProvider())

    result, _, outputs = _run_in_workspace(
        seedream_tool.image_generate_seedream_tool,
        tmp_path,
        prompt="cover",
    )

    assert (outputs / "images" / "generated.png").is_file()
    assert result["success"] is True
    assert result["output_paths"] == [str(outputs / "images" / "generated.png")]
    assert result["workspace_paths"] == ["outputs/images/generated.png"]
