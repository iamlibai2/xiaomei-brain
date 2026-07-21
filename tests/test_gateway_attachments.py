import base64
import io
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from xiaomei_brain.consciousness.living import LivingMessage
from xiaomei_brain.consciousness.context_pipeline import build_context
from xiaomei_brain.gateway import attachments as attachment_module
from xiaomei_brain.gateway.attachments import (
    AttachmentError,
    append_text_attachments,
    prepare_attachments,
    public_attachment_metadata,
)
from xiaomei_brain.gateway.inbound import Accepted
from xiaomei_brain.gateway.schemas import ChatAttachment
from xiaomei_brain.gateway.server_methods import MethodRouter


def payload(name: str, mime_type: str, data: bytes, attachment_id: str = "attachment-1") -> ChatAttachment:
    return ChatAttachment(
        id=attachment_id,
        name=name,
        mime_type=mime_type,
        size=len(data),
        data_base64=base64.b64encode(data).decode("ascii"),
    )


def test_text_attachment_is_saved_and_added_to_model_context(tmp_path, monkeypatch):
    monkeypatch.setattr(attachment_module.Path, "home", classmethod(lambda cls: tmp_path))
    prepared, images, saved = prepare_attachments(
        "xiaomei", "session-1", [payload("notes.md", "text/markdown", "你好".encode())],
    )

    assert images == []
    assert len(saved) == 1 and saved[0].read_text(encoding="utf-8") == "你好"
    assert public_attachment_metadata(prepared) == [{
        "id": "attachment-1",
        "name": "notes.md",
        "mime_type": "text/markdown",
        "size": 6,
        "kind": "text",
    }]
    model_input = append_text_attachments("总结它", prepared)
    assert "总结它" in model_input
    assert '<attached_file name="notes.md">' in model_input
    assert "你好" in model_input


def test_unsupported_binary_attachment_is_rejected_without_file(tmp_path, monkeypatch):
    monkeypatch.setattr(attachment_module.Path, "home", classmethod(lambda cls: tmp_path))
    with pytest.raises(AttachmentError, match="暂不支持"):
        prepare_attachments("xiaomei", "session-1", [payload("archive.zip", "application/zip", b"zip")])
    assert list(tmp_path.rglob("*")) == []


def office_archive(files: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def test_docx_extracts_paragraphs_and_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(attachment_module.Path, "home", classmethod(lambda cls: tmp_path))
    data = office_archive({
        "word/document.xml": """
        <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:body>
            <w:p><w:r><w:t>项目说明</w:t></w:r></w:p>
            <w:tbl><w:tr>
              <w:tc><w:p><w:r><w:t>姓名</w:t></w:r></w:p></w:tc>
              <w:tc><w:p><w:r><w:t>小美</w:t></w:r></w:p></w:tc>
            </w:tr></w:tbl>
          </w:body>
        </w:document>
        """,
    })
    item = payload(
        "plan.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        data,
    )

    prepared, images, saved = prepare_attachments("xiaomei", "session-1", [item])

    assert images == [] and saved[0].suffix == ".docx"
    assert prepared[0]["kind"] == "document"
    assert "项目说明" in prepared[0]["text_content"]
    assert "姓名\t小美" in prepared[0]["text_content"]


def test_pptx_extracts_slides_and_notes(tmp_path, monkeypatch):
    monkeypatch.setattr(attachment_module.Path, "home", classmethod(lambda cls: tmp_path))
    drawing_ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
    data = office_archive({
        "ppt/slides/slide1.xml": f'<p:sld xmlns:p="urn:p" xmlns:a="{drawing_ns}"><a:t>产品定位</a:t></p:sld>',
        "ppt/slides/slide2.xml": f'<p:sld xmlns:p="urn:p" xmlns:a="{drawing_ns}"><a:t>系统架构</a:t></p:sld>',
        "ppt/notesSlides/notesSlide1.xml": f'<p:notes xmlns:p="urn:p" xmlns:a="{drawing_ns}"><a:t>演讲备注</a:t></p:notes>',
    })
    item = payload(
        "design.pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        data,
    )

    prepared, _, _ = prepare_attachments("xiaomei", "session-1", [item])
    text = prepared[0]["text_content"]

    assert "[幻灯片 1]" in text and "产品定位" in text
    assert "[备注]" in text and "演讲备注" in text
    assert "[幻灯片 2]" in text and "系统架构" in text


def test_context_logs_public_metadata_but_sends_file_content_to_model():
    calls = []

    class ConversationDB:
        def log(self, **kwargs):
            calls.append(kwargs)
            return 1

    agent = SimpleNamespace(
        conversation_db=ConversationDB(), exp_stream=None, session_id="session-1",
        user_id="user-1", messages=[], _last_user_msg_time=None,
    )
    attachment = {
        "id": "attachment-1", "name": "notes.txt", "mime_type": "text/plain",
        "size": 5, "kind": "text", "text_content": "hello", "local_path": "private.txt",
    }

    messages = build_context(agent, "总结", assemble=False, attachments=[attachment])

    assert calls[0]["content"] == "总结"
    assert calls[0]["metadata"] == {"attachments": [{
        "id": "attachment-1", "name": "notes.txt", "mime_type": "text/plain",
        "size": 5, "kind": "text",
    }]}
    assert "hello" in messages[-1]["content"]
    assert "private.txt" not in str(calls[0]["metadata"])


def test_chat_send_transports_attachments_and_deduplicates(monkeypatch):
    prepared = [{
        "id": "attachment-1", "name": "notes.txt", "mime_type": "text/plain",
        "size": 5, "kind": "text", "text_content": "hello", "local_path": "notes.txt",
    }]
    monkeypatch.setattr(
        "xiaomei_brain.gateway.server_methods.prepare_attachments",
        lambda *_args: (prepared, [], []),
    )

    class Inbound:
        def __init__(self):
            self.messages = []

        def accept(self, raw):
            self.messages.append(raw)
            return Accepted(LivingMessage(
                content=raw.content, session_id=raw.session_id,
                attachments=raw.attachments, images=raw.images,
            ))

    inbound = Inbound()
    router = MethodRouter(living=SimpleNamespace(_agent_id="xiaomei", _gateway_inbound=inbound))
    router._auth_sessions.add("connection-1")
    params = {
        "content": "",
        "client_request_id": "request-1",
        "session_id": "session-1",
        "attachments": [payload("notes.txt", "text/plain", b"hello").model_dump()],
    }

    first = router.dispatch("connection-1", "rpc-1", "chat.send", params)
    duplicate = router.dispatch("connection-1", "rpc-2", "chat.send", params)

    assert first["result"]["accepted"] is True
    assert duplicate["result"]["duplicate"] is True
    assert len(inbound.messages) == 1
    assert inbound.messages[0].attachments == prepared


def test_chat_history_returns_public_attachment_metadata():
    metadata = [{
        "id": "attachment-1", "name": "photo.png", "mime_type": "image/png",
        "size": 3, "kind": "image",
    }]

    class ConversationDB:
        def get_history_page(self, **_kwargs):
            return ([{
                "id": 1, "role": "user", "content": "看图", "created_at": 1,
                "user_id": "user-1", "metadata": json.dumps({"attachments": metadata}),
            }], False)

    router = MethodRouter(living=SimpleNamespace(agent=SimpleNamespace(conversation_db=ConversationDB())))
    router._auth_sessions.add("connection-1")
    response = router.dispatch("connection-1", "rpc-1", "chat.history", {"session_id": "session-1"})

    assert response["result"]["messages"][0]["attachments"] == metadata
