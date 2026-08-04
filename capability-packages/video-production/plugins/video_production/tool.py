"""Project-scoped video planning and FFmpeg execution tools."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Literal

from xiaomei_brain.tools.base import tool
from xiaomei_brain.tools.execution_context import (
    ToolExecutionContext,
    current_tool_execution,
)


WORK_DIRECTORIES = (
    "script", "storyboard", "visual", "motion", "audio", "subtitles", "tmp",
)


def _context() -> tuple[ToolExecutionContext, Any, Path, Path]:
    context = current_tool_execution()
    if context is None or context.project_context is None:
        raise ValueError(
            "当前尚未绑定视频项目。请先调用 create_project 创建 "
            "video.production 项目并确认成功，再调用本工具。"
        )
    project = context.project_context
    if project.project_type != "video.production":
        raise ValueError("当前项目不是 video.production 类型")
    state_root = Path(project.state_root).expanduser().resolve()
    work_root = (
        Path(project.work_root).expanduser().resolve()
        if project.work_root else (state_root / "work").resolve()
    )
    state_root.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)
    return context, project, state_root, work_root


def _within(root: Path, relative: str, *, must_exist: bool = False) -> Path:
    candidate_relative = Path(str(relative or ""))
    if candidate_relative.is_absolute() or ".." in candidate_relative.parts:
        raise ValueError("项目路径必须是安全的相对路径")
    target = (root / candidate_relative).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("项目路径越过工作区边界") from exc
    if must_exist and not target.is_file():
        raise FileNotFoundError(
            f"项目媒体文件不存在: {relative}。请原样使用 stage_video_asset 返回的 "
            "media_path；该参数必须指向具体文件，不能传目录、`.` 或绝对路径。"
        )
    return target


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _run(args: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"未找到 {Path(args[0]).name}，请先配置本机媒体运行环境") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{Path(args[0]).name} 执行超时") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()[-2000:]
        raise RuntimeError(f"{Path(args[0]).name} 执行失败: {detail}") from exc


def _executable(name: str) -> str:
    resolved = shutil.which(name)
    if not resolved:
        raise RuntimeError(f"未找到 {name}，视频项目可以继续策划，但暂时不能执行媒体处理")
    return resolved


def _project_actor(context: ToolExecutionContext):
    from xiaomei_brain.projects import ProjectActor, ProjectActorType

    return ProjectActor(ProjectActorType.AGENT, context.person_id or "agent")


def _planned_video_facts(work_root: Path) -> dict[str, Any]:
    """Read factual duration and audio requirements from durable planning files."""
    target_duration = 0.0
    brief_path = work_root / "script" / "brief.json"
    storyboard_path = work_root / "storyboard" / "storyboard.json"
    try:
        brief = json.loads(brief_path.read_text(encoding="utf-8"))
        target_duration = float(brief.get("target_duration") or 0)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    scenes: list[dict[str, Any]] = []
    try:
        raw = json.loads(storyboard_path.read_text(encoding="utf-8"))
        raw_scenes = raw.get("scenes") if isinstance(raw, dict) else raw
        if isinstance(raw_scenes, list):
            scenes = [item for item in raw_scenes if isinstance(item, dict)]
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    storyboard_duration = sum(float(item.get("duration") or 0) for item in scenes)
    audio_required = any(
        str(item.get("audio") or "").strip()
        or str(item.get("narration") or "").strip()
        for item in scenes
    )
    return {
        "target_duration": target_duration,
        "storyboard_duration": storyboard_duration,
        "audio_required": audio_required,
    }


@tool(
    name="initialize_video_project",
    description=(
        "初始化当前 video.production 项目的工作目录并保存结构化需求简报，不会预设项目阶段。"
        "不要把它作为创建项目的第一步：必须先调用 create_project，确认创建成功并绑定当前会话后，才能调用本工具。"
    ),
)
def initialize_video_project(
    brief: str,
    target_duration: int,
    aspect_ratio: Literal["16:9", "9:16", "1:1", "4:3", "3:4"] = "16:9",
    audience: str = "",
    style: str = "",
    language: str = "zh-CN",
) -> str:
    context, project, state_root, work_root = _context()
    if not brief.strip():
        return "视频需求简报不能为空。"
    if not 3 <= int(target_duration) <= 3600:
        return "目标时长必须在 3～3600 秒之间。"
    for directory in WORK_DIRECTORIES:
        (work_root / directory).mkdir(parents=True, exist_ok=True)
    (state_root / "review").mkdir(exist_ok=True)
    (state_root / "deliverables").mkdir(exist_ok=True)

    specification = {
        "schema_version": 1,
        "project_id": project.project_id,
        "brief": brief.strip(),
        "target_duration": int(target_duration),
        "aspect_ratio": aspect_ratio,
        "audience": audience.strip(),
        "style": style.strip(),
        "language": language.strip() or "zh-CN",
    }
    brief_path = work_root / "script" / "brief.json"
    _write_json(brief_path, specification)

    service = context.project_service
    brief_asset_id = ""
    if service is not None:
        from xiaomei_brain.projects import ProjectAssetRole

        actor = _project_actor(context)
        asset = service.register_asset(
            project.project_id,
            actor=actor,
            relative_uri=brief_path.relative_to(state_root).as_posix(),
            role=ProjectAssetRole.WORKING,
            kind="brief",
            name=brief_path.name,
            source_type="video.production",
            producer="initialize_video_project",
            metadata={
                "target_duration": int(target_duration),
                "aspect_ratio": aspect_ratio,
            },
        )
        brief_asset_id = asset.id
        current = service.require_project(project.project_id, actor=actor)
        project_metadata = dict(current.metadata)
        project_metadata["video"] = {
            "target_duration": int(target_duration),
            "aspect_ratio": aspect_ratio,
            "language": language.strip() or "zh-CN",
        }
        service.update(
            project.project_id,
            actor=actor,
            progress_summary="视频项目工作区和需求简报已初始化",
            metadata=project_metadata,
        )
    return json.dumps({
        "project_id": project.project_id,
        "brief_path": brief_path.relative_to(work_root).as_posix(),
        "project_asset_id": brief_asset_id,
        "next_action": "根据当前需求和视频制作 Skill 建立适合本项目的阶段地图",
    }, ensure_ascii=False)


@tool(
    name="save_video_storyboard",
    description=(
        "校验并保存当前视频项目的结构化分镜。storyboard_json 必须是 JSON 数组，"
        "每个镜头至少包含 id、duration、visual，可选 narration、transition、audio。"
    ),
)
def save_video_storyboard(storyboard_json: str) -> str:
    context, project, _state_root, work_root = _context()
    try:
        scenes = json.loads(storyboard_json)
    except json.JSONDecodeError as exc:
        return f"分镜 JSON 无效: {exc}"
    if not isinstance(scenes, list) or not scenes:
        return "分镜必须是非空 JSON 数组。"
    normalized = []
    seen: set[str] = set()
    for index, raw in enumerate(scenes, start=1):
        if not isinstance(raw, dict):
            return f"第 {index} 个镜头不是对象。"
        scene_id = str(raw.get("id") or f"shot-{index:03d}").strip()
        visual = str(raw.get("visual") or "").strip()
        try:
            duration = float(raw.get("duration"))
        except (TypeError, ValueError):
            return f"镜头 {scene_id} 的 duration 无效。"
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", scene_id) or scene_id in seen:
            return f"镜头 ID 无效或重复: {scene_id}"
        if not visual or not 0.2 <= duration <= 300:
            return f"镜头 {scene_id} 缺少画面描述或时长超出范围。"
        seen.add(scene_id)
        normalized.append({
            "id": scene_id,
            "duration": duration,
            "visual": visual,
            "narration": str(raw.get("narration") or "").strip(),
            "transition": str(raw.get("transition") or "cut").strip(),
            "audio": str(raw.get("audio") or "").strip(),
            "status": str(raw.get("status") or "planned").strip(),
        })

    total_duration = round(sum(item["duration"] for item in normalized), 3)
    payload = {
        "schema_version": 1,
        "project_id": project.project_id,
        "total_duration": total_duration,
        "scenes": normalized,
    }
    path = work_root / "storyboard" / "storyboard.json"
    _write_json(path, payload)
    markdown = ["# 视频分镜", "", f"总时长：{total_duration:g} 秒", ""]
    for item in normalized:
        markdown.extend([
            f"## {item['id']} · {item['duration']:g} 秒",
            f"- 画面：{item['visual']}",
            f"- 口播：{item['narration'] or '无'}",
            f"- 转场：{item['transition']}",
            "",
        ])
    (work_root / "storyboard" / "storyboard.md").write_text(
        "\n".join(markdown), encoding="utf-8",
    )

    storyboard_asset_id = ""
    if context.project_service is not None:
        from xiaomei_brain.projects import ProjectAssetRole

        asset = context.project_service.register_asset(
            project.project_id,
            actor=_project_actor(context),
            relative_uri=path.relative_to(_state_root).as_posix(),
            role=ProjectAssetRole.WORKING,
            kind="storyboard",
            name=path.name,
            source_type="video.production",
            producer="save_video_storyboard",
            metadata={
                "scene_count": len(normalized),
                "total_duration": total_duration,
            },
        )
        storyboard_asset_id = asset.id
    return json.dumps({
        "project_id": project.project_id,
        "storyboard_path": path.relative_to(work_root).as_posix(),
        "project_asset_id": storyboard_asset_id,
        "scene_count": len(normalized),
        "total_duration": total_duration,
        "status": "saved",
    }, ensure_ascii=False)


@tool(
    name="stage_video_asset",
    description=(
        "把当前消息中的媒体附件复制进当前视频项目工作区。必须使用 attachment_id，"
        "不能传本机绝对路径。后续工具必须原样使用返回的 media_path；"
        "不要传目录、`.`、本机绝对路径，也不要再用 Shell 或 Glob 搜索文件。"
    ),
)
def stage_video_asset(attachment_id: str, destination: str = "") -> str:
    context, project, state_root, work_root = _context()
    attachment = next(
        (item for item in context.attachments if str(item.get("id")) == attachment_id),
        None,
    )
    if attachment is None:
        return f"当前消息中没有附件 {attachment_id}。"
    source = Path(str(attachment.get("local_path") or "")).resolve()
    if not source.is_file():
        return f"附件不可读取: {attachment_id}"
    relative = destination.strip() or f"source/{source.name}"
    target = _within(work_root, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    project_asset_id = ""
    if context.project_service is not None:
        from xiaomei_brain.projects import ProjectAssetRole

        asset = context.project_service.register_asset(
            project.project_id,
            actor=_project_actor(context),
            relative_uri=target.relative_to(state_root).as_posix(),
            role=ProjectAssetRole.SOURCE,
            kind=str(attachment.get("kind") or "file"),
            name=target.name,
            source_type="attachment",
            source_id=attachment_id,
            producer="stage_video_asset",
            metadata={
                "mime_type": str(attachment.get("mime_type") or ""),
                "original_name": str(attachment.get("name") or source.name),
            },
        )
        project_asset_id = asset.id
    return json.dumps({
        "attachment_id": attachment_id,
        "media_path": target.relative_to(work_root).as_posix(),
        "project_asset_id": project_asset_id,
        "name": target.name,
        "size": target.stat().st_size,
        "next_actions": {
            "inspect_video_media": {
                "media_path": target.relative_to(work_root).as_posix(),
            },
            "create_video_contact_sheet": {
                "media_path": target.relative_to(work_root).as_posix(),
            },
        },
    }, ensure_ascii=False)


@tool(
    name="inspect_video_media",
    description=(
        "使用 FFprobe 检查当前视频项目中的一个媒体文件，返回格式、时长、分辨率、帧率和音视频流。"
        "media_path 必须是 stage_video_asset 返回的 media_path 原值，例如 clips/shot-001.mp4；"
        "它必须指向文件，不能传目录、`.` 或本机绝对路径。"
    ),
)
def inspect_video_media(media_path: str) -> str:
    _context_value, _project, _state_root, work_root = _context()
    source = _within(work_root, media_path, must_exist=True)
    result = _run([
        _executable("ffprobe"),
        "-v", "error",
        "-show_entries",
        "format=filename,format_name,duration,size,bit_rate:stream=index,codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
        "-of", "json",
        str(source),
    ], timeout=60)
    payload = json.loads(result.stdout or "{}")
    payload["media_path"] = source.relative_to(work_root).as_posix()
    return json.dumps(payload, ensure_ascii=False)


@tool(
    name="create_video_contact_sheet",
    description=(
        "从当前视频项目的一个视频文件中等间隔抽帧，生成用于快速审阅的联系表 JPG。"
        "media_path 必须原样使用 stage_video_asset 返回的 media_path，不能传目录、`.` 或绝对路径。"
    ),
)
def create_video_contact_sheet(
    media_path: str,
    filename: str = "contact-sheet.jpg",
    frames: int = 12,
    columns: int = 4,
) -> str:
    context, project, state_root, work_root = _context()
    source = _within(work_root, media_path, must_exist=True)
    frames = min(max(int(frames), 4), 40)
    columns = min(max(int(columns), 2), 8)
    rows = (frames + columns - 1) // columns
    safe_name = Path(filename).name
    if Path(safe_name).suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        safe_name = f"{Path(safe_name).stem}.jpg"
    target = _within(state_root / "review", safe_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    probe = json.loads(inspect_video_media.execute(media_path=media_path))
    duration = float((probe.get("format") or {}).get("duration") or 0)
    if duration <= 0:
        return "无法确定视频时长，不能生成联系表。"
    fps = max(frames / duration, 0.001)
    _run([
        _executable("ffmpeg"), "-y", "-i", str(source),
        "-vf", f"fps={fps:.8f},scale=320:-1:flags=lanczos,tile={columns}x{rows}",
        "-frames:v", "1", "-update", "1", str(target),
    ], timeout=300)
    project_asset_id = ""
    if context.project_service is not None:
        from xiaomei_brain.projects import ProjectAssetRole

        asset = context.project_service.register_asset(
            project.project_id,
            actor=_project_actor(context),
            relative_uri=target.relative_to(state_root).as_posix(),
            role=ProjectAssetRole.REVIEW,
            kind="image",
            name=target.name,
            source_type="project_asset",
            source_id=source.relative_to(state_root).as_posix(),
            producer="create_video_contact_sheet",
            metadata={"frames": frames, "columns": columns},
        )
        project_asset_id = asset.id
    return json.dumps({
        "output_path": str(target),
        "project_asset_id": project_asset_id,
        "review_path": target.relative_to(state_root).as_posix(),
        "source_media_path": source.relative_to(work_root).as_posix(),
        "frames": frames,
    }, ensure_ascii=False)


def _subtitle_filter(path: Path) -> str:
    text = path.resolve().as_posix().replace(":", r"\:").replace("'", r"\'")
    return f"subtitles=filename='{text}'"


@tool(
    name="compose_video_timeline",
    description=(
        "使用 FFmpeg 按顺序合成当前视频项目中的镜头，可加入项目内的口播、音乐和 SRT 字幕。"
        "clips 中的每一项都必须原样使用 stage_video_asset 返回的 media_path；"
        "narration_path、music_path、subtitle_path 也必须是具体文件的项目工作区相对路径。"
        "模型生成时长长于分镜时，使用与 clips 一一对应的 clip_durations 精确裁剪每个镜头。"
        "不能传目录、`.`、本机绝对路径，也不要使用 Shell 或 Glob 搜索已登记素材。"
    ),
)
def compose_video_timeline(
    clips: list[str],
    clip_durations: list[float] | None = None,
    filename: str = "final-video.mp4",
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    narration_path: str = "",
    music_path: str = "",
    subtitle_path: str = "",
    music_volume: float = 0.18,
    clip_audio_volume: float = 1.0,
    preserve_clip_audio: bool = True,
) -> str:
    context, project, state_root, work_root = _context()
    if not clips:
        return "至少需要一个视频片段。"
    if len(clips) > 100:
        return "第一版一次最多合成 100 个视频片段。"
    width = min(max(int(width), 320), 4096)
    height = min(max(int(height), 320), 4096)
    fps = min(max(int(fps), 12), 60)
    sources = [_within(work_root, value, must_exist=True) for value in clips]
    durations = list(clip_durations or [])
    if durations and len(durations) != len(sources):
        return "clip_durations 必须为空，或与 clips 数量完全一致。"
    if durations:
        try:
            durations = [float(value) for value in durations]
        except (TypeError, ValueError):
            return "clip_durations 中的时长必须是数字。"
        if any(value < 0.2 or value > 3600 for value in durations):
            return "clip_durations 中的时长必须在 0.2～3600 秒之间。"
    narration = _within(work_root, narration_path, must_exist=True) if narration_path else None
    music = _within(work_root, music_path, must_exist=True) if music_path else None
    subtitle = _within(work_root, subtitle_path, must_exist=True) if subtitle_path else None
    safe_name = Path(filename).name
    if Path(safe_name).suffix.lower() != ".mp4":
        safe_name = f"{Path(safe_name).stem}.mp4"
    target = _within(state_root / "deliverables", safe_name)
    target.parent.mkdir(parents=True, exist_ok=True)

    args = [_executable("ffmpeg"), "-y"]
    for source in sources:
        args.extend(["-i", str(source)])
    narration_index = len(sources) if narration else -1
    if narration:
        args.extend(["-i", str(narration)])
    music_index = len(sources) + (1 if narration else 0) if music else -1
    if music:
        args.extend(["-stream_loop", "-1", "-i", str(music)])

    filters = []
    video_labels = []
    for index in range(len(sources)):
        label = f"v{index}"
        trim = f"trim=duration={durations[index]:.6f}," if durations else ""
        filters.append(
            f"[{index}:v]{trim}setpts=PTS-STARTPTS,"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p[{label}]"
        )
        video_labels.append(f"[{label}]")
    filters.append(
        "".join(video_labels)
        + f"concat=n={len(video_labels)}:v=1:a=0[vcat]"
    )
    final_video_label = "vcat"
    if subtitle:
        filters.append(f"[vcat]{_subtitle_filter(subtitle)}[vout]")
        final_video_label = "vout"

    def has_audio(path: Path) -> bool:
        probe = _run([
            _executable("ffprobe"), "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=index", "-of", "json", str(path),
        ], timeout=60)
        return bool(json.loads(probe.stdout or "{}").get("streams"))

    audio_inputs: list[str] = []
    clip_audio_preserved = False
    if preserve_clip_audio and all(has_audio(source) for source in sources):
        clip_audio_preserved = True
        clip_audio_labels = []
        source_volume = min(max(float(clip_audio_volume), 0.0), 2.0)
        for index in range(len(sources)):
            label = f"ca{index}"
            trim = f"atrim=duration={durations[index]:.6f}," if durations else ""
            filters.append(
                f"[{index}:a]{trim}asetpts=PTS-STARTPTS,aresample=48000,"
                f"volume={source_volume:.3f}[{label}]"
            )
            clip_audio_labels.append(f"[{label}]")
        filters.append(
            "".join(clip_audio_labels)
            + f"concat=n={len(clip_audio_labels)}:v=0:a=1[clipaudio]"
        )
        audio_inputs.append("clipaudio")
    if narration:
        filters.append(f"[{narration_index}:a]aresample=48000[narr]")
        audio_inputs.append("narr")
    if music:
        volume = min(max(float(music_volume), 0.0), 1.0)
        filters.append(
            f"[{music_index}:a]aresample=48000,volume={volume:.3f}[music]"
        )
        audio_inputs.append("music")

    audio_label = ""
    if len(audio_inputs) == 1:
        audio_label = audio_inputs[0]
    elif len(audio_inputs) > 1:
        filters.append(
            "".join(f"[{label}]" for label in audio_inputs)
            + f"amix=inputs={len(audio_inputs)}:duration=longest:normalize=0[aout]"
        )
        audio_label = "aout"

    args.extend(["-filter_complex", ";".join(filters), "-map", f"[{final_video_label}]"])
    if audio_label:
        args.extend(["-map", f"[{audio_label}]", "-c:a", "aac", "-b:a", "192k", "-shortest"])
    args.extend([
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-movflags", "+faststart", str(target),
    ])

    _run(args, timeout=1800)
    probe = json.loads(_run([
        _executable("ffprobe"), "-v", "error",
        "-show_entries", "format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate",
        "-of", "json", str(target),
    ], timeout=60).stdout or "{}")
    planned = _planned_video_facts(work_root)
    actual_duration = float((probe.get("format") or {}).get("duration") or 0)
    actual_has_audio = any(
        stream.get("codec_type") == "audio"
        for stream in (probe.get("streams") or [])
        if isinstance(stream, dict)
    )
    actual_has_video = any(
        stream.get("codec_type") == "video"
        for stream in (probe.get("streams") or [])
        if isinstance(stream, dict)
    )
    target_duration = float(
        planned.get("storyboard_duration")
        or planned.get("target_duration")
        or 0
    )
    evidence = {
        **planned,
        "actual_duration": actual_duration,
        "duration_delta": actual_duration - target_duration if target_duration else 0.0,
        "has_video": actual_has_video,
        "has_audio": actual_has_audio,
    }

    project_asset_id = ""
    if context.project_service is not None:
        from xiaomei_brain.projects import ProjectAssetRole

        actor = _project_actor(context)
        asset = context.project_service.register_asset(
            project.project_id,
            actor=actor,
            relative_uri=target.relative_to(state_root).as_posix(),
            role=ProjectAssetRole.DELIVERABLE,
            kind="video",
            name=target.name,
            source_type="video.production",
            producer="compose_video_timeline",
            metadata={"clips": list(clips), **evidence},
        )
        project_asset_id = asset.id
    return json.dumps({
        "output_path": str(target),
        "project_asset_id": project_asset_id,
        "probe": probe,
        "clip_durations": durations,
        "preserved_clip_audio": clip_audio_preserved,
        "evidence": evidence,
        "status": "composed",
    }, ensure_ascii=False)


VIDEO_PRODUCTION_TOOLS = (
    initialize_video_project,
    save_video_storyboard,
    stage_video_asset,
    inspect_video_media,
    create_video_contact_sheet,
    compose_video_timeline,
)
