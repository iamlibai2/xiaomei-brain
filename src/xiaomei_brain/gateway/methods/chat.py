"""Gateway chat lifecycle methods."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Any

from ..attachments import (
    AttachmentError,
    MAX_REFERENCED_ARTIFACT_BYTES,
    MAX_TOTAL_BYTES,
    MAX_VIDEO_TOTAL_BYTES,
    attachment_fingerprint,
    cleanup_attachments,
    prepare_attachments,
    restore_attachment_refs,
)
from ..artifacts import ArtifactError, managed_artifact_path, read_stored_artifact
from ..connection import cm
from ..protocol import ErrorCode, build_error, build_response
from ..schemas import (
    ChatAbortParams,
    ChatCompactParams,
    ChatHistoryParams,
    ChatRetryParams,
    ChatSendParams,
    format_error,
)

logger = logging.getLogger(__name__)


class ChatMethods:
    def __init__(self, living: Any) -> None:
        self._living = living
        self._receipts_lock = threading.Lock()
        self._receipts: OrderedDict[
            tuple[str, str], tuple[str, str, str, dict[str, Any]]
        ] = OrderedDict()

    @property
    def handlers(self) -> dict[str, Any]:
        return {
            "chat.send": self.handle_send,
            "chat.retry": self.handle_retry,
            "chat.abort": self.handle_abort,
            "chat.compact": self.handle_compact,
            "chat.history": self.handle_history,
        }

    def handle_send(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = ChatSendParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, f"参数无效: {format_error(exc)}")

        content = parsed.content.strip()
        if (
            not content
            and not parsed.attachments
            and not parsed.attachment_refs
            and not parsed.artifact_references
        ):
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "消息内容和附件不能同时为空")
        if (
            len(parsed.attachments)
            + len(parsed.attachment_refs)
            + len(parsed.artifact_references)
            > 4
        ):
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "一次最多发送 4 个附件")
        if len(parsed.attachment_refs) != len(set(parsed.attachment_refs)):
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "附件引用不能重复")
        artifact_keys = [
            (item.session_id, item.artifact_id)
            for item in parsed.artifact_references
        ]
        if len(artifact_keys) != len(set(artifact_keys)):
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "产物引用不能重复")
        session_id = cm.resolve_session(conn_id, parsed.session_id, f"ws-{conn_id[:8]}")
        if session_id is None:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "不能访问当前连接之外的会话")
        # 旧客户端可能仍回显 user_id，但它只能与 Gateway 已绑定的
        # person_id 相同；缺失时直接使用服务器身份，绝不据此切换人物。
        requested_user_id = str(params.get("user_id", ""))
        user_id = cm.resolve_user(conn_id, requested_user_id, "ws-user")
        if user_id is None:
            return build_error(req_id, ErrorCode.UNAUTHORIZED, "当前连接身份无效或尚未认证")
        invocation: dict[str, str] = {}
        if parsed.invocation is not None:
            from xiaomei_brain.agent.invocations import validate_invocation

            try:
                invocation = validate_invocation(
                    getattr(self._living, "agent", None),
                    parsed.invocation.model_dump(mode="json"),
                )
            except (AttributeError, KeyError, ValueError) as exc:
                return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))
        attachments_fingerprint = (
            attachment_fingerprint(parsed.attachments)
            + ":" + ",".join(parsed.attachment_refs)
            + ":artifacts=" + json.dumps(
                [item.model_dump(mode="json") for item in parsed.artifact_references],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + f":retry={parsed.retry_of_message_id or ''}"
            + ":invocation=" + json.dumps(
                invocation,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        receipt_key = (session_id, parsed.client_request_id)
        with self._receipts_lock:
            receipt = self._receipts.get(receipt_key)
            if receipt is not None:
                original_content, original_user_id, original_fingerprint, original_response = receipt
                if (
                    original_content != content
                    or original_user_id != user_id
                    or original_fingerprint != attachments_fingerprint
                ):
                    return build_error(
                        req_id,
                        ErrorCode.INVALID_PARAMS,
                        "client_request_id 已被同一会话中的其他消息使用",
                    )
                self._receipts.move_to_end(receipt_key)
                return build_response(req_id, result={**original_response, "duplicate": True})

        living = self._living
        if living is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "Gateway 未就绪")
        db = getattr(getattr(living, "agent", None), "conversation_db", None)
        capability_resume_id = ""
        capability_request_id = ""
        if parsed.retry_of_message_id is not None:
            source = db.get_user_message(parsed.retry_of_message_id, session_id) if db else None
            if source is None or source.get("content", "").strip() != content:
                return build_error(req_id, ErrorCode.INVALID_PARAMS, "重试消息不属于该会话或内容不一致")
            try:
                source_metadata = json.loads(source.get("metadata") or "{}")
            except (TypeError, json.JSONDecodeError):
                source_metadata = {}
            capability_resume_id = self._resumable_capability_id(source_metadata)
            blocked = source_metadata.get("capability_blocked") if isinstance(source_metadata, dict) else None
            if isinstance(blocked, dict):
                capability_request_id = str(blocked.get("request_id", ""))
            if not isinstance(source_metadata, dict) or (
                source_metadata.get("status") not in {"failed", "interrupted"}
                and not capability_resume_id
            ):
                if self._blocked_capability_id(source_metadata):
                    return build_error(
                        req_id,
                        ErrorCode.INVALID_PARAMS,
                        "能力尚未就绪，请完成配置并按提示重启 Agent 后再继续任务",
                    )
                return build_error(req_id, ErrorCode.INVALID_PARAMS, "只有失败或已中断的消息可以重试")
            source_attachment_ids = [
                item.get("id") for item in source_metadata.get("attachments", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            ]
            if source_attachment_ids != parsed.attachment_refs:
                return build_error(req_id, ErrorCode.INVALID_PARAMS, "重试必须使用原消息的附件")

        saved_paths = []
        try:
            prepared_attachments, image_paths, saved_paths = prepare_attachments(
                getattr(living, "_agent_id", "default"), session_id, parsed.attachments,
            )
            referenced = []
            for attachment_id in parsed.attachment_refs:
                metadata = db.get_attachment_metadata(session_id, attachment_id) if db else None
                if metadata is None:
                    raise AttachmentError("引用附件不属于该会话或不存在")
                referenced.append(metadata)
            restored, restored_images = restore_attachment_refs(
                getattr(living, "_agent_id", "default"), session_id, referenced,
            )
            artifact_attachments: list[dict[str, Any]] = []
            artifact_images: list[str] = []
            for reference in parsed.artifact_references:
                if db is None:
                    raise AttachmentError("Agent 会话数据库尚未就绪")
                artifact = db.get_artifact_metadata(
                    reference.session_id,
                    reference.artifact_id,
                )
                if artifact is None or str(artifact.get("user_id") or "") not in {
                    user_id,
                    "global",
                }:
                    raise AttachmentError("引用产物不存在或当前人物不可访问")
                try:
                    stored = read_stored_artifact(
                        getattr(living, "_agent_id", "default"),
                        reference.session_id,
                        artifact,
                    )
                except ArtifactError as exc:
                    raise AttachmentError(str(exc)) from exc
                prepared_artifacts, prepared_images, artifact_paths = prepare_attachments(
                    getattr(living, "_agent_id", "default"),
                    session_id,
                    [{
                        "id": reference.artifact_id,
                        "name": stored["name"],
                        "mime_type": stored["mime_type"],
                        "size": stored["size"],
                        "data_base64": stored["data_base64"],
                    }],
                    max_item_bytes=MAX_REFERENCED_ARTIFACT_BYTES,
                    max_total_bytes=MAX_REFERENCED_ARTIFACT_BYTES,
                )
                saved_paths.extend(artifact_paths)
                annotation = (
                    reference.selection.model_dump(mode="json")
                    if reference.selection is not None
                    else None
                )
                for item in prepared_artifacts:
                    item["source_artifact"] = {
                        "artifact_id": reference.artifact_id,
                        "session_id": reference.session_id,
                    }
                    managed_relative_path = str(
                        artifact.get("relative_path") or "",
                    ).replace("\\", "/")
                    # Artifact paths are stored relative to the Agent root,
                    # while file tools resolve relative paths from its
                    # workspace.  Expose the latter so the model can pass the
                    # value to read/edit without guessing or duplicating the
                    # leading ``workspace`` directory.
                    if managed_relative_path.startswith("workspace/"):
                        item["managed_artifact_relative_path"] = (
                            managed_relative_path.removeprefix("workspace/")
                        )
                    try:
                        item["managed_artifact_path"] = str(
                            managed_artifact_path(
                                getattr(living, "_agent_id", "default"),
                                artifact,
                            ),
                        )
                    except ArtifactError:
                        # Legacy artifacts without a managed source remain
                        # readable, but write_document will create a new file.
                        pass
                    if annotation is not None:
                        item["annotation"] = annotation
                artifact_attachments.extend(prepared_artifacts)
                artifact_images.extend(prepared_images)

            combined = [*prepared_attachments, *restored, *artifact_attachments]
            combined_ids = [str(item.get("id", "")) for item in combined]
            if len(combined_ids) != len(set(combined_ids)):
                raise AttachmentError("附件标识不能重复")
            combined_limit = (
                MAX_REFERENCED_ARTIFACT_BYTES
                if parsed.artifact_references
                else MAX_VIDEO_TOTAL_BYTES
                if any(item.get("kind") == "video" for item in combined)
                else MAX_TOTAL_BYTES
            )
            if sum(int(item.get("size", 0)) for item in combined) > combined_limit:
                raise AttachmentError(
                    f"单条消息的附件合计不能超过 {combined_limit // (1024 * 1024)} MB"
                )
            prepared_attachments.extend(restored)
            prepared_attachments.extend(artifact_attachments)
            image_paths.extend(restored_images)
            image_paths.extend(artifact_images)
        except AttachmentError as exc:
            cleanup_attachments(saved_paths)
            return build_error(req_id, ErrorCode.INVALID_PARAMS, str(exc))
        except OSError as exc:
            cleanup_attachments(saved_paths)
            logger.exception("Failed to persist chat attachments")
            return build_error(req_id, ErrorCode.INTERNAL_ERROR, f"保存附件失败: {exc}")

        gateway = getattr(living, "_gateway_inbound", None)
        if gateway:
            from ..inbound import Accepted, RawMessage

            accepted_result = gateway.accept(RawMessage(
                content=content,
                source="human",
                channel="ws",
                peer_id=user_id,
                peer_type="human",
                session_id=session_id,
                images=image_paths,
                attachments=prepared_attachments,
                metadata={
                    **({"retry_of": parsed.retry_of_message_id} if parsed.retry_of_message_id else {}),
                    **({"resumed_capability_id": capability_resume_id} if capability_resume_id else {}),
                    **({"invocation": invocation} if invocation else {}),
                },
                reply_channel="ws",
                reply_target=session_id,
            ))
            accepted = isinstance(accepted_result, Accepted)
            response = {"accepted": accepted, "session_id": session_id}
            if accepted:
                living_state = getattr(getattr(living, "state", None), "value", "")
                response["turn_id"] = accepted_result.living_message.turn_id
                response["message_id"] = accepted_result.living_message.message_id
                active_turn_id = str(
                    getattr(
                        accepted_result.living_message,
                        "steered_into_turn_id",
                        "",
                    )
                    or ""
                )
                response["status"] = "steering" if active_turn_id else "queued"
                if active_turn_id:
                    response["active_turn_id"] = active_turn_id
                response["deferred"] = living_state == "dreaming"
                if response["deferred"]:
                    response["deferred_reason"] = "dreaming"
                self._remember_receipt(
                    receipt_key, content, user_id, attachments_fingerprint, response,
                )
                if capability_resume_id and parsed.retry_of_message_id and db is not None:
                    self._mark_capability_resumed(
                        db, parsed.retry_of_message_id, capability_resume_id,
                        accepted_result.living_message.message_id,
                        capability_request_id,
                        session_id,
                    )
            else:
                response["reason"] = getattr(accepted_result, "reason", "REJECTED")
                cleanup_attachments(saved_paths)
            return build_response(req_id, result=response)

        message = living.put_message(
            content,
            session_id=session_id,
            user_id=user_id,
            images=image_paths,
            attachments=prepared_attachments,
            invocation=invocation,
        )
        response = {
            "accepted": True,
            "session_id": session_id,
            "turn_id": message.turn_id,
            "message_id": getattr(message, "message_id", None),
            "status": (
                "steering"
                if getattr(message, "steered_into_turn_id", "")
                else "queued"
            ),
            "deferred": getattr(getattr(living, "state", None), "value", "") == "dreaming",
        }
        if getattr(message, "steered_into_turn_id", ""):
            response["active_turn_id"] = message.steered_into_turn_id
        if response["deferred"]:
            response["deferred_reason"] = "dreaming"
        self._remember_receipt(
            receipt_key, content, user_id, attachments_fingerprint, response,
        )
        if capability_resume_id and parsed.retry_of_message_id and db is not None:
            self._mark_capability_resumed(
                db, parsed.retry_of_message_id, capability_resume_id,
                getattr(message, "message_id", None),
                capability_request_id,
                session_id,
            )
        return build_response(req_id, result=response)

    def handle_retry(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = ChatRetryParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, f"参数无效: {format_error(exc)}")
        session_id = cm.resolve_session(conn_id, parsed.session_id)
        if session_id is None and cm.is_subscribed(conn_id, parsed.session_id):
            session_id = parsed.session_id
        if session_id is None:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "不能访问当前连接之外的会话")
        living = self._living
        db = getattr(getattr(living, "agent", None), "conversation_db", None) if living else None
        if db is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "会话存储未就绪")
        source = db.get_user_message(parsed.message_id, session_id)
        if source is None:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "重试消息不属于该会话或不存在")
        try:
            metadata = json.loads(source.get("metadata") or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        status = metadata.get("status") if isinstance(metadata, dict) else None
        capability_resume_id = self._resumable_capability_id(metadata)
        if status not in {"failed", "interrupted"} and not capability_resume_id:
            if self._blocked_capability_id(metadata):
                return build_error(
                    req_id,
                    ErrorCode.INVALID_PARAMS,
                    "能力尚未就绪，请完成配置并按提示重启 Agent 后再继续任务",
                )
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "只有失败或已中断的消息可以重试")
        attachment_refs = [
            item.get("id") for item in metadata.get("attachments", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ] if isinstance(metadata, dict) else []
        return self.handle_send(conn_id, req_id, {
            "content": source.get("content", ""),
            "client_request_id": parsed.client_request_id,
            "session_id": session_id,
            "attachment_refs": attachment_refs,
            "invocation": metadata.get("invocation") if isinstance(metadata, dict) else None,
            "retry_of_message_id": parsed.message_id,
        })

    def _resumable_capability_id(self, metadata: Any) -> str:
        capability_id = self._blocked_capability_id(metadata)
        agent = getattr(self._living, "agent", None)
        get_capability = getattr(agent, "get_capability", None)
        capability = get_capability(capability_id) if callable(get_capability) and capability_id else None
        if not isinstance(capability, dict) or capability.get("status") not in {"ready", "degraded"}:
            return ""
        return capability_id

    @staticmethod
    def _blocked_capability_id(metadata: Any) -> str:
        if not isinstance(metadata, dict):
            return ""
        blocked = metadata.get("capability_blocked")
        if not isinstance(blocked, dict) or blocked.get("active") is not True:
            return ""
        return str(blocked.get("capability_id", "")).strip()

    def _mark_capability_resumed(
        self,
        db: Any,
        source_message_id: int,
        capability_id: str,
        resumed_message_id: int | None,
        request_id: str,
        session_id: str,
    ) -> None:
        resumed_at = time.time()
        db.update_message_metadata(source_message_id, {
            "capability_blocked": {
                "active": False,
                "capability_id": capability_id,
                "request_id": request_id,
                "resumed_at": resumed_at,
                "resumed_message_id": resumed_message_id,
            },
        })
        if request_id:
            event_hub = getattr(self._living, "_event_hub", None)
            if event_hub is not None:
                event_hub.publish(
                    "capability.setup.updated",
                    {
                        "id": request_id,
                        "session_id": session_id,
                        "capability_id": capability_id,
                        "resume_status": "resumed",
                        "resumed_at": resumed_at,
                        "resumed_message_id": resumed_message_id,
                    },
                    session_id=session_id,
                )
            else:
                update_interaction = getattr(db, "update_interaction_metadata", None)
                if callable(update_interaction):
                    update_interaction(request_id, {
                        "resume_status": "resumed",
                        "resumed_at": resumed_at,
                        "resumed_message_id": resumed_message_id,
                    })

    def handle_abort(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            ChatAbortParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, f"参数无效: {format_error(exc)}")
        living = self._living
        if living is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "Gateway 未就绪")
        try:
            session_id = cm.get_session_id(conn_id)
            broker = getattr(living, "_interaction_broker", None)
            if broker is not None and session_id:
                broker.cancel_session(session_id)
            action_broker = getattr(living, "_action_broker", None)
            if action_broker is not None and session_id:
                action_broker.cancel_session(session_id)
            living.abort_chat()
            return build_response(req_id, result={"aborted": True})
        except Exception as exc:
            return build_error(req_id, ErrorCode.INTERNAL_ERROR, str(exc))

    def handle_compact(self, conn_id: str, req_id: str, params: dict) -> dict:
        """Manually compact the current conversation without creating a chat turn."""
        try:
            parsed = ChatCompactParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, f"参数无效: {format_error(exc)}")
        session_id = cm.resolve_session(conn_id, parsed.session_id)
        if session_id is None:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "不能压缩当前连接之外的会话")
        user_id = cm.resolve_user(conn_id, "")
        if user_id is None:
            return build_error(req_id, ErrorCode.UNAUTHORIZED, "当前连接身份无效或尚未认证")
        instance = getattr(self._living, "agent", None)
        commands = getattr(instance, "commands", None)
        if commands is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "会话压缩服务尚未就绪")
        try:
            result = commands.execute(
                "summarize",
                user_id=user_id,
                session_id=session_id,
            )
        except Exception as exc:
            logger.exception("Manual conversation compact failed")
            return build_error(req_id, ErrorCode.INTERNAL_ERROR, str(exc))
        data = dict(getattr(result, "data", None) or {})
        return build_response(req_id, result={
            "compacted": bool(data.get("node_id")),
            "session_id": session_id,
            **data,
        })

    def handle_history(self, conn_id: str, req_id: str, params: dict) -> dict:
        try:
            parsed = ChatHistoryParams.model_validate(params)
        except Exception as exc:
            return build_error(req_id, ErrorCode.INVALID_REQUEST, f"参数无效: {format_error(exc)}")
        session_id = cm.resolve_session(conn_id, parsed.session_id)
        if session_id is None and cm.is_subscribed(conn_id, parsed.session_id):
            session_id = parsed.session_id
        if session_id is None:
            return build_error(req_id, ErrorCode.INVALID_PARAMS, "不能访问当前连接之外的会话")
        living = self._living
        if living is None:
            return build_error(req_id, ErrorCode.GATEWAY_NOT_READY, "Gateway 未就绪")
        try:
            db = getattr(getattr(living, "agent", None), "conversation_db", None)
            if db is None:
                return build_response(req_id, result={
                    "messages": [], "has_more": False, "next_before_id": None,
                })
            query_session_id = session_id or None
            rows, has_more = db.get_history_page(
                limit=parsed.limit,
                session_id=query_session_id,
                before_id=parsed.before_id,
            )
            list_artifacts = getattr(db, "list_artifacts", None)
            get_cursor_time = getattr(db, "get_message_created_at", None)
            cursor_time = (
                get_cursor_time(parsed.before_id, query_session_id)
                if parsed.before_id is not None and callable(get_cursor_time)
                else None
            )
            artifact_rows = list_artifacts(
                query_session_id,
                since=float(rows[0].get("created_at", 0)) if rows else None,
                until=(
                    cursor_time if cursor_time is not None
                    else float(rows[-1].get("created_at", 0))
                    if rows and parsed.before_id is not None
                    else None
                ),
                presented_only=True,
            ) if callable(list_artifacts) and (rows or parsed.before_id is None) else []
            timeline_rows = [*rows, *(
                {
                    "id": f"artifact:{artifact.get('id', '')}",
                    "role": "artifact",
                    "content": artifact.get("name", ""),
                    "created_at": (
                        artifact.get("presented_at")
                        or artifact.get("created_at", 0)
                    ),
                    "user_id": artifact.get("user_id", ""),
                    "artifact": artifact,
                }
                for artifact in artifact_rows
            )]
            timeline_rows.sort(
                key=lambda row: (float(row.get("created_at", 0)), str(row.get("id", ""))),
            )
            messages = []
            for row in timeline_rows:
                message = {
                    "id": row.get("id"),
                    "role": row.get("role", "user"),
                    "content": row.get("content", ""),
                    "created_at": row.get("created_at", 0),
                    "user_id": row.get("user_id", ""),
                }
                if row.get("role") == "user":
                    try:
                        user_metadata = json.loads(row.get("metadata") or "{}")
                    except (TypeError, json.JSONDecodeError):
                        user_metadata = {}
                    if isinstance(user_metadata, dict) and isinstance(
                        user_metadata.get("attachments"), list,
                    ):
                        message["attachments"] = user_metadata["attachments"]
                    if isinstance(user_metadata, dict):
                        for key in (
                            "turn_id",
                            "status",
                            "error",
                            "retry_of",
                            "steered_into_turn_id",
                            "invocation",
                        ):
                            if key in user_metadata:
                                message[key] = user_metadata[key]
                elif row.get("role") == "assistant":
                    try:
                        assistant_metadata = json.loads(
                            row.get("metadata") or "{}",
                        )
                    except (TypeError, json.JSONDecodeError):
                        assistant_metadata = {}
                    if isinstance(assistant_metadata, dict):
                        if isinstance(
                            assistant_metadata.get("reasoning_content"),
                            str,
                        ):
                            message["reasoning_content"] = assistant_metadata[
                                "reasoning_content"
                            ]
                        if isinstance(
                            assistant_metadata.get("memory_references"),
                            list,
                        ):
                            message["memory_references"] = [
                                reference
                                for reference in assistant_metadata[
                                    "memory_references"
                                ][:8]
                                if isinstance(reference, dict)
                                and isinstance(reference.get("summary"), str)
                            ]
                        if isinstance(
                            assistant_metadata.get("turn_id"),
                            str,
                        ):
                            message["turn_id"] = assistant_metadata["turn_id"]
                if row.get("role") == "interaction":
                    try:
                        interaction = json.loads(row.get("metadata") or "{}")
                    except (TypeError, json.JSONDecodeError):
                        interaction = {}
                    if not isinstance(interaction, dict) or not interaction.get("id"):
                        continue
                    if interaction.get("kind") == "tool_approval":
                        message["action"] = interaction
                    elif interaction.get("kind") == "capability_setup":
                        message["capability_setup"] = interaction
                    else:
                        message["interaction"] = interaction
                elif row.get("role") == "tool":
                    message["tool_call_id"] = row.get("tool_call_id", "")
                    message["tool_name"] = row.get("tool_name", "")
                    try:
                        tool_metadata = json.loads(row.get("metadata") or "{}")
                    except (TypeError, json.JSONDecodeError):
                        tool_metadata = {}
                    if isinstance(tool_metadata, dict) and isinstance(
                        tool_metadata.get("turn_id"),
                        str,
                    ):
                        message["turn_id"] = tool_metadata["turn_id"]
                    if isinstance(tool_metadata, dict) and isinstance(
                        tool_metadata.get("duration_ms"),
                        (int, float),
                    ):
                        message["duration_ms"] = max(
                            0,
                            int(tool_metadata["duration_ms"]),
                        )
                elif row.get("role") == "artifact":
                    artifact = dict(row.get("artifact") or {})
                    if not artifact.get("id"):
                        continue
                    artifact.pop("relative_path", None)
                    artifact.pop("storage_suffix", None)
                    artifact.pop("user_id", None)
                    artifact.pop("session_id", None)
                    artifact.pop("created_at", None)
                    message["artifact"] = artifact
                messages.append(message)
            return build_response(req_id, result={
                "messages": messages,
                "has_more": has_more,
                "next_before_id": rows[0].get("id") if has_more and rows else None,
            })
        except Exception as exc:
            return build_error(req_id, ErrorCode.INTERNAL_ERROR, str(exc))

    def _remember_receipt(
        self,
        key: tuple[str, str],
        content: str,
        user_id: str,
        attachments_fingerprint: str,
        response: dict[str, Any],
    ) -> None:
        with self._receipts_lock:
            self._receipts[key] = (
                content, user_id, attachments_fingerprint, dict(response),
            )
            self._receipts.move_to_end(key)
            while len(self._receipts) > 2048:
                self._receipts.popitem(last=False)
