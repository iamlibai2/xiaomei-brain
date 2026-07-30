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
    read_stored_attachment,
    restore_attachment_refs,
)
from xiaomei_brain.gateway.inbound import Accepted
from xiaomei_brain.gateway.schemas import ChatAttachment
from xiaomei_brain.gateway.server_methods import MethodRouter
from xiaomei_brain.memory.conversation_db import ConversationDB as RealConversationDB


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


def test_docx_is_saved_as_document_without_eager_context_extraction(tmp_path, monkeypatch):
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
    assert "text_content" not in prepared[0]
    model_input = append_text_attachments("总结", prepared)
    assert 'attached_document id="attachment-1"' in model_input
    assert "read_document" in model_input


def test_pptx_is_saved_as_document_without_eager_context_extraction(tmp_path, monkeypatch):
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
    assert prepared[0]["kind"] == "document"
    assert "text_content" not in prepared[0]


@pytest.mark.parametrize("name,mime_type", [
    ("report.pdf", "application/pdf"),
    ("data.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
])
def test_pdf_and_xlsx_are_accepted_as_documents(tmp_path, monkeypatch, name, mime_type):
    monkeypatch.setattr(attachment_module.Path, "home", classmethod(lambda cls: tmp_path))
    prepared, images, saved = prepare_attachments(
        "xiaomei", "session-1", [payload(name, mime_type, b"document-bytes")],
    )

    assert images == []
    assert saved[0].suffix == Path(name).suffix
    assert prepared[0]["kind"] == "document"
    assert "text_content" not in prepared[0]


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
        "xiaomei_brain.gateway.methods.chat.prepare_attachments",
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


def test_attachment_get_reads_only_attachment_owned_by_session(tmp_path, monkeypatch):
    monkeypatch.setattr(attachment_module.Path, "home", classmethod(lambda cls: tmp_path))
    data = b"image-bytes"
    prepared, _, _ = prepare_attachments(
        "xiaomei",
        "session-1",
        [payload("photo.png", "image/png", data)],
    )
    db = RealConversationDB(tmp_path / "brain.db")
    db.log(
        "session-1",
        "user",
        "look",
        metadata={"attachments": public_attachment_metadata(prepared)},
    )
    living = SimpleNamespace(
        _agent_id="xiaomei",
        agent=SimpleNamespace(conversation_db=db),
    )
    router = MethodRouter(living=living)
    router._auth_sessions.add("connection-1")

    response = router.dispatch("connection-1", "rpc-1", "attachment.get", {
        "session_id": "session-1",
        "attachment_id": "attachment-1",
    })
    denied = router.dispatch("connection-1", "rpc-2", "attachment.get", {
        "session_id": "another-session",
        "attachment_id": "attachment-1",
    })

    assert base64.b64decode(response["result"]["attachment"]["data_base64"]) == data
    assert response["result"]["attachment"]["name"] == "photo.png"
    assert denied["error"]["code"] == -32602
    db.close()


def test_read_stored_attachment_rejects_metadata_size_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(attachment_module.Path, "home", classmethod(lambda cls: tmp_path))
    prepared, _, _ = prepare_attachments(
        "xiaomei",
        "session-1",
        [payload("photo.png", "image/png", b"abc")],
    )
    metadata = public_attachment_metadata(prepared)[0]
    metadata["size"] = 4

    with pytest.raises(AttachmentError):
        read_stored_attachment("xiaomei", "session-1", metadata)


def test_restored_text_attachments_are_combined_in_one_model_input(tmp_path, monkeypatch):
    monkeypatch.setattr(attachment_module.Path, "home", classmethod(lambda cls: tmp_path))
    prepared, _, _ = prepare_attachments(
        "xiaomei",
        "session-1",
        [
            payload("requirements.txt", "text/plain", b"requirement A", "attachment-1"),
            payload("notes.md", "text/markdown", b"constraint B", "attachment-2"),
        ],
    )

    restored, image_paths = restore_attachment_refs(
        "xiaomei", "session-1", public_attachment_metadata(prepared),
    )
    model_input = append_text_attachments("Compare these files", restored)

    assert image_paths == []
    assert "requirement A" in model_input
    assert "constraint B" in model_input
    assert model_input.index("requirements.txt") < model_input.index("notes.md")


def test_chat_retry_reuses_agent_owned_message_and_attachments(tmp_path, monkeypatch):
    monkeypatch.setattr(attachment_module.Path, "home", classmethod(lambda cls: tmp_path))
    prepared, _, _ = prepare_attachments(
        "xiaomei",
        "session-1",
        [payload("notes.txt", "text/plain", b"important context")],
    )
    db = RealConversationDB(tmp_path / "brain.db")
    message_id = db.log(
        "session-1",
        "user",
        "continue the task",
        user_id="user-1",
        metadata={
            "status": "failed",
            "attachments": public_attachment_metadata(prepared),
        },
    )

    class Inbound:
        def __init__(self):
            self.messages = []

        def accept(self, raw):
            self.messages.append(raw)
            return Accepted(LivingMessage(
                content=raw.content,
                session_id=raw.session_id,
                attachments=raw.attachments,
                images=raw.images,
            ))

    inbound = Inbound()
    living = SimpleNamespace(
        _agent_id="xiaomei",
        agent=SimpleNamespace(conversation_db=db),
        _gateway_inbound=inbound,
    )
    router = MethodRouter(living=living)
    router._auth_sessions.add("connection-1")
    params = {
        "message_id": message_id,
        "client_request_id": "retry-1",
        "session_id": "session-1",
    }

    first = router.dispatch("connection-1", "rpc-1", "chat.retry", params)
    duplicate = router.dispatch("connection-1", "rpc-2", "chat.retry", params)

    assert first["result"]["accepted"] is True
    assert duplicate["result"]["duplicate"] is True
    assert len(inbound.messages) == 1
    retried = inbound.messages[0]
    assert retried.content == "continue the task"
    assert retried.metadata == {"retry_of": message_id}
    assert retried.attachments[0]["text_content"] == "important context"
    assert Path(retried.attachments[0]["local_path"]).is_file()
    db.close()


def test_chat_retry_rejects_completed_or_other_session_message(tmp_path):
    db = RealConversationDB(tmp_path / "brain.db")
    message_id = db.log(
        "session-1", "user", "done", metadata={"status": "completed"},
    )
    router = MethodRouter(living=SimpleNamespace(
        _agent_id="xiaomei",
        agent=SimpleNamespace(conversation_db=db),
    ))
    router._auth_sessions.add("connection-1")

    completed = router.dispatch("connection-1", "rpc-1", "chat.retry", {
        "message_id": message_id,
        "client_request_id": "retry-1",
        "session_id": "session-1",
    })
    other_session = router.dispatch("connection-1", "rpc-2", "chat.retry", {
        "message_id": message_id,
        "client_request_id": "retry-2",
        "session_id": "session-2",
    })

    assert completed["error"]["code"] == -32602
    assert other_session["error"]["code"] == -32602
    db.close()
