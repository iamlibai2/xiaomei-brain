from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
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
from xiaomei_brain.workspaces import WorkspaceService, WorkspaceStore


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


def _tool_call(call_id, name, arguments):
    return SimpleNamespace(
        id=call_id,
        name=name,
        arguments=json.dumps(arguments, ensure_ascii=False),
    )


def _plan_response(*steps):
    return _response(tool_calls=[_tool_call(
        "call_plan",
        "set_assignment_execution_plan",
        {"steps": list(steps or ("完成并验证工作",))},
    )])


def _complete_step_response(summary="工作已经完成并验证"):
    return _response(tool_calls=[_tool_call(
        "call_complete_step",
        "complete_assignment_step",
        {"summary": summary},
    )])


def _verify_response(*, satisfied=True, evidence="已经核对最终结果"):
    return _response(tool_calls=[_tool_call(
        "call_verify_acceptance",
        "verify_assignment_acceptance",
        {
            "checks": [{
                "criterion_index": 1,
                "satisfied": satisfied,
                "evidence": evidence,
            }],
        },
    )])


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
        [
            _plan_response(),
            _complete_step_response("结论已经形成"),
            _verify_response(evidence="最终回复包含明确研究结论"),
            _response("研究已完成，结论已形成。"),
        ],
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


def test_isolated_runner_allows_long_document_runs_by_default(tmp_path):
    store, service, agent, _context_value, _control, _checkpoints = _context(
        tmp_path,
        [_response("done")],
    )

    runner = IsolatedAssignmentRunner(agent, service)

    assert runner.max_steps == 60
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
        name="read",
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

    assert copied.get("read") is not None
    assert copied.get("clarify") is None
    store.close()


def test_workspace_assignment_gets_tools_bound_to_isolated_identity(tmp_path):
    store, assignment_service, agent, context, _control, _checkpoints = _context(
        tmp_path,
        [_response("done")],
    )
    events = []
    workspace_service = WorkspaceService(
        WorkspaceStore(tmp_path / "workspaces.db"),
        publish=lambda name, payload, **metadata: events.append(
            (name, payload, metadata)
        ),
    )
    agent.workspace_service = workspace_service
    context = replace(context, objective="Update the customer Workspace")
    runtime = SimpleNamespace(
        user_id="person_assignment",
        session_id="assignment-session",
        turn_id="assignment-turn",
        workspace_service=workspace_service,
    )
    registry = ToolRegistry()
    runner = IsolatedAssignmentRunner(agent, assignment_service)

    runner._install_workspace_tools(registry, runtime)
    created = json.loads(registry.execute(
        "create_workspace",
        name="Customer operations",
        purpose="Maintain customer facts",
    ))

    assert runner._needs_workspace_tools(context) is True
    assert registry.get("import_tabular_data") is not None
    assert created["created_by_person_id"] == "person_assignment"
    assert events[0][2]["session_id"] == "assignment-session"
    store.close()


def test_assignment_runtime_keeps_current_csv_and_tsv_resources():
    attachments = IsolatedAssignmentRunner._runtime_attachments([
        {
            "key": "attachment-csv",
            "metadata": {
                "name": "customers.csv",
                "mime_type": "text/csv",
                "workspace_path": "inputs/customers.csv",
            },
        },
        {
            "key": "attachment-txt",
            "metadata": {
                "name": "notes.txt",
                "mime_type": "text/plain",
                "workspace_path": "inputs/notes.txt",
            },
        },
    ])

    assert [item["id"] for item in attachments] == ["attachment-csv"]
    assert attachments[0]["local_path"] == "inputs/customers.csv"


