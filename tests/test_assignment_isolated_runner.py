from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from xiaomei_brain.assignments import (
    ActorType,
    AssignmentActor,
    AssignmentExecutionContext,
    AssignmentService,
    AssignmentStore,
    CancellationToken,
    ExecutionControl,
    IsolatedAssignmentRunner,
)
from xiaomei_brain.tools.base import Tool
from xiaomei_brain.tools.registry import ToolRegistry


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, tools=None, log_level=None):
        self.calls.append((messages, tools))
        return self.responses.pop(0)


class FakeLLMTemplate:
    def __init__(self, responses):
        self.responses = responses
        self.clones = []

    def clone_for_isolated_run(self):
        clone = FakeLLM(self.responses)
        self.clones.append(clone)
        return clone


class FakeAgentInstance:
    def __init__(self, llm, tools):
        self.id = "xiaomei"
        self.llm = llm
        self.tools = tools
        self.conversation_db = None

    def get_system_prompt(self):
        return "你是小美。"


def _response(content="", tool_calls=None):
    return SimpleNamespace(
        content=content,
        reasoning=None,
        tool_calls=list(tool_calls or []),
    )


def _context(tmp_path, responses, tools=None):
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda person_id: person_id == "person_1",
    )
    assignment = service.offer(
        title="市场研究",
        objective="研究市场并形成结论",
        actor=AssignmentActor(ActorType.PERSON, "person_1"),
        requester_person_id="person_1",
        scope_type="person",
        scope_id="person_1",
        acceptance_criteria=["给出明确结论"],
    )
    assignment = service.accept(
        assignment.id,
        actor=AssignmentActor(ActorType.AGENT, "xiaomei"),
    )
    registry = tools or ToolRegistry()
    template = FakeLLMTemplate(responses)
    agent = FakeAgentInstance(template, registry)
    context = AssignmentExecutionContext.capture(
        assignment,
        run_id="run_1",
        agent_id="xiaomei",
    )
    checkpoints = []
    control = ExecutionControl(
        CancellationToken(),
        lambda data, safe: checkpoints.append((data, safe)),
    )
    return store, service, agent, context, control, checkpoints


def test_isolated_runner_clones_llm_and_completes_without_live_core(tmp_path, capsys):
    store, service, agent, context, control, _checkpoints = _context(
        tmp_path,
        [_response("研究已完成，结论已形成。")],
    )
    runner = IsolatedAssignmentRunner(agent, service)

    result = runner(context, control)

    assert result.status == "completed"
    assert result.summary == "研究已完成，结论已形成。"
    assert len(agent.llm.clones) == 1
    messages = agent.llm.clones[0].calls[0][0]
    assert "你是小美" in messages[0]["content"]
    assert context.assignment_id in messages[1]["content"]
    assert capsys.readouterr().out == ""
    store.close()


def test_isolated_runner_turns_clarification_marker_into_durable_wait(tmp_path):
    marker = (
        '<WAIT_FOR_PERSON>{"reason":"缺少范围","question":"研究哪个地区？",'
        '"choices":["中国","全球"]}</WAIT_FOR_PERSON>'
    )
    store, service, agent, context, control, _checkpoints = _context(
        tmp_path,
        [_response(marker)],
    )

    result = IsolatedAssignmentRunner(agent, service)(context, control)

    assert result.status == "waiting_person"
    assert result.summary == "研究哪个地区？"
    assert result.checkpoint["pending_interaction"]["choices"] == ["中国", "全球"]
    assert result.safe_to_resume is True
    store.close()


def test_isolated_runner_honors_initial_clarification_without_llm(tmp_path):
    store, service, agent, context, _control, checkpoints = _context(
        tmp_path,
        [_response("不应被调用")],
    )
    pending = {
        "pending_interaction": {
            "reason": "缺少受众",
            "question": "这份 PPT 给谁看？",
            "choices": ["投资人", "客户"],
        },
    }
    control = ExecutionControl(
        CancellationToken(),
        lambda data, safe: checkpoints.append((data, safe)),
        pending,
    )

    result = IsolatedAssignmentRunner(agent, service)(context, control)

    assert result.status == "waiting_person"
    assert result.summary == "这份 PPT 给谁看？"
    assert agent.llm.clones == []
    store.close()


def test_isolated_runner_copies_only_explicit_background_tools(tmp_path):
    registry = ToolRegistry()
    registry.register(Tool(
        name="read_file",
        description="safe",
        parameters={"type": "object", "properties": {}},
        func=lambda: "ok",
    ))
    registry.register(Tool(
        name="clarify",
        description="conversation state",
        parameters={"type": "object", "properties": {}},
        func=lambda: "unsafe",
    ))
    store, service, agent, context, control, _checkpoints = _context(
        tmp_path,
        [_response("done")],
        tools=registry,
    )
    runner = IsolatedAssignmentRunner(agent, service)

    copied = runner._copy_safe_tools()

    assert copied.get("read_file") is not None
    assert copied.get("clarify") is None
    store.close()


