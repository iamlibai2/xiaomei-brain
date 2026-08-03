"""Agent tools for long-running MiniMax video generation."""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
import re
import threading
from pathlib import Path
from typing import Literal

from xiaomei_brain.tools.base import tool
from xiaomei_brain.tools.execution_context import (
    ToolExecutionContext,
    current_tool_execution,
)

from .provider import H3_MODEL, HAILUO_MODEL, MiniMaxVideoProvider, VideoTask


logger = logging.getLogger(__name__)
_video_provider: MiniMaxVideoProvider | None = None
_output_base: str | None = None


def set_video_provider(provider: MiniMaxVideoProvider) -> None:
    global _video_provider
    _video_provider = provider


def set_output_base(base_dir: str) -> None:
    global _output_base
    _output_base = base_dir


def _is_video_project(context: ToolExecutionContext | None) -> bool:
    return bool(
        context is not None
        and context.project_context is not None
        and context.project_context.project_type == "video.production"
    )


def _roots(context: ToolExecutionContext | None) -> tuple[Path, Path]:
    if context is not None and context.project_context is not None:
        project = context.project_context
        state_root = Path(project.state_root).resolve()
        if project.project_type == "video.production":
            work_root = (
                Path(project.work_root).resolve()
                if project.work_root else state_root / "work"
            )
            return work_root / "motion", state_root / "state" / "video_tasks"
        return state_root / "deliverables", state_root / "state" / "video_tasks"
    if context is not None and context.output_root:
        output = Path(context.output_root).resolve() / "videos"
        return output, output / "tasks"
    if _output_base:
        output = Path(_output_base).resolve() / "videos"
        return output, output / "tasks"
    output = Path.home() / ".xiaomei-brain" / "global" / "videos"
    return output, output / "tasks"


def _safe_filename(filename: str, task_id: str) -> str:
    name = Path(filename).name.strip() if filename else ""
    if not name:
        name = f"video_{task_id}.mp4"
    if Path(name).suffix.lower() != ".mp4":
        name = f"{Path(name).stem}.mp4"
    stem = re.sub(r"[^\w\-.\u4e00-\u9fff]+", "_", Path(name).stem).strip("._")
    return f"{stem or f'video_{task_id}'}.mp4"


def _attachment_data_url(
    context: ToolExecutionContext | None,
    attachment_id: str,
) -> tuple[str, str]:
    if context is None:
        raise ValueError("当前没有可读取的会话附件")
    attachment = next(
        (item for item in context.attachments if str(item.get("id")) == attachment_id),
        None,
    )
    if attachment is None:
        raise ValueError(f"当前消息中没有附件 {attachment_id}")
    path = Path(str(attachment.get("local_path") or "")).resolve()
    if not path.is_file():
        raise ValueError(f"附件不可读取: {attachment_id}")
    mime = str(attachment.get("mime_type") or mimetypes.guess_type(path.name)[0] or "")
    if mime.startswith("image/"):
        # H3 permits 30 MB images, while the Hailuo V1 first-frame endpoint
        # permits less than 20 MB.  Use the shared conservative boundary so a
        # current-message attachment behaves consistently across both models.
        media_type, limit = "image", 20 * 1024 * 1024
    elif mime.startswith("video/"):
        media_type, limit = "video", 50 * 1024 * 1024
    elif mime in {"audio/wav", "audio/x-wav", "audio/mpeg"}:
        media_type, limit = "audio", 15 * 1024 * 1024
    else:
        raise ValueError(f"附件格式不能用于视频参考: {path.name}")
    if path.stat().st_size > limit:
        raise ValueError(f"附件超过 MiniMax {media_type} 输入大小限制: {path.name}")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}", media_type