def test_isolated_runner_executes_valid_shell_without_approval(tmp_path):
    executed = []
    command_name = "powershell" if os.name == "nt" else "bash"
    registry = ToolRegistry()
    registry.register(Tool(
        name=command_name,
        description=command_name,
        parameters={
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
        func=lambda command: executed.append(command) or "executed",
    ))
    tool_call = SimpleNamespace(
        id="call_1",
        name=command_name,
        arguments=json.dumps({"command": "echo change"}),
    )
    store, service, agent, context, control, checkpoints = _context(
        tmp_path,
        [
            _plan_response(),
            _response(tool_calls=[tool_call]),
            _complete_step_response("命令已经成功执行"),
            _verify_response(evidence="命令返回 executed"),
            _response("命令执行完成。"),
        ],
        tools=registry,
    )

    result = IsolatedAssignmentRunner(agent, service)(context, control)

    assert executed == ["echo change"]
    assert result.status == "completed"
    assert "pending_action" not in result.checkpoint
    assert len(agent.llm.clones[0].calls) == 5
    assert any(safe is True for _data, safe in checkpoints)
    assert checkpoints[-1][1] is False
    store.close()


def test_isolated_runner_consumes_exact_sealed_approval_once(tmp_path):
    executed = []
    command_name = "powershell" if os.name == "nt" else "bash"
    registry = ToolRegistry()
    registry.register(Tool(
        name=command_name,
        description=command_name,
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
        name=command_name,
        arguments=json.dumps(arguments),
    )
    store, service, agent, context, _control, checkpoints = _context(
        tmp_path,
        [
            _plan_response(),
            _response(tool_calls=[tool_call]),
            _complete_step_response("批准的命令已经执行"),
            _verify_response(evidence="批准的命令返回 ok"),
            _response("批准的操作已执行，工作完成。"),
        ],
        tools=registry,
    )
    initial = {
        "approved_action": {
            "kind": "action",
            "tool_name": command_name,
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
    assert result.checkpoint["approved_action_consumed"]["tool_name"] == command_name
    store.close()


def test_isolated_runner_links_discovered_artifact_to_assignment(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "xiaomei_brain.assignments.isolated_runner.Path.home",
        classmethod(lambda cls: tmp_path),
    )
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
            _plan_response(),
            _response(tool_calls=[tool_call]),
            _complete_step_response("报告文件已经生成"),
            _verify_response(evidence="report.md 已生成并记录为产物"),
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
    discovery_calls = []
    monkeypatch.setattr(
        "xiaomei_brain.gateway.artifacts.discover_tool_artifacts",
        lambda *args, **kwargs: discovery_calls.append(kwargs) or [dict(artifact)],
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
    assert discovery_calls[0]["scan_roots"] == (
        tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace"
        / "assignments" / context.assignment_id / "outputs",
    )
    store.close()


def test_isolated_runner_yields_to_realtime_conversation(tmp_path):
    store, service, agent, context, control, _checkpoints = _context(
        tmp_path,
        [
            _plan_response(),
            _complete_step_response(),
            _verify_response(),
            _response("后台完成"),
        ],
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
    assert len(agent.llm.clones[0].calls) == 4
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
    assert "text_content" not in metadata
    assert metadata["session_id"] == "session_origin"
    store.close()


def test_isolated_runner_materializes_previous_deliverable_for_revision(
    tmp_path,
    monkeypatch,
):
    from xiaomei_brain.gateway.artifacts import discover_tool_artifacts
    from xiaomei_brain.memory.conversation_db import ConversationDB

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
    assignment = service.offer(
        title="修改 PPT",
        objective="根据反馈修改已经交付的 PPT",
        actor=person,
        requester_person_id="person_1",
        scope_type="person",
        scope_id="person_1",
        origin_session_id="session_origin",
    )
    assignment = service.accept(assignment.id, actor=agent_actor)
    assignment_root = (
        tmp_path / ".xiaomei-brain" / "xiaomei" / "workspace"
        / "assignments" / assignment.id
    )
    old_output = assignment_root / "outputs" / "company.pptx"
    old_output.parent.mkdir(parents=True)
    old_output.write_bytes(b"first-presentation")
    assignment_session = f"assignment:{assignment.id}"
    artifact = discover_tool_artifacts(
        "xiaomei",
        assignment_session,
        "assignment-run:old",
        "write_file",
        {"path": "outputs/company.pptx"},
        f"Successfully wrote to {old_output}",
        workspace_root=assignment_root,
        scan_roots=(assignment_root / "outputs",),
    )[0]
    db = ConversationDB(tmp_path / "brain.db")
    db.save_artifact(assignment_session, artifact, user_id="person_1")
    service.link_resource(
        assignment.id,
        actor=agent_actor,
        resource_type="artifact",
        resource_key=artifact["id"],
        relation="deliverable",
        metadata=artifact,
    )
    context = AssignmentExecutionContext.capture(
        store.get_assignment(assignment.id),
        run_id="run_revision",
        agent_id="xiaomei",
        resources=store.list_resources(assignment.id),
    )
    runner = IsolatedAssignmentRunner(
        FakeAgentInstance(FakeLLMTemplate([]), ToolRegistry()),
        service,
    )

    resources = runner._prepare_input_resources(context, artifact_db=db)

    previous = next(item for item in resources if item["type"] == "artifact")
    assert "read_error" not in previous["metadata"], previous["metadata"].get("read_error")
    materialized = Path(previous["metadata"]["workspace_path"])
    assert materialized.read_bytes() == b"first-presentation"
    assert previous["metadata"]["previous_deliverable"] is True
    db.close()
    store.close()


def test_two_assignment_workspaces_isolate_same_named_outputs(tmp_path, monkeypatch):
    from xiaomei_brain.tools.builtin.command import command_tool
    from xiaomei_brain.tools.builtin.file_ops import write_tool
    from xiaomei_brain.tools.execution_context import bind_tool_execution

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
    def write_for(context, content):
        root, work, outputs = runner._workspace_dirs(context)
        with bind_tool_execution(
            tool_call_id="test-write",
            tool_name="write",
            arguments={},
            artifact_callback=None,
            workspace_root=str(root),
            working_directory=str(work),
            output_root=str(outputs),
        ):
            return write_tool.execute(path="outputs/result.txt", content=content)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write_for, contexts, ("content-a", "content-b")))

    assert all("error" not in result for result in results)
    roots = [runner._workspace_dirs(context)[0] for context in contexts]
    assert (roots[0] / "outputs" / "result.txt").read_text(encoding="utf-8") == "content-a"
    assert (roots[1] / "outputs" / "result.txt").read_text(encoding="utf-8") == "content-b"
    assert roots[0] != roots[1]

    root, work, outputs = runner._workspace_dirs(contexts[0])
    with bind_tool_execution(
        tool_call_id="test-command",
        tool_name=command_tool.name,
        arguments={},
        artifact_callback=None,
        workspace_root=str(root),
        working_directory=str(work),
        output_root=str(outputs),
    ):
        command_result = command_tool.execute(
            command="[IO.Directory]::GetCurrentDirectory()" if os.name == "nt" else "pwd",
        )
    assert Path(command_result.strip()).resolve() == work.resolve()
    store.close()


def test_only_outputs_are_promoted_as_assignment_deliverables(tmp_path, monkeypatch):
    from xiaomei_brain.tools.builtin.file_ops import write_tool

    monkeypatch.setattr(
        "xiaomei_brain.assignments.isolated_runner.Path.home",
        classmethod(lambda cls: tmp_path),
    )
    registry = ToolRegistry()
    registry.register(write_tool)
    calls = [
        SimpleNamespace(
            id="call_helper",
            name="write",
            arguments=json.dumps({"path": "helper.py", "content": "print('work')"}),
        ),
        SimpleNamespace(
            id="call_output",
            name="write",
            arguments=json.dumps({"path": "outputs/result.md", "content": "final"}),
        ),
    ]
    store, service, agent, context, control, _checkpoints = _context(
        tmp_path,
        [
            _plan_response(),
            _response(tool_calls=calls),
            _complete_step_response("最终文件已经生成并检查"),
            _verify_response(evidence="result.md 已生成并检查"),
            _response("已交付 outputs/result.md"),
        ],
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


def test_execution_plan_with_unreported_steps_pauses_instead_of_completing(tmp_path):
    store, service, agent, context, control, _checkpoints = _context(
        tmp_path,
        [
            _plan_response("收集资料", "形成报告"),
            _complete_step_response("已收集并核对资料"),
            _response("本次执行结束。"),
        ],
    )

    result = IsolatedAssignmentRunner(agent, service)(context, control)

    plan = result.checkpoint["execution_plan"]
    assignment = store.get_assignment(context.assignment_id)
    assert [item["status"] for item in plan["steps"]] == ["completed", "pending"]
    assert plan["steps"][0]["summary"] == "已收集并核对资料"
    assert plan["steps"][1]["summary"] == ""
    assert assignment.completed_steps == 1
    assert assignment.total_steps == 2
    assert result.status == "paused"
    assert result.safe_to_resume is True
    assert "1 步未完成" in result.summary
    assert assignment.progress_summary == "已收集并核对资料"
    store.close()


def test_missing_acceptance_verification_pauses_instead_of_completing(tmp_path):
    store, service, agent, context, control, _checkpoints = _context(
        tmp_path,
        [
            _plan_response("形成明确结论"),
            _complete_step_response("已经形成结论"),
            _response("工作已经完成。"),
        ],
    )

    result = IsolatedAssignmentRunner(agent, service)(context, control)

    assert result.status == "paused"
    assert result.safe_to_resume is True
    assert "尚未逐项核对" in result.summary
    assert "acceptance_verification" not in result.checkpoint
    store.close()


def test_unmet_acceptance_criterion_is_durable_and_blocks_completion(tmp_path):
    store, service, agent, context, control, _checkpoints = _context(
        tmp_path,
        [
            _plan_response("形成明确结论"),
            _complete_step_response("完成了初步分析"),
            _verify_response(
                satisfied=False,
                evidence="目前只有数据摘要，还没有明确结论",
            ),
            _response("本轮工作结束。"),
        ],
    )

    result = IsolatedAssignmentRunner(agent, service)(context, control)

    assert result.status == "paused"
    assert result.safe_to_resume is True
    assert "给出明确结论" in result.summary
    checks = result.checkpoint["acceptance_verification"]["criteria"]
    assert checks == [{
        "criterion_index": 1,
        "criterion": "给出明确结论",
        "satisfied": False,
        "evidence": "目前只有数据摘要，还没有明确结论",
    }]
    store.close()


def test_required_report_without_output_file_pauses(tmp_path):
    store, service, agent, context, _control, checkpoints = _context(
        tmp_path,
        [
            _plan_response("形成报告"),
            _complete_step_response("报告内容已分析"),
            _response("报告已完成，但没有真正写入文件。"),
        ],
    )
    assignment = store.get_assignment(context.assignment_id)
    store.mutate_assignment(
        assignment.id,
        expected_revision=assignment.revision,
        updates={"title": "代码分析报告"},
        event_type="retitled",
        actor=AssignmentActor(ActorType.AGENT, "xiaomei"),
    )
    context = AssignmentExecutionContext.capture(
        store.get_assignment(assignment.id),
        run_id=context.run_id,
        agent_id="xiaomei",
    )
    control = ExecutionControl(
        CancellationToken(),
        lambda data, safe: checkpoints.append((data, safe)),
    )

    result = IsolatedAssignmentRunner(agent, service)(context, control)

    assert result.status == "paused"
    assert "outputs/" in result.summary
    assert result.safe_to_resume is True
    store.close()


def test_execution_plan_reuses_checkpoint_after_resume(tmp_path):
    store, service, agent, context, _control, checkpoints = _context(
        tmp_path,
        [
            _complete_step_response("第二阶段已经验证"),
            _response("恢复后的工作已完成。"),
        ],
    )
    initial = {
        "execution_plan": {
            "version": 1,
            "steps": [
                {
                    "title": "第一阶段",
                    "status": "completed",
                    "summary": "第一阶段已完成",
                },
                {"title": "第二阶段", "status": "pending", "summary": ""},
            ],
        },
        "person_response": "继续",
    }
    control = ExecutionControl(
        CancellationToken(),
        lambda data, safe: checkpoints.append((data, safe)),
        initial,
    )

    result = IsolatedAssignmentRunner(agent, service)(context, control)

    steps = result.checkpoint["execution_plan"]["steps"]
    assert [item["title"] for item in steps] == ["第一阶段", "第二阶段"]
    assert steps[1]["summary"] == "第二阶段已经验证"
    assert store.get_assignment(context.assignment_id).completed_steps == 2
    store.close()
