from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from xiaomei_brain.capability_packages import (
    CapabilityPackageBuilder,
    CapabilityPackageInspector,
    CapabilityPackageService,
)
from xiaomei_brain.capabilities.loader import CapabilityManifestLoader
from xiaomei_brain.plugin.loader import PluginLoader
from xiaomei_brain.plugin.registry import PluginRegistry
from xiaomei_brain.processes import ProcessTemplateRegistry
from xiaomei_brain.projects.models import ProjectRuntimeContext, WorkspaceKind
from xiaomei_brain.tools.execution_context import bind_tool_execution


SOURCE = Path("capability-packages/video-production")


def _load_tool_module():
    path = SOURCE / "plugins/video_production/tool.py"
    spec = importlib.util.spec_from_file_location("video_production_package_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeProjectService:
    def __init__(self):
        self.steps = []
        self.step_statuses = {}
        self.updates = []
        self.assets = []
        self.metadata = {
            "delivery_process": {"required": True, "requested_stage_count": 5},
            "execution": {"assignment_required": True},
        }

    def require_project(self, project_id, **_kwargs):
        return SimpleNamespace(id=project_id, metadata=dict(self.metadata))

    def put_step(self, project_id, **kwargs):
        step_id = kwargs["step_id"]
        current = kwargs["status"]
        self.step_statuses[step_id] = current
        self.steps.append((project_id, kwargs))
        return SimpleNamespace(**kwargs)

    def get_step(self, _project_id, step_id, **_kwargs):
        status = self.step_statuses.get(step_id)
        return SimpleNamespace(status=status) if status is not None else None

    def update(self, project_id, **kwargs):
        self.updates.append((project_id, kwargs))
        return SimpleNamespace(id=project_id)

    def register_asset(self, project_id, **kwargs):
        asset = SimpleNamespace(id=f"asset_{len(self.assets) + 1}", **kwargs)
        self.assets.append((project_id, kwargs))
        return asset


def _project_context(tmp_path: Path) -> ProjectRuntimeContext:
    return ProjectRuntimeContext(
        project_id="project_video",
        project_type="video.production",
        scope_type="person",
        scope_id="person_1",
        workspace_kind=WorkspaceKind.MANAGED,
        state_root=str(tmp_path / "projects/project_video"),
        work_root=str(tmp_path / "projects/project_video/work"),
    )


def test_video_production_package_exports_as_valid_xmcap(tmp_path):
    result = CapabilityPackageBuilder().pack(
        SOURCE,
        output_path=tmp_path / "video-production.xmcap",
    )

    package = Path(result["path"])
    inspection = CapabilityPackageInspector().inspect(
        package.read_bytes(),
        file_name=package.name,
    )
    assert inspection["valid"] is True
    assert inspection["manifest"]["package"]["id"] == "xiaomei.video-production"
    assert inspection["manifest"]["capabilities"][0]["id"] == "video_production"


def test_installed_video_package_loads_complete_runtime(tmp_path):
    export = CapabilityPackageBuilder().pack(
        SOURCE,
        output_path=tmp_path / "video-production.xmcap",
    )
    archive = Path(export["path"])
    service = CapabilityPackageService(base_dir=tmp_path / "host", agent_id="test")
    installed = service.install(archive.read_bytes(), file_name=archive.name)
    service.activate(
        "xiaomei.video-production",
        "1.0.12",
        installed["package"]["sha256"],
    )

    directories = service.runtime_directories()
    registry = PluginRegistry()
    loaded = PluginLoader(registry, agent_id="test").boot(directories["plugins"])
    definitions = CapabilityManifestLoader(directories["capabilities"]).load()
    process_templates = ProcessTemplateRegistry(directories["processes"]).list()

    assert service.runtime_issues == {}
    assert len(loaded) == 1
    assert loaded[0].status == "loaded"
    assert {tool.name for tool in registry.get_agent_tools()} == {
        "initialize_video_project",
        "save_video_storyboard",
        "stage_video_asset",
        "inspect_video_media",
        "create_video_contact_sheet",
        "compose_video_timeline",
    }
    assert [definition.id for definition in definitions] == ["video_production"]
    assert [(item.id, len(item.definition["stages"])) for item in process_templates] == [
        ("video-full-8", 8),
        ("video-fast-3", 3),
    ]
    assert len(directories["skills"]) == 1
    installed_skill = Path(directories["skills"][0]) / "video-production" / "SKILL.md"
    assert installed_skill.is_file()
    skill_text = installed_skill.read_text(encoding="utf-8")
    assert "  - review_project" in skill_text
    for tool_name in {tool.name for tool in registry.get_agent_tools()}:
        assert f"  - {tool_name}" in skill_text


def test_video_project_initialization_and_storyboard_are_durable(tmp_path):
    module = _load_tool_module()
    service = FakeProjectService()
    project_context = _project_context(tmp_path)

    with bind_tool_execution(
        tool_call_id="call_1",
        tool_name="initialize_video_project",
        arguments={},
        artifact_callback=None,
        person_id="person_1",
        project_context=project_context,
        project_service=service,
    ):
        initialized = json.loads(module.initialize_video_project.execute(
            brief="介绍公司的核心产品",
            target_duration=30,
            aspect_ratio="16:9",
            audience="潜在客户",
        ))
        storyboard = json.loads(module.save_video_storyboard.execute(
            storyboard_json=json.dumps([
                {
                    "id": "shot-001",
                    "duration": 5,
                    "visual": "厂区航拍后推进到产品",
                    "narration": "从真实生产开始",
                },
                {
                    "id": "shot-002",
                    "duration": 7.5,
                    "visual": "产品特写与数据叠加",
                    "transition": "dissolve",
                },
            ], ensure_ascii=False),
        ))

    work_root = Path(project_context.work_root)
    assert service.steps == []
    assert "阶段地图" in initialized["next_action"]
    assert initialized["project_asset_id"] == "asset_1"
    assert (work_root / "script/brief.json").is_file()
    saved = json.loads((work_root / "storyboard/storyboard.json").read_text(encoding="utf-8"))
    assert saved["total_duration"] == 12.5
    assert storyboard["status"] == "saved"
    assert storyboard["project_asset_id"] == "asset_2"
    updated_metadata = service.updates[0][1]["metadata"]
    assert updated_metadata["delivery_process"]["requested_stage_count"] == 5
    assert updated_metadata["execution"]["assignment_required"] is True
    assert updated_metadata["video"]["target_duration"] == 30


def test_video_tools_explain_that_project_must_be_created_first():
    module = _load_tool_module()

    with pytest.raises(ValueError, match="create_project"):
        module.initialize_video_project.execute(
            brief="测试视频",
            target_duration=6,
        )


def test_stage_asset_copies_only_current_attachment_into_project(tmp_path):
    module = _load_tool_module()
    project_context = _project_context(tmp_path)
    service = FakeProjectService()
    source = tmp_path / "incoming" / "logo.png"
    source.parent.mkdir()
    source.write_bytes(b"logo")

    with bind_tool_execution(
        tool_call_id="call_2",
        tool_name="stage_video_asset",
        arguments={},
        artifact_callback=None,
        attachments=({
            "id": "asset_1",
            "name": "logo.png",
            "mime_type": "image/png",
            "local_path": str(source),
        },),
        project_context=project_context,
        project_service=service,
    ):
        result = json.loads(module.stage_video_asset.execute(
            attachment_id="asset_1",
            destination="visual/logo.png",
        ))
        with pytest.raises(ValueError, match="相对路径|边界"):
            module.stage_video_asset.execute(
                attachment_id="asset_1",
                destination="../outside.png",
            )

    assert result["media_path"] == "visual/logo.png"
    assert result["next_actions"]["inspect_video_media"] == {
        "media_path": "visual/logo.png",
    }
    assert result["project_asset_id"] == "asset_1"
    assert service.assets[0][1]["role"].value == "source"
    assert service.assets[0][1]["relative_uri"] == "work/visual/logo.png"
    assert (Path(project_context.work_root) / "visual/logo.png").read_bytes() == b"logo"
    assert not (Path(project_context.work_root).parent / "outside.png").exists()


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg runtime is not installed",
)
def test_ffmpeg_probe_contact_sheet_and_composition(tmp_path):
    module = _load_tool_module()
    project_context = _project_context(tmp_path)
    service = FakeProjectService()
    work_root = Path(project_context.work_root)
    motion = work_root / "motion"
    motion.mkdir(parents=True)
    for name, color in (("shot-001.mp4", "red"), ("shot-002.mp4", "blue")):
        subprocess.run([
            shutil.which("ffmpeg") or "ffmpeg",
            "-y", "-f", "lavfi", "-i", f"color=c={color}:s=320x240:d=0.5",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(motion / name),
        ], check=True, capture_output=True, timeout=60)

    with bind_tool_execution(
        tool_call_id="call_3",
        tool_name="compose_video_timeline",
        arguments={},
        artifact_callback=None,
        project_context=project_context,
        project_service=service,
    ):
        probe = json.loads(module.inspect_video_media.execute(
            media_path="motion/shot-001.mp4",
        ))
        contact = json.loads(module.create_video_contact_sheet.execute(
            media_path="motion/shot-001.mp4",
            frames=4,
            columns=2,
        ))
        with pytest.raises(FileNotFoundError, match="media_path.*具体文件"):
            module.inspect_video_media.execute(media_path="motion")
        composed = json.loads(module.compose_video_timeline.execute(
            clips=["motion/shot-001.mp4", "motion/shot-002.mp4"],
            clip_durations=[0.25, 0.25],
            filename="test-final.mp4",
            width=320,
            height=240,
            fps=24,
        ))

    assert probe["streams"][0]["codec_type"] == "video"
    assert Path(contact["output_path"]).is_file()
    assert contact["project_asset_id"] == "asset_1"
    assert Path(composed["output_path"]).is_file()
    assert 0.45 <= float(composed["probe"]["format"]["duration"]) <= 0.8
    assert {stream["codec_type"] for stream in composed["probe"]["streams"]} == {
        "audio",
        "video",
    }
    assert composed["preserved_clip_audio"] is True
    assert composed["status"] == "composed"
    assert composed["evidence"]["has_video"] is True
    assert service.step_statuses == {}
    assert [item[1]["role"].value for item in service.assets] == [
        "review",
        "deliverable",
    ]


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg runtime is not installed",
)
def test_composition_reports_missing_audio_without_deciding_project_state(tmp_path):
    module = _load_tool_module()
    project_context = _project_context(tmp_path)
    service = FakeProjectService()
    work_root = Path(project_context.work_root)
    motion = work_root / "motion"
    storyboard = work_root / "storyboard"
    script = work_root / "script"
    motion.mkdir(parents=True)
    storyboard.mkdir(parents=True)
    script.mkdir(parents=True)
    (script / "brief.json").write_text(
        json.dumps({"target_duration": 1}), encoding="utf-8",
    )
    (storyboard / "storyboard.json").write_text(json.dumps([{
        "id": "shot-1", "duration": 1, "visual": "scene",
        "audio": "music-box note", "narration": "",
    }]), encoding="utf-8")
    subprocess.run([
        shutil.which("ffmpeg") or "ffmpeg",
        "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=1",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(motion / "silent.mp4"),
    ], check=True, capture_output=True, timeout=60)

    with bind_tool_execution(
        tool_call_id="call_missing_audio",
        tool_name="compose_video_timeline",
        arguments={},
        artifact_callback=None,
        project_context=project_context,
        project_service=service,
    ):
        composed = json.loads(module.compose_video_timeline.execute(
            clips=["motion/silent.mp4"],
            filename="silent-final.mp4",
            width=320,
            height=240,
            fps=24,
        ))

    assert composed["evidence"]["audio_required"] is True
    assert composed["evidence"]["has_audio"] is False
    assert service.step_statuses == {}
    deliverable = service.assets[-1][1]
    assert deliverable["metadata"]["audio_required"] is True
    assert deliverable["metadata"]["has_audio"] is False