def test_isolated_runner_executes_valid_shell_without_approval(tmp_path):
    executed = []
    registry = ToolRegistry()
    registry.register(Tool(
        name="shell",
        description="shell",
        parameters={
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
        func=lambda command: executed.append(command) or "executed",
    ))
    tool_call = SimpleNamespace(
        id="call_1",
        name="shell",
        arguments=json.dumps({"command": "echo change"}),
    )
    store, service, agent, context, control, checkpoints = _context(
        tmp_path,
        [
            _response(tool_calls=[tool_call]),
            _response("命令执行完成。"),
        ],
        tools=registry,
    )

    result = IsolatedAssignmentRunner(agent, service)(context, control)

    assert executed == ["echo change"]
    assert result.status == "completed"
    assert "pending_action" not in result.checkpoint
    assert len(agent.llm.clones[0].calls) == 2
    assert checkpoints[-1][1] is True
    store.close()


def test_isolated_runner_consumes_exact_sealed_approval_once(tmp_path):
    executed = []
    registry = ToolRegistry()
    registry.register(Tool(
        name="shell",
        description="shell",
        parameters={
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
        func=lambda command: executed.append(command) or "ok",
    ))
    arguments = {"command": "echo change"}
    tool_call = SimpleNamespace(
        id="call_2",
        name="shell",
        arguments=json.dumps(arguments),
    )
    store, service, agent, context, _control, checkpoints = _context(
        tmp_path,
        [
            _response(tool_calls=[tool_call]),
            _response("批准的操作已执行，工作完成。"),
        ],
        tools=registry,
    )
    initial = {
        "approved_action": {
            "kind": "action",
            "tool_name": "shell",
            "arguments": arguments,
        },
        "person_response": "批准",
    }
    control = ExecutionControl(
        CancellationToken(),
        lambda data, safe: checkpoints.append((data, safe)),
        initial,
    )

    result = IsolatedAssignmentRunner(agent, service)(context, control)

    assert executed == ["echo change"]
    assert result.status == "completed"
    assert "approved_action" not in result.checkpoint
    assert result.checkpoint["approved_action_consumed"]["tool_name"] == "shell"
    store.close()


def test_isolated_runner_links_discovered_artifact_to_assignment(tmp_path, monkeypatch):
    registry = ToolRegistry()
    registry.register(Tool(
        name="write_file",
        description="write",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        func=lambda path, content: f"Successfully wrote to {path}",
    ))
    tool_call = SimpleNamespace(
        id="call_artifact",
        name="write_file",
        arguments=json.dumps({"path": "outputs/report.md", "content": "done"}),
    )
    store, service, agent, context, control, _checkpoints = _context(
        tmp_path,
        [
            _response(tool_calls=[tool_call]),
            _response("报告已经生成。"),
        ],
        tools=registry,
    )
    agent.conversation_db = SimpleNamespace(db_path=tmp_path / "brain.db")
    artifact = {
        "id": "b" * 32,
        "name": "report.md",
        "mime_type": "text/markdown",
        "size": 4,
        "kind": "text",
        "description": "Created by write_file",
        "source_relative_path": "workspace/report.md",
        "storage_suffix": ".md",
        "turn_id": context.turn_id,
        "relative_path": f"workspace/assignments/{context.assignment_id}/outputs/report.md",
    }
    monkeypatch.setattr(
        "xiaomei_brain.gateway.artifacts.discover_tool_artifacts",
        lambda *args, **kwargs: [dict(artifact)],
    )

    result = IsolatedAssignmentRunner(agent, service)(context, control)

    assert result.status == "completed"
    resources = store.list_resources(context.assignment_id)
    assert any(
        item.resource_type == "artifact"
        and item.resource_key == artifact["id"]
        and item.relation == "output"
        for item in resources
    )
    store.close()


def test_isolated_runner_yields_to_realtime_conversation(tmp_path):
    store, service, agent, context, control, _checkpoints = _context(
        tmp_path,
        [_response("后台完成")],
    )
    busy = threading.Event()
    busy.set()
    result_holder = []
    runner = IsolatedAssignmentRunner(
        agent,
        service,
        realtime_busy=busy.is_set,
    )
    thread = threading.Thread(
        target=lambda: result_holder.append(runner(context, control)),
    )
    thread.start()
    time.sleep(0.1)

    assert agent.llm.clones[0].calls == []
    busy.clear()
    thread.join(1.0)

    assert result_holder[0].status == "completed"
    assert len(agent.llm.clones[0].calls) == 1
    store.close()


def test_isolated_runner_materializes_origin_attachment_for_background_work(
    tmp_path,
    monkeypatch,
):
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda person_id: person_id == "person_1",
    )
    person = AssignmentActor(ActorType.PERSON, "person_1")
    agent_actor = AssignmentActor(ActorType.AGENT, "xiaomei")
    assignment = service.offer(
        title="优化 PPT",
        objective="优化人物提供的演示文稿",
        actor=person,
        requester_person_id="person_1",
        scope_type="person",
        scope_id="person_1",
        origin_session_id="session_origin",
    )
    assignment = service.accept(assignment.id, actor=agent_actor)
    service.link_resource(
        assignment.id,
        actor=agent_actor,
        resource_type="attachment",
        resource_key="attachment_1",
        relation="input",
        metadata={
            "name": "方案.pptx",
            "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "size": 4,
            "kind": "document",
            "session_id": "session_origin",
        },
    )
    source = tmp_path / "source.pptx"
    source.write_bytes(b"pptx")
    monkeypatch.setattr(
        "xiaomei_brain.assignments.isolated_runner.Path.home",
        classmethod(lambda cls: tmp_path),
    )
    monkeypatch.setattr(
        "xiaomei_brain.gateway.attachments.restore_attachment_refs",
        lambda agent_id, session_id, attachments: ([{
            **attachments[0],
            "local_path": str(source),
            "text_content": "演示文稿正文",
        }], []),
    )
    context = AssignmentExecutionContext.capture(
        assignment,
        run_id="run_attachment",
        agent_id="xiaomei",
        resources=store.list_resources(assignment.id),
    )
    agent = FakeAgentInstance(FakeLLMTemplate([]), ToolRegistry())
    runner = IsolatedAssignmentRunner(agent, service)

    resources = runner._prepare_input_resources(context)

    metadata = resources[0]["metadata"]
    assert Path(metadata["workspace_path"]).read_bytes() == b"pptx"
    assert metadata["text_content"] == "演示文稿正文"
    assert metadata["session_id"] == "session_origin"
    store.close()


def test_two_assignment_workspaces_isolate_same_named_outputs(tmp_path, monkeypatch):
    from xiaomei_brain.tools.builtin.file_ops import write_file_tool
    from xiaomei_brain.tools.builtin.shell import shell_tool

    monkeypatch.setattr(
        "xiaomei_brain.assignments.isolated_runner.Path.home",
        classmethod(lambda cls: tmp_path),
    )
    store = AssignmentStore(tmp_path / "brain.db")
    service = AssignmentService(
        store,
        person_exists=lambda person_id: person_id == "person_1",
    )
    person = AssignmentActor(ActorType.PERSON, "person_1")
    agent_actor = AssignmentActor(ActorType.AGENT, "xiaomei")
    contexts = []
    for suffix in ("a", "b"):
        assignment = service.offer(
            title=f"并发委托 {suffix}",
            objective="生成同名文件",
            actor=person,
            requester_person_id="person_1",
            scope_type="person",
            scope_id="person_1",
            assignment_id=f"assignment_{suffix}",
        )
        assignment = service.accept(assignment.id, actor=agent_actor)
        contexts.append(AssignmentExecutionContext.capture(
            assignment,
            run_id=f"run_{suffix}",
            agent_id="xiaomei",
        ))
    runner = IsolatedAssignmentRunner(
        FakeAgentInstance(FakeLLMTemplate([]), ToolRegistry()),
        service,
    )
    bound_writers = [runner._bind_workspace_tool(write_file_tool, context) for context in contexts]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda item: item[0].execute(path="outputs/result.txt", content=item[1]),
            zip(bound_writers, ("content-a", "content-b")),
        ))

    assert all(result.startswith("Successfully wrote") for result in results)
    roots = [runner._workspace_dirs(context)[0] for context in contexts]
    assert (roots[0] / "outputs" / "result.txt").read_text(encoding="utf-8") == "content-a"
    assert (roots[1] / "outputs" / "result.txt").read_text(encoding="utf-8") == "content-b"
    assert roots[0] != roots[1]

    bound_shell = runner._bind_workspace_tool(shell_tool, contexts[0])
    cwd_output = bound_shell.execute(command="cd" if os.name == "nt" else "pwd").strip()
    assert Path(cwd_output).resolve() == (roots[0] / "work").resolve()
    store.close()


