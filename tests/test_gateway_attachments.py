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
    MAX_ATTACHMENT_BYTES,
    append_text_attachments,
    prepare_attachments,
    prepare_local_attachments,
    public_attachment_metadata,
    read_stored_attachment,
    restore_attachment_refs,
)
from xiaomei_brain.gateway.inbound import Accepted
from xiaomei_brain.gateway.connection import cm
from xiaomei_brain.gateway.schemas import ChatAttachment, ChatSendParams
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


def test_channel_local_image_is_imported_as_durable_session_attachment(
    tmp_path, monkeypatch,
):
    home = tmp_path / "home"
    channel_temp = tmp_path / "channel-temp"
    channel_temp.mkdir()
    source = channel_temp / "meal.jpg"
    source.write_bytes(b"jpeg-content")
    monkeypatch.setattr(attachment_module.Path, "home", classmethod(lambda cls: home))

    prepared, images, saved = prepare_local_attachments(
        "test", "dingtalk-person-1", [source],
    )

    assert len(prepared) == 1
    assert prepared[0]["name"] == "meal.jpg"
    assert prepared[0]["kind"] == "image"
    assert prepared[0]["mime_type"] == "image/jpeg"
    assert images == [str(saved[0])]
    assert saved[0].read_bytes() == b"jpeg-content"
    assert saved[0].is_relative_to(
        home / ".xiaomei-brain" / "test" / "workspace" / "inputs" / "attachments"
    )
    assert source.exists()


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


def test_text_artifact_annotation_is_added_to_model_context(tmp_path, monkeypatch):
    monkeypatch.setattr(attachment_module.Path, "home", classmethod(lambda cls: tmp_path))
    prepared, _, _ = prepare_attachments(
        "xiaomei", "session-1", [payload("notes.md", "text/markdown", b"before selected after")],
    )
    prepared[0]["annotation"] = {
        "kind": "text",
        "selected_text": "selected",
        "context_before": "before ",
        "context_after": " after",
    }
    prepared[0]["managed_artifact_relative_path"] = "work/notes.md"

    model_input = append_text_attachments("rewrite", prepared)

    assert '<attached_file name="notes.md" workspace_path="work/notes.md">' in model_input
    assert '<document_annotation kind="text">' in model_input
    assert "<selected_text>selected</selected_text>" in model_input
    assert "workspace_path exactly" in model_input
    assert "Update this Agent-owned artifact in place" in model_input


def test_visualization_artifact_exposes_in_place_revision_context():
    artifact_id = "a" * 32
    model_input = append_text_attachments("make it dark", [{
        "id": artifact_id,
        "name": "dashboard.visualization.html",
        "mime_type": "text/html",
        "size": 24,
        "kind": "text",
        "text_content": '<div id="dashboard"></div>',
        "managed_artifact_relative_path": "dashboard.visualization.html",
        "managed_artifact_path": r"C:\agent\workspace\dashboard.visualization.html",
        "presentation_mode": "visualization_fullscreen",
        "source_artifact": {
            "artifact_id": artifact_id,
            "session_id": "session-1",
        },
    }])

    assert (
        f'<attached_file id="{artifact_id}" name="dashboard.visualization.html" '
        'workspace_path="dashboard.visualization.html">'
    ) in model_input
    assert "write_visualization with this source_attachment_id" in model_input
    assert "updated in place" in model_input


def test_non_fullscreen_visualization_keeps_normal_attachment_context():
    artifact_id = "b" * 32
    model_input = append_text_attachments("summarize this", [{
        "id": artifact_id,
        "name": "dashboard.visualization.html",
        "mime_type": "text/html",
        "size": 24,
        "kind": "text",
        "text_content": '<div id="dashboard"></div>',
        "managed_artifact_relative_path": "dashboard.visualization.html",
        "managed_artifact_path": r"C:\agent\workspace\dashboard.visualization.html",
        "source_artifact": {
            "artifact_id": artifact_id,
            "session_id": "session-1",
        },
    }])

    assert f'<attached_file name="dashboard.visualization.html"' in model_input
    assert "source_attachment_id" not in model_input
    assert "updated in place" not in model_input