def _register_project_asset(
    context: ToolExecutionContext,
    target: Path,
    task: VideoTask,
) -> str:
    project = context.project_context
    service = context.project_service
    if project is None or service is None:
        return ""
    try:
        from xiaomei_brain.projects import (
            ProjectActor,
            ProjectActorType,
            ProjectAssetRole,
        )

        is_working_clip = project.project_type == "video.production"
        state_root = Path(project.state_root).resolve()
        relative_uri = target.relative_to(state_root).as_posix()
        work_root = (
            Path(project.work_root).resolve()
            if project.work_root else (state_root / "work").resolve()
        )
        media_path = (
            target.relative_to(work_root).as_posix()
            if is_working_clip else ""
        )
        asset = service.register_asset(
            project.project_id,
            actor=ProjectActor(ProjectActorType.AGENT, "agent"),
            relative_uri=relative_uri,
            role=(
                ProjectAssetRole.WORKING
                if is_working_clip else ProjectAssetRole.DELIVERABLE
            ),
            kind="video",
            name=target.name,
            source_type=("assignment" if project.active_assignment_id else "conversation"),
            source_id=project.active_assignment_id or context.session_id,
            producer="generate_video_minimax",
            provider="minimax",
            model=task.model,
            metadata={
                "task_id": task.task_id,
                "scene_id": task.scene_id,
                "relative_uri": relative_uri,
                "media_path": media_path,
            },
        )
        return asset.id
    except Exception:
        logger.exception("Failed to register generated video as a Project asset")
        return ""


def _finish_generation(
    *,
    provider: MiniMaxVideoProvider,
    task: VideoTask,
    output_path: Path,
    task_dir: Path,
    context: ToolExecutionContext | None,
) -> None:
    try:
        completed = provider.wait(task)
        provider.save_task(completed, task_dir)
        target = provider.download(completed, output_path)
        project_asset_id = (
            _register_project_asset(context, target, completed)
            if context is not None else ""
        )
        size_mb = target.stat().st_size / (1024 * 1024)
        message = (
            f"视频生成完成: {target.name} ({size_mb:.1f} MB)\n"
            f"- output_path: {target}\n"
            f"- task_id: {completed.task_id}\n"
            f"- model: {completed.model}"
        )
        if project_asset_id:
            message += f"\n- project_asset_id: {project_asset_id}"
        if context is not None and _is_video_project(context):
            project = context.project_context
            assert project is not None
            work_root = (
                Path(project.work_root).resolve()
                if project.work_root else Path(project.state_root).resolve() / "work"
            )
            message += (
                "\n- media_path: "
                + target.relative_to(work_root).as_posix()
                + "\n- asset_role: working"
            )
        elif context is not None:
            context.publish_artifacts(message)
    except Exception as exc:
        failed = VideoTask(
            task_id=task.task_id,
            api_version=task.api_version,
            model=task.model,
            status="failed",
            error=str(exc),
            scene_id=task.scene_id,
        )
        provider.save_task(failed, task_dir)
        logger.exception("MiniMax video generation failed: %s", task.task_id)


