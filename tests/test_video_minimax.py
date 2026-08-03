from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from xiaomei_brain.plugins.tools.video_minimax.provider import (
    H3_MODEL,
    HAILUO_MODEL,
    MiniMaxVideoProvider,
    VideoTask,
)
from xiaomei_brain.plugins.tools.video_minimax import tool as video_tool
from xiaomei_brain.projects.models import ProjectRuntimeContext, WorkspaceKind
from xiaomei_brain.tools.execution_context import bind_tool_execution


class FakeResponse:
    def __init__(self, data, *, status_code=200, content=b"video"):
        self._data = data
        self.status_code = status_code
        self.content = content

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_h3_create_uses_v2_multimodal_content(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return FakeResponse({"task_id": "h3-task"})

    monkeypatch.setattr(
        "xiaomei_brain.plugins.tools.video_minimax.provider.requests.request",
        fake_request,
    )
    provider = MiniMaxVideoProvider(api_key="secret")
    task = provider.create(
        prompt="camera moves forward",
        model=H3_MODEL,
        duration=5,
        resolution="2K",
        ratio="16:9",
        first_frame="data:image/png;base64,AA==",
    )

    assert task == VideoTask("h3-task", "v2", H3_MODEL)
    assert calls[0][1].endswith("/v2/video_generation")
    payload = calls[0][2]["json"]
    assert payload["ratio"] == "adaptive"
    assert payload["content"][1]["role"] == "first_frame"
    assert payload["content"][1]["image_url"]["url"].startswith("data:image")


def test_video_tool_does_not_expose_expensive_h3_2k_option():
    resolution = video_tool.video_generate_tool.parameters["properties"]["resolution"]
    assert resolution["enum"] == ["768P", "1080P"]
    assert "2K" not in video_tool.video_generate_tool.description


def test_hailuo_create_uses_v1_and_validates_duration(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return FakeResponse({
            "task_id": "v1-task",
            "base_resp": {"status_code": 0, "status_msg": "success"},
        })

    monkeypatch.setattr(
        "xiaomei_brain.plugins.tools.video_minimax.provider.requests.request",
        fake_request,
    )
    provider = MiniMaxVideoProvider(api_key="secret")
    task = provider.create(
        prompt="a person reads a book",
        model=HAILUO_MODEL,
        duration=10,
        resolution="768P",
        first_frame="data:image/png;base64,AA==",
    )

    assert task.api_version == "v1"
    assert calls[0][1].endswith("/v1/video_generation")
    assert calls[0][2]["json"]["first_frame_image"].startswith("data:image")
    with pytest.raises(ValueError, match="10 秒"):
        provider.create(
            prompt="bad combination",
            model=HAILUO_MODEL,
            duration=10,
            resolution="1080P",
        )


def test_h3_rejects_mixed_or_excessive_reference_inputs():
    provider = MiniMaxVideoProvider(api_key="secret")

    with pytest.raises(ValueError, match="不能与"):
        provider._h3_payload(
            prompt="mixed",
            duration=5,
            resolution="768P",
            ratio="16:9",
            first_frame="data:image/png;base64,AA==",
            last_frame="",
            references=[("data:image/png;base64,AA==", "image")],
        )
    with pytest.raises(ValueError, match="9 张"):
        provider._h3_payload(
            prompt="too many",
            duration=5,
            resolution="768P",
            ratio="16:9",
            first_frame="",
            last_frame="",
            references=[("https://example.com/a.png", "image")] * 10,
        )


def test_query_normalizes_v1_and_v2_results(monkeypatch):
    responses = iter([
        FakeResponse({
            "task": {
                "model": H3_MODEL,
                "status": "succeeded",
                "content": {"url": "https://cdn.example/video.mp4"},
            },
        }),
        FakeResponse({
            "task_id": "legacy",
            "status": "Success",
            "file_id": "file-1",
            "base_resp": {"status_code": 0},
        }),
    ])
    monkeypatch.setattr(
        "xiaomei_brain.plugins.tools.video_minimax.provider.requests.request",
        lambda *args, **kwargs: next(responses),
    )
    provider = MiniMaxVideoProvider(api_key="secret")

    h3 = provider.query("new", api_version="v2", model=H3_MODEL)
    old = provider.query("legacy", api_version="v1", model=HAILUO_MODEL)

    assert h3.status == "succeeded"
    assert h3.download_url.endswith("video.mp4")
    assert old.status == "success"
    assert old.file_id == "file-1"


def test_task_record_round_trip(tmp_path):
    task = VideoTask("task_123", "v2", H3_MODEL, status="running")

    path = MiniMaxVideoProvider.save_task(task, tmp_path)

    assert path.is_file()
    assert MiniMaxVideoProvider.load_task("task_123", tmp_path) == task
    with pytest.raises(ValueError, match="ID"):
        MiniMaxVideoProvider.load_task("../escape", tmp_path)


def test_video_tool_uses_project_motion_workspace_and_current_attachment(
    tmp_path,
    monkeypatch,
):
    state_root = tmp_path / "project"
    image_path = tmp_path / "frame.png"
    image_path.write_bytes(b"png")
    captured = {}

    class FakeProvider:
        def create(self, **kwargs):
            captured.update(kwargs)
            return VideoTask("task_123", "v2", H3_MODEL)

        def save_task(self, task, directory):
            Path(directory).mkdir(parents=True, exist_ok=True)
            path = Path(directory) / f"{task.task_id}.json"
            path.write_text(json.dumps({"task_id": task.task_id}), encoding="utf-8")
            return path

    class FakeThread:
        def __init__(self, *, target, kwargs, **_rest):
            captured["thread_target"] = target
            captured["thread_kwargs"] = kwargs

        def start(self):
            captured["started"] = True

    monkeypatch.setattr(video_tool.threading, "Thread", FakeThread)
    video_tool.set_video_provider(FakeProvider())
    project_context = ProjectRuntimeContext(
        project_id="project_1",
        project_type="video.production",
        scope_type="person",
        scope_id="person_1",
        workspace_kind=WorkspaceKind.MANAGED,
        state_root=str(state_root),
        work_root="",
    )

    with bind_tool_execution(
        tool_call_id="call_1",
        tool_name="generate_video_minimax",
        arguments={},
        artifact_callback=None,
        attachments=({
            "id": "frame_1",
            "name": "frame.png",
            "mime_type": "image/png",
            "local_path": str(image_path),
        },),
        project_context=project_context,
    ):
        result = video_tool.video_generate_tool.execute(
            prompt="make it move",
            first_frame_attachment_id="frame_1",
            duration=5,
            scene_id="shot-001",
        )

    assert "task_123" in result
    assert captured["first_frame"].startswith("data:image/png;base64,")
    assert captured["thread_kwargs"]["output_path"] == (
        state_root / "work" / "motion" / "shot-001.mp4"
    )
    assert captured["thread_kwargs"]["task"].scene_id == "shot-001"
    assert captured["started"] is True


def test_completed_project_scene_is_working_asset_not_chat_delivery(tmp_path):
    state_root = tmp_path / "project"
    delivered = []
    registered = {}

    class FakeProvider:
        def wait(self, task):
            return VideoTask(
                task.task_id,
                task.api_version,
                task.model,
                status="succeeded",
                download_url="https://example.invalid/video.mp4",
                scene_id=task.scene_id,
            )

        def save_task(self, task, directory):
            Path(directory).mkdir(parents=True, exist_ok=True)

        def download(self, task, output_path):
            target = Path(output_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"video")
            return target

    class FakeProjectService:
        def register_asset(self, project_id, **kwargs):
            registered["project_id"] = project_id
            registered.update(kwargs)
            return type("Asset", (), {"id": "project_asset_1"})()

    project_context = ProjectRuntimeContext(
        project_id="project_1",
        project_type="video.production",
        scope_type="person",
        scope_id="person_1",
        workspace_kind=WorkspaceKind.MANAGED,
        state_root=str(state_root),
        work_root=str(state_root / "work"),
        active_assignment_id="assignment_1",
    )
    with bind_tool_execution(
        tool_call_id="call_2",
        tool_name="generate_video_minimax",
        arguments={},
        artifact_callback=lambda *args: delivered.append(args),
        session_id="session_1",
        project_context=project_context,
        project_service=FakeProjectService(),
    ) as context:
        video_tool._finish_generation(
            provider=FakeProvider(),
            task=VideoTask("task_1", "v2", H3_MODEL, scene_id="shot-001"),
            output_path=state_root / "work" / "motion" / "shot-001.mp4",
            task_dir=state_root / "state" / "video_tasks",
            context=context,
        )

    assert registered["project_id"] == "project_1"
    assert registered["role"].value == "working"
    assert registered["relative_uri"] == "work/motion/shot-001.mp4"
    assert registered["source_type"] == "assignment"
    assert registered["source_id"] == "assignment_1"
    assert registered["metadata"]["scene_id"] == "shot-001"
    assert registered["metadata"]["relative_uri"] == "work/motion/shot-001.mp4"
    assert registered["metadata"]["media_path"] == "motion/shot-001.mp4"
    assert delivered == []


def test_query_returns_work_root_relative_media_path_for_video_project(tmp_path):
    state_root = tmp_path / "project"

    class FakeProvider:
        def load_task(self, task_id, _directory):
            return VideoTask(task_id, "v2", H3_MODEL, scene_id="shot-001")

        def query(self, task_id, **_kwargs):
            return VideoTask(
                task_id,
                "v2",
                H3_MODEL,
                status="succeeded",
                download_url="https://example.invalid/video.mp4",
                scene_id="shot-001",
            )

        def save_task(self, _task, directory):
            Path(directory).mkdir(parents=True, exist_ok=True)

        def download(self, _task, output_path):
            target = Path(output_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"video")
            return target

    class FakeProjectService:
        def register_asset(self, _project_id, **_kwargs):
            return type("Asset", (), {"id": "project_asset_1"})()

    project_context = ProjectRuntimeContext(
        project_id="project_1",
        project_type="video.production",
        scope_type="person",
        scope_id="person_1",
        workspace_kind=WorkspaceKind.MANAGED,
        state_root=str(state_root),
        work_root=str(state_root / "work"),
    )
    video_tool.set_video_provider(FakeProvider())
    with bind_tool_execution(
        tool_call_id="call_query",
        tool_name="query_video_minimax",
        arguments={},
        artifact_callback=None,
        session_id="session_1",
        project_context=project_context,
        project_service=FakeProjectService(),
    ):
        result = video_tool.video_query_tool.execute(
            task_id="task_1",
            filename="shot-001.mp4",
        )

    assert "media_path: motion/shot-001.mp4" in result
    assert "project_path:" not in result