def test_image_attachment_id_is_added_to_model_context(tmp_path, monkeypatch):
    monkeypatch.setattr(attachment_module.Path, "home", classmethod(lambda cls: tmp_path))
    prepared, images, _ = prepare_attachments(
        "xiaomei",
        "session-1",
        [payload("cover.png", "image/png", b"image-bytes", "image-42")],
    )

    model_input = append_text_attachments("把这张图放进 Word", prepared)

    assert len(images) == 1
    assert '<attached_image id="image-42" name="cover.png" mime_type="image/png">' in model_input
    assert "attachment_id" in model_input


def test_video_attachment_is_saved_restored_and_added_to_tool_context(tmp_path, monkeypatch):
    monkeypatch.setattr(attachment_module.Path, "home", classmethod(lambda cls: tmp_path))
    prepared, images, saved = prepare_attachments(
        "xiaomei",
        "session-1",
        [payload("shot-001.mp4", "video/mp4", b"video-bytes", "video-42")],
    )

    assert images == []
    assert saved[0].suffix == ".mp4"
    assert prepared[0]["kind"] == "video"
    model_input = append_text_attachments("把这个镜头加入项目", prepared)
    assert '<attached_video id="video-42" name="shot-001.mp4" mime_type="video/mp4">' in model_input
    assert "attachment_id" in model_input

    metadata = public_attachment_metadata(prepared)
    restored, restored_images = restore_attachment_refs("xiaomei", "session-1", metadata)
    assert restored_images == []
    assert restored[0]["kind"] == "video"
    assert Path(restored[0]["local_path"]).read_bytes() == b"video-bytes"


def test_video_attachment_has_larger_limit_than_documents(tmp_path, monkeypatch):
    monkeypatch.setattr(attachment_module.Path, "home", classmethod(lambda cls: tmp_path))
    data = b"v" * (MAX_ATTACHMENT_BYTES + 1)

    prepared, _, _ = prepare_attachments(
        "xiaomei",
        "session-1",
        [payload("clip.mp4", "video/mp4", data)],
    )

    assert prepared[0]["size"] == len(data)
    with pytest.raises(AttachmentError, match="超过 5 MB"):
        prepare_attachments(
            "xiaomei",
            "session-2",
            [payload("notes.pdf", "application/pdf", data)],
        )


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


def test_document_annotation_is_public_and_added_to_model_context(tmp_path, monkeypatch):
    monkeypatch.setattr(attachment_module.Path, "home", classmethod(lambda cls: tmp_path))
    data = office_archive({"word/document.xml": "<document/>"})
    prepared, _, _ = prepare_attachments(
        "xiaomei",
        "session-1",
        [payload(
            "proposal.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            data,
        )],
    )
    prepared[0]["source_artifact"] = {
        "artifact_id": "a" * 32,
        "session_id": "source-session",
    }
    prepared[0]["annotation"] = {
        "kind": "text",
        "page": 3,
        "selected_text": "需要重写的段落",
        "context_before": "上一段",
        "context_after": "下一段",
    }

    metadata = public_attachment_metadata(prepared)[0]
    model_input = append_text_attachments("改得更正式", prepared)

    assert metadata["source_artifact"]["artifact_id"] == "a" * 32
    assert metadata["annotation"]["selected_text"] == "需要重写的段落"
    assert '<document_annotation kind="text" page="3">' in model_input
    assert "<selected_text>需要重写的段落</selected_text>" in model_input
    assert "preserve unrelated content and formatting" in model_input


def test_spreadsheet_annotation_identifies_exact_sheet_and_range(tmp_path, monkeypatch):
    monkeypatch.setattr(attachment_module.Path, "home", classmethod(lambda cls: tmp_path))
    prepared, _, _ = prepare_attachments(
        "xiaomei",
        "session-1",
        [payload(
            "sales.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            b"workbook",
        )],
    )
    prepared[0]["annotation"] = {
        "kind": "spreadsheet",
        "sheet": "华东销售",
        "range": "B2:C4",
        "selected_text": "地区\t销售额\n上海\t120\n杭州\t80",
    }

    model_input = append_text_attachments("把金额改为含税价", prepared)

    assert (
        '<document_annotation kind="spreadsheet" sheet="华东销售" range="B2:C4">'
        in model_input
    )
    assert "<selected_cells>地区\t销售额\n上海\t120\n杭州\t80</selected_cells>" in model_input
    assert "preserve formulas and formatting outside the range" in model_input