@tool(
    name="generate_video_minimax",
    description=(
        "使用 MiniMax 生成一个视频片段。调用后任务在后台运行，不阻塞继续对话；完成后自动交付 MP4。"
        "MiniMax-H3 支持文生视频、首尾帧和多模态参考，时长必须为 4～15 秒；为控制成本，"
        "本工具固定只使用 768P。MiniMax-Hailuo-2.3 支持文生视频及首帧图生视频，时长只能是 6 或 10 秒，"
        "分辨率只能是 768P 或 1080P。目标镜头短于模型最小时长时，先生成允许的最短时长，"
        "再由 compose_video_timeline 的 clip_durations 精确裁剪。"
        "引用当前消息附件时必须传 attachment_id，不能传本机文件路径。完整视频制作应在项目委托中分镜生成多个片段。"
    ),
)
def video_generate(
    prompt: str,
    filename: str = "generated_video.mp4",
    model: Literal["MiniMax-H3", "MiniMax-Hailuo-2.3"] = "MiniMax-H3",
    duration: int = 6,
    resolution: Literal["768P", "1080P"] = "768P",
    ratio: Literal["21:9", "16:9", "4:3", "1:1", "3:4", "9:16", "adaptive"] = "16:9",
    first_frame_attachment_id: str = "",
    last_frame_attachment_id: str = "",
    reference_attachment_ids: list[str] | None = None,
    prompt_optimizer: bool = True,
    scene_id: str = "",
) -> str:
    global _video_provider
    provider = _video_provider
    if provider is None:
        return "MiniMax 视频生成未启用或未配置，请在 Agent 设置的媒体服务中完成配置。"
    if not prompt.strip():
        return "视频描述不能为空。"
    if scene_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", scene_id):
        return "scene_id 只能包含字母、数字、下划线和连字符，最长 64 个字符。"

    context = current_tool_execution()
    try:
        first_frame = ""
        last_frame = ""
        references: list[tuple[str, str]] = []
        if first_frame_attachment_id:
            first_frame, media_type = _attachment_data_url(context, first_frame_attachment_id)
            if media_type != "image":
                raise ValueError("首帧附件必须是图片")
        if last_frame_attachment_id:
            last_frame, media_type = _attachment_data_url(context, last_frame_attachment_id)
            if media_type != "image":
                raise ValueError("尾帧附件必须是图片")
        for attachment_id in reference_attachment_ids or []:
            references.append(_attachment_data_url(context, attachment_id))
        if model == HAILUO_MODEL and (last_frame or references):
            raise ValueError("Hailuo 2.3 当前工具仅支持文本或首帧图片，请改用 MiniMax-H3")

        task = provider.create(
            prompt=prompt,
            model=model,
            duration=duration,
            resolution=resolution,
            ratio=ratio,
            first_frame=first_frame,
            last_frame=last_frame,
            references=references,
            prompt_optimizer=prompt_optimizer,
        )
        if scene_id:
            task = VideoTask(
                task_id=task.task_id,
                api_version=task.api_version,
                model=task.model,
                status=task.status,
                file_id=task.file_id,
                download_url=task.download_url,
                error=task.error,
                scene_id=scene_id,
            )
        output_dir, task_dir = _roots(context)
        output_dir.mkdir(parents=True, exist_ok=True)
        provider.save_task(task, task_dir)
        output_name = f"{scene_id}.mp4" if scene_id else filename
        output_path = output_dir / _safe_filename(output_name, task.task_id)
        thread = threading.Thread(
            target=_finish_generation,
            kwargs={
                "provider": provider,
                "task": task,
                "output_path": output_path,
                "task_dir": task_dir,
                "context": context,
            },
            name=f"video-minimax-{task.task_id[-12:]}",
            daemon=True,
        )
        thread.start()
        return (
            f"视频生成任务已提交，task_id: {task.task_id}。"
            f"模型: {task.model}。任务将在后台执行，完成后自动交付 {output_path.name}。"
        )
    except Exception as exc:
        logger.error("Failed to create MiniMax video task: %s", exc)
        return f"视频生成任务创建失败: {exc}"


@tool(
    name="query_video_minimax",
    description=(
        "查询或恢复当前 Agent 已提交的 MiniMax 视频任务；任务成功时下载并登记 MP4。"
        "视频项目中返回的 media_path 可直接传给 inspect_video_media、"
        "create_video_contact_sheet 和 compose_video_timeline，不要再次调用 stage_video_asset。"
    ),
)
def video_query(task_id: str, filename: str = "") -> str:
    global _video_provider
    provider = _video_provider
    if provider is None:
        return "MiniMax 视频生成未启用或未配置。"
    context = current_tool_execution()
    output_dir, task_dir = _roots(context)
    try:
        saved = provider.load_task(task_id, task_dir)
        current = provider.query(
            task_id,
            api_version=saved.api_version,
            model=saved.model,
            scene_id=saved.scene_id,
        )
        provider.save_task(current, task_dir)
        if current.status not in {"success", "succeeded"}:
            return f"视频任务 {task_id} 当前状态: {current.status}。"
        output_dir.mkdir(parents=True, exist_ok=True)
        target = provider.download(
            current,
            output_dir / _safe_filename(filename, task_id),
        )
        project_asset_id = (
            _register_project_asset(context, target, current)
            if context is not None else ""
        )
        message = (
            f"视频任务已完成: {target.name}\n"
            f"- task_id: {task_id}"
        )
        if _is_video_project(context):
            project = context.project_context
            assert project is not None
            work_root = (
                Path(project.work_root).resolve()
                if project.work_root else Path(project.state_root).resolve() / "work"
            )
            message += (
                "\n- media_path: "
                + target.relative_to(work_root).as_posix()
                + "\n- asset_role: working"
            )
        else:
            message += f"\n- output_path: {target}"
        if project_asset_id:
            message += f"\n- project_asset_id: {project_asset_id}"
        return message
    except FileNotFoundError:
        return f"没有找到本 Agent 的视频任务记录: {task_id}"
    except Exception as exc:
        return f"查询视频任务失败: {exc}"


video_generate_tool = video_generate
video_query_tool = video_query
