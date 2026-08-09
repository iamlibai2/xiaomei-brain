"""On-demand materialization for resources observed in Feishu groups."""

from __future__ import annotations

import base64
import hashlib
import mimetypes
from pathlib import Path
from typing import Any

from xiaomei_brain.gateway.attachments import (
    prepare_attachments,
    restore_attachment_refs,
)
from xiaomei_brain.tools.base import Tool
from xiaomei_brain.tools.execution_context import current_tool_execution


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _register_workspace_asset(
    *,
    agent_instance: Any,
    context: Any,
    group_message: dict[str, Any],
    attachment: dict[str, Any],
) -> dict[str, str] | None:
    """Project a materialized group resource into an accessible focused Workspace."""
    service = context.workspace_service or getattr(
        agent_instance,
        "workspace_service",
        None,
    )
    if service is None or not context.person_id:
        return None
    workspace = service.current_for_session(
        context.session_id,
        person_id=context.person_id,
    )
    if workspace is None:
        return None
    local_path = str(attachment.get("local_path") or "")
    if not local_path or not Path(local_path).is_file():
        raise ValueError("Materialized group attachment has no readable content")
    asset = service.assets.register_attachment(
        workspace.id,
        person_id=context.person_id,
        session_id=context.session_id,
        attachment=attachment,
        sha256=_sha256(local_path),
    )

    metadata = group_message.get("metadata")
    observation_id = (
        str(metadata.get("workspace_observation_id") or "")
        if isinstance(metadata, dict)
        else ""
    )
    observation = (
        service.business.store.get_observation(observation_id)
        if observation_id
        else None
    )
    if observation is None:
        source = service.business.store.find_data_source(
            workspace.id,
            kind="channel",
            locator=f"channel:feishu:session:{context.session_id}",
        )
        external_message_id = str(
            group_message.get("external_message_id") or ""
        )
        if source is not None and external_message_id:
            observation = service.business.store.find_observation(
                source.id,
                f"external:{external_message_id}",
            )
    if observation is None or observation.workspace_id != workspace.id:
        return {
            "workspace_id": workspace.id,
            "asset_id": asset.id,
            "observation_id": "",
        }

    remote = dict(observation.attributes.get("remote_attachment") or {})
    remote.update({"status": "materialized", "asset_id": asset.id})
    updated = service.business.attach_observation_asset(
        workspace.id,
        observation_id=observation.id,
        asset_id=asset.id,
        attribute_updates={"remote_attachment": remote},
        session_id=context.session_id,
        turn_id=context.turn_id,
    )
    return {
        "workspace_id": workspace.id,
        "asset_id": asset.id,
        "observation_id": updated.id,
    }


def create_fetch_group_attachment_tool(adapter: Any) -> Tool:
    """Create a Feishu-owned tool without exposing credentials to the model."""

    def fetch_group_attachment(attachment_ref: str = "") -> dict[str, Any]:
        context = current_tool_execution()
        if context is None or not context.session_id:
            return {"error": "群附件只能在当前 Agent 会话中读取"}
        living = getattr(adapter, "_living", None)
        agent_instance = getattr(living, "agent", None)
        db = getattr(agent_instance, "conversation_db", None)
        if db is None or not hasattr(db, "find_group_attachments"):
            return {"error": "当前 Agent 没有可用的群消息附件记录"}

        matches = db.find_group_attachments(
            context.session_id,
            attachment_ref,
        )
        if not matches:
            return {"error": "没有找到匹配的飞书群附件"}
        if len(matches) > 1:
            return {
                "error": "匹配到多个群附件，请使用准确的附件引用或文件名",
                "candidates": [
                    {
                        "attachment_ref": item["remote_attachment"].get("id", ""),
                        "name": item["remote_attachment"].get("name", ""),
                    }
                    for item in matches[:10]
                ],
            }

        item = matches[0]
        remote = item["remote_attachment"]
        if (
            remote.get("channel") != "feishu"
            or str(remote.get("account_id") or "")
            != str(adapter._channel.account_id)
        ):
            return {"error": "该附件不属于当前飞书连接"}

        agent_id = str(getattr(living, "_agent_id", "default") or "default")
        prepared: list[dict[str, Any]] = []
        materialized = item.get("materialized_attachment")
        if isinstance(materialized, dict):
            try:
                prepared, _images = restore_attachment_refs(
                    agent_id,
                    context.session_id,
                    [materialized],
                )
            except Exception:
                prepared = []

        if not prepared:
            message_type = str(remote.get("message_type") or "file")
            max_bytes = (
                20 * 1024 * 1024 if message_type == "media" else 5 * 1024 * 1024
            )
            data = adapter._channel.download_message_resource(
                str(remote.get("message_id") or ""),
                str(remote.get("resource_key") or ""),
                resource_type=str(remote.get("resource_type") or "file"),
                max_bytes=max_bytes,
            )
            name = str(remote.get("name") or "飞书附件")
            if message_type == "image":
                suffix, mime_type = adapter._detect_image_format(data)
                if not name.lower().endswith(suffix):
                    name = f"{name.rsplit('.', 1)[0]}{suffix}"
            elif message_type == "media":
                mime_type = mimetypes.guess_type(name)[0] or "video/mp4"
            else:
                mime_type = (
                    mimetypes.guess_type(name)[0] or "application/octet-stream"
                )
            prepared, _images, _paths = prepare_attachments(
                agent_id,
                context.session_id,
                [{
                    "id": str(remote.get("id") or ""),
                    "name": name,
                    "mime_type": mime_type,
                    "size": len(data),
                    "data_base64": base64.b64encode(data).decode("ascii"),
                }],
            )
            db.update_group_message_metadata(
                int(item["id"]),
                {"materialized_attachment": dict(prepared[0])},
            )

        core = agent_instance._get_agent()
        known = {
            str(value.get("id") or "")
            for value in getattr(core, "current_attachments", [])
        }
        if str(prepared[0].get("id") or "") not in known:
            core.current_attachments.append(dict(prepared[0]))
        workspace_link = _register_workspace_asset(
            agent_instance=agent_instance,
            context=context,
            group_message=item,
            attachment=prepared[0],
        )
        if workspace_link is not None:
            db.update_group_message_metadata(
                int(item["id"]),
                {
                    "workspace_id": workspace_link["workspace_id"],
                    "workspace_asset_id": workspace_link["asset_id"],
                    "workspace_observation_id": workspace_link["observation_id"],
                },
            )
        public = {
            key: prepared[0].get(key)
            for key in ("id", "name", "mime_type", "size", "kind")
        }
        return {
            "attachment": public,
            "workspace": workspace_link,
            "next": "使用 attachment.id 调用对应的文档、图片或视频工具",
        }

    return Tool(
        name="fetch_group_attachment",
        description=(
            "按需下载当前飞书群现场中尚未落盘的附件。只有当前请求确实需要读取、"
            "分析或引用该文件时才调用；不要为了浏览群消息而批量下载。可传入"
            "group_observations 中的 attachment_ref 或准确文件名。"
        ),
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "attachment_ref": {
                    "type": "string",
                    "description": "remote_group_attachment 中的 ref 或文件名",
                },
            },
        },
        func=fetch_group_attachment,
        source="plugin:feishu",
        category="channel",
    )