def test_chat_schema_accepts_spreadsheet_artifact_selection():
    parsed = ChatSendParams.model_validate({
        "content": "修改选中区域",
        "client_request_id": "request-1",
        "session_id": "session-1",
        "artifact_references": [{
            "artifact_id": "a" * 32,
            "session_id": "source-session",
            "selection": {
                "kind": "spreadsheet",
                "sheet": "Sheet1",
                "range": "A2:B5",
                "selected_text": "产品\t金额\nA\t10",
            },
        }],
    })

    selection = parsed.artifact_references[0].selection
    assert selection is not None
    assert selection.kind == "spreadsheet"
    assert selection.sheet == "Sheet1"
    assert selection.range == "A2:B5"


def test_presentation_annotation_identifies_exact_slide_element(tmp_path, monkeypatch):
    monkeypatch.setattr(attachment_module.Path, "home", classmethod(lambda cls: tmp_path))
    prepared, _, _ = prepare_attachments(
        "xiaomei",
        "session-1",
        [payload(
            "deck.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            office_archive({"ppt/presentation.xml": "<presentation/>"}),
        )],
    )
    prepared[0]["annotation"] = {
        "kind": "presentation",
        "slide": 2,
        "element_id": "slide-2-shape-3",
        "element_type": "text",
        "selected_text": "Old heading",
    }

    model_input = append_text_attachments("Make it shorter", prepared)

    assert (
        '<document_annotation kind="presentation" slide="2" '
        'element_id="slide-2-shape-3" element_type="text">'
        in model_input
    )
    assert "Use update_element" in model_input


def test_chat_schema_accepts_presentation_artifact_selection():
    parsed = ChatSendParams.model_validate({
        "content": "Change the selected heading",
        "client_request_id": "request-presentation",
        "session_id": "session-1",
        "artifact_references": [{
            "artifact_id": "c" * 32,
            "session_id": "source-session",
            "selection": {
                "kind": "presentation",
                "slide": 2,
                "element_id": "slide-2-shape-3",
                "element_type": "text",
                "selected_text": "Old heading",
            },
        }],
    })

    selection = parsed.artifact_references[0].selection
    assert selection is not None
    assert selection.kind == "presentation"
    assert selection.slide == 2
    assert selection.element_id == "slide-2-shape-3"


def test_chat_schema_accepts_presentation_line_selection(tmp_path, monkeypatch):
    parsed = ChatSendParams.model_validate({
        "content": "改成绿色虚线，末端加箭头",
        "client_request_id": "request-presentation-line",
        "session_id": "session-1",
        "artifact_references": [{
            "artifact_id": "d" * 32,
            "session_id": "source-session",
            "selection": {
                "kind": "presentation",
                "slide": 2,
                "element_id": "slide-2-shape-id-8",
                "element_type": "line",
                "selected_text": "",
            },
        }],
    })

    selection = parsed.artifact_references[0].selection
    assert selection is not None
    assert selection.kind == "presentation"
    assert selection.element_type == "line"

    monkeypatch.setattr(attachment_module.Path, "home", classmethod(lambda cls: tmp_path))
    prepared, _, _ = prepare_attachments(
        "xiaomei",
        "session-1",
        [payload(
            "deck.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            office_archive({"ppt/presentation.xml": "<presentation/>"}),
        )],
    )
    prepared[0]["annotation"] = selection.model_dump()
    model_input = append_text_attachments("改成绿色虚线，末端加箭头", prepared)

    assert 'element_type="line"' in model_input
    assert "connector color, width, dash style, arrows" in model_input


def test_presentation_table_cell_annotation_includes_revision_and_coordinates(tmp_path, monkeypatch):
    monkeypatch.setattr(attachment_module.Path, "home", classmethod(lambda cls: tmp_path))
    prepared, _, _ = prepare_attachments(
        "xiaomei",
        "session-1",
        [payload(
            "deck.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            office_archive({"ppt/presentation.xml": "<presentation/>"}),
        )],
    )
    prepared[0]["annotation"] = {
        "kind": "presentation",
        "slide": 3,
        "element_id": "slide-3-shape-id-12",
        "element_type": "table",
        "selected_text": "Old value",
        "source_revision": "a" * 64,
        "row": 2,
        "column": 4,
    }

    model_input = append_text_attachments("Change the cell", prepared)

    assert 'source_revision="' + "a" * 64 + '" row="2" column="4"' in model_input
    assert "use update_table_cell" in model_input