def test_only_outputs_are_promoted_as_assignment_deliverables(tmp_path, monkeypatch):
    from xiaomei_brain.tools.builtin.file_ops import write_file_tool

    monkeypatch.setattr(
        "xiaomei_brain.assignments.isolated_runner.Path.home",
        classmethod(lambda cls: tmp_path),
    )
    registry = ToolRegistry()
    registry.register(write_file_tool)
    calls = [
        SimpleNamespace(
            id="call_helper",
            name="write_file",
            arguments=json.dumps({"path": "helper.py", "content": "print('work')"}),
        ),
        SimpleNamespace(
            id="call_output",
            name="write_file",
            arguments=json.dumps({"path": "outputs/result.md", "content": "final"}),
        ),
    ]
    store, service, agent, context, control, _checkpoints = _context(
        tmp_path,
        [_response(tool_calls=calls), _response("已交付 outputs/result.md")],
        tools=registry,
    )
    agent.conversation_db = SimpleNamespace(db_path=tmp_path / "brain.db")

    result = IsolatedAssignmentRunner(agent, service)(context, control)

    assert result.status == "completed"
    resources = store.list_resources(context.assignment_id)
    helper_relations = {
        item.relation for item in resources
        if item.resource_type == "artifact" and item.metadata.get("name") == "helper.py"
    }
    output_relations = {
        item.relation for item in resources
        if item.resource_type == "artifact" and item.metadata.get("name") == "result.md"
    }
    assert helper_relations == {"process"}
    assert output_relations == {"output", "deliverable"}
    store.close()