def test_presentation_chart_annotation_keeps_native_chart_guidance(tmp_path, monkeypatch):
    monkeypatch.setattr(attachment_module.Path, "home", classmethod(lambda cls: tmp_path))
    prepared, _, _ = prepare_attachments(
        "xiaomei",
        "session-1",
        [payload(
            "deck.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            office_archive({"ppt/presentation.xml": "<presentation/>"}),
        )],
    )
    prepared[0]["annotation"] = {
        "kind": "presentation",
        "slide": 4,
        "element_id": "slide-4-shape-id-9",
        "element_type": "chart",
        "selected_text": "Sales\nQ1 / Q2\nEast: 10, 20",
        "source_revision": "b" * 64,
    }

    model_input = append_text_attachments("Change Q2 to 28", prepared)

    assert "Use update_chart" in model_input
    assert "Keep it as a native chart" in model_input


def test_html_artifact_annotation_identifies_exact_element(tmp_path, monkeypatch):
    monkeypatch.setattr(attachment_module.Path, "home", classmethod(lambda cls: tmp_path))
    prepared, _, _ = prepare_attachments(
        "xiaomei", "session-1", [payload("page.html", "text/html", b"<main><h1>Hello</h1></main>")],
    )
    prepared[0]["annotation"] = {
        "kind": "html",
        "selector": "main > h1",
        "tag": "h1",
        "selected_text": "Hello",
        "outer_html": '<h1 class="title">Hello</h1>',
        "context_before": "",
        "context_after": "",
    }

    model_input = append_text_attachments("make it blue", prepared)

    assert '<document_annotation kind="html" selector="main &gt; h1" tag="h1">' in model_input
    assert "&lt;h1 class=\"title\"&gt;Hello&lt;/h1&gt;" in model_input
    assert "present the same artifact again" in model_input


def test_chat_schema_accepts_html_artifact_selection():
    parsed = ChatSendParams.model_validate({
        "content": "change selected element",
        "client_request_id": "request-html",
        "session_id": "session-1",
        "artifact_references": [{
            "artifact_id": "b" * 32,
            "session_id": "source-session",
            "selection": {
                "kind": "html",
                "selector": "#hero > h1",
                "tag": "h1",
                "selected_text": "Hello",
                "outer_html": '<h1 id="title">Hello</h1>',
                "context_before": "",
                "context_after": "",
            },
        }],
    })

    selection = parsed.artifact_references[0].selection
    assert selection is not None
    assert selection.kind == "html"
    assert selection.selector == "#hero > h1"
    assert selection.outer_html == '<h1 id="title">Hello</h1>'


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


def test_chat_send_allows_video_total_above_document_limit(monkeypatch):
    prepared = [{
        "id": "video-1", "name": "clip.mp4", "mime_type": "video/mp4",
        "size": 9 * 1024 * 1024, "kind": "video", "local_path": "clip.mp4",
    }]
    monkeypatch.setattr(
        "xiaomei_brain.gateway.methods.chat.prepare_attachments",
        lambda *_args: (prepared, [], []),
    )

    class Inbound:
        def accept(self, raw):
            return Accepted(LivingMessage(
                content=raw.content,
                session_id=raw.session_id,
                attachments=raw.attachments,
                images=raw.images,
            ))

    router = MethodRouter(living=SimpleNamespace(
        _agent_id="xiaomei",
        _gateway_inbound=Inbound(),
    ))
    router._auth_sessions.add("connection-1")
    response = router.dispatch("connection-1", "rpc-video", "chat.send", {
        "content": "处理这个视频",
        "client_request_id": "request-video",
        "session_id": "session-1",
        "attachments": [payload("clip.mp4", "video/mp4", b"video").model_dump()],
    })

    assert response["result"]["accepted"] is True


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


def test_chat_continue_creates_a_new_turn_without_replaying_original_input(tmp_path):
    db = RealConversationDB(tmp_path / "brain.db")
    db.log(
        "session-1",
        "user",
        "run a side-effecting task",
        user_id="ws-user",
        metadata={"turn_id": "turn-interrupted", "status": "interrupted"},
    )

    class Inbound:
        def __init__(self):
            self.messages = []

        def accept(self, raw):
            self.messages.append(raw)
            return Accepted(LivingMessage(
                content=raw.content,
                user_id=raw.peer_id,
                session_id=raw.session_id,
                turn_id="turn-continuation",
                message_id=42,
                continued_from_turn_id=raw.metadata["continued_from_turn_id"],
            ))

    inbound = Inbound()
    living = SimpleNamespace(
        agent=SimpleNamespace(conversation_db=db),
        _gateway_inbound=inbound,
        active_turn_snapshot=lambda: None,
    )
    router = MethodRouter(living=living)
    conn_id = "continue-connection"
    router._auth_sessions.add(conn_id)
    cm.set_session("session-1", conn_id)
    cm.bind_person(conn_id, "ws-user")
    params = {
        "session_id": "session-1",
        "interrupted_turn_id": "turn-interrupted",
        "client_request_id": "continue-1",
    }

    try:
        first = router.dispatch(conn_id, "rpc-1", "chat.continue", params)
        duplicate = router.dispatch(conn_id, "rpc-2", "chat.continue", params)
    finally:
        cm.unregister(conn_id)

    assert first["result"]["accepted"] is True
    assert first["result"]["turn_id"] == "turn-continuation"
    assert duplicate["result"]["duplicate"] is True
    assert len(inbound.messages) == 1
    assert inbound.messages[0].content == "继续"
    assert inbound.messages[0].metadata == {
        "continued_from_turn_id": "turn-interrupted",
    }
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


def test_chat_retry_resumes_completed_message_after_capability_becomes_ready(tmp_path):
    db = RealConversationDB(tmp_path / "brain.db")
    message_id = db.log(
        "session-1",
        "user",
        "search today's news",
        metadata={
            "status": "completed",
            "capability_blocked": {
                "active": True,
                "capability_id": "web_search",
                "request_id": "capability-setup-1",
            },
        },
    )

    class Inbound:
        def __init__(self):
            self.messages = []

        def accept(self, raw):
            self.messages.append(raw)
            return Accepted(LivingMessage(content=raw.content, session_id=raw.session_id))

    inbound = Inbound()
    agent = SimpleNamespace(
        conversation_db=db,
        get_capability=lambda capability_id: {
            "id": capability_id,
            "status": "ready",
        },
    )
    router = MethodRouter(living=SimpleNamespace(
        _agent_id="xiaomei",
        agent=agent,
        _gateway_inbound=inbound,
    ))
    router._auth_sessions.add("connection-1")

    response = router.dispatch("connection-1", "rpc-1", "chat.retry", {
        "message_id": message_id,
        "client_request_id": "capability-resume-1",
        "session_id": "session-1",
    })

    assert response["result"]["accepted"] is True
    assert inbound.messages[0].metadata == {
        "retry_of": message_id,
        "resumed_capability_id": "web_search",
    }
    stored = db.get_user_message(message_id, "session-1")
    metadata = json.loads(stored["metadata"])
    assert metadata["capability_blocked"]["active"] is False
    assert metadata["capability_blocked"]["capability_id"] == "web_search"
    db.close()


def test_chat_retry_keeps_capability_blocked_until_runtime_is_ready(tmp_path):
    db = RealConversationDB(tmp_path / "brain.db")
    message_id = db.log(
        "session-1",
        "user",
        "search today's news",
        metadata={
            "status": "completed",
            "capability_blocked": {"active": True, "capability_id": "web_search"},
        },
    )
    agent = SimpleNamespace(
        conversation_db=db,
        get_capability=lambda capability_id: {
            "id": capability_id,
            "status": "preparing",
        },
    )
    router = MethodRouter(living=SimpleNamespace(_agent_id="xiaomei", agent=agent))
    router._auth_sessions.add("connection-1")

    response = router.dispatch("connection-1", "rpc-1", "chat.retry", {
        "message_id": message_id,
        "client_request_id": "capability-resume-1",
        "session_id": "session-1",
    })

    assert response["error"]["code"] == -32602
    metadata = json.loads(db.get_user_message(message_id, "session-1")["metadata"])
    assert metadata["capability_blocked"]["active"] is True
    db.close()
