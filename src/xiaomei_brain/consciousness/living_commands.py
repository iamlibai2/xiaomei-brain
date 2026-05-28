"""CLI 命令函数 — 从 ConsciousLiving 中独立出来。

每个函数签名: cmd_xxx(living, args="") -> None
通过 living 访问 agent / purpose / consciousness / drive 等。
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .conscious_living import ConsciousLiving

logger = logging.getLogger(__name__)


# ── 命令函数 ────────────────────────────────────────────────────

def cmd_show_intent(living: ConsciousLiving, args: str = "") -> None:
    """显示当前 Intent"""
    logger.info("[CLI] 执行命令: intent")
    intent = living.consciousness.get_pending_intent()
    if intent:
        print(f"\n当前意图: {intent.type.value} (priority={intent.priority})", flush=True)
        print(f"内容: {intent.content}", flush=True)
    else:
        print("\n无待处理意图", flush=True)
    living._print_prompt()


def cmd_manual_fuel(living: ConsciousLiving, args: str = "") -> None:
    """手动触发加柴"""
    logger.info("[CLI] 执行命令: fuel")
    print("\n手动触发 L2 加柴...", flush=True)
    living.consciousness._last_l2_time = time.time()
    report = living.consciousness.tick_L2("manual")
    logger.info("[ConsciousLiving] L2加柴: %s", report.summary[:50])

    intent = living.consciousness.get_pending_intent()
    if intent:
        print(f"生成的意图: {intent.type.value}", flush=True)
        print(f"内容: {intent.content[:50]}", flush=True)
    else:
        print("无意图生成（LLM未返回有效意图）", flush=True)
    living._print_prompt()


def cmd_show_flame(living: ConsciousLiving, args: str = "") -> None:
    """显示火焰状态"""
    logger.info("[CLI] 执行命令: flame")
    si = living.consciousness.get_self_image()
    print("\n火焰状态:", flush=True)
    print(f"  燃烧时长: {int(si.history.consciousness_age)}秒", flush=True)
    print(f"  状态: {si.perception.agent_state}", flush=True)
    print(f"  用户空闲: {int(si.perception.user_idle_duration)}秒", flush=True)
    print(f"  能量: {si.body.energy:.2f}", flush=True)
    print(f"  累积变化: {len(living.consciousness._state_buffer)}条", flush=True)
    print(f"  上次加柴: {int(time.time() - living.consciousness._last_l2_time)}秒前", flush=True)
    living._print_prompt()


def cmd_tick_count(living: ConsciousLiving, args: str = "") -> None:
    """显示心跳计数"""
    logger.info("[CLI] 执行命令: tick")
    print(f"\nL0 心跳计数: {living.consciousness._l0_count}", flush=True)
    print(f"状态: {living.state.value}", flush=True)
    living._print_prompt()


def cmd_show_inner_thought(living: ConsciousLiving, args: str = "") -> None:
    """显示当前内在想法"""
    logger.info("[CLI] 执行命令: think")
    si = living.consciousness.get_self_image()

    print("\n内在感知:", flush=True)
    print(f"  当前想法: {si.mind.inner_thought[:100] if si.mind.inner_thought else '（无）'}", flush=True)
    print(f"  历史想法: {len(si.mind.inner_thought_history)}条", flush=True)

    if si.mind.inner_thought_history:
        print("\n最近想法:", flush=True)
        for i, thought in enumerate(si.mind.inner_thought_history[-3:]):
            print(f"  [{i}] {thought[:80]}", flush=True)

    living._print_prompt()


def cmd_show_identity(living: ConsciousLiving, args: str = "") -> None:
    """显示意识全景（完整身份分层）"""
    logger.info("[CLI] 执行命令: identity")
    si = living.consciousness.get_self_image()

    print("\n" + "=" * 50, flush=True)
    print("       意识全景", flush=True)
    print("=" * 50, flush=True)

    print("\n【L0: 先天身份】（不可变，见 Essence 底色）", flush=True)
    print(f"  名字: {si.being.name}", flush=True)
    print(f"  诞生: {si.being.birth_date}", flush=True)
    print(f"  基础性格: {si.being.personality}", flush=True)

    print("\n【L2: 社会身份】（动态变化）", flush=True)
    print(f"  关系状态: {si.being.relationship_status}", flush=True)
    print(f"  关系深度: {si.being.relationship_depth:.2f}", flush=True)
    print(f"  用户信任: {si.being.trust_level:.2f}", flush=True)

    print("\n【L4: 状态身份】（实时变化）", flush=True)
    print(f"  当前心情: {si.body.mood}", flush=True)
    print(f"  能量水平: {si.body.energy:.2f}", flush=True)
    print(f"  注意力: {si.body.attention}", flush=True)

    print("\n【我在哪】", flush=True)
    print(f"  当前环境: {si.perception.environment}", flush=True)

    print("\n【火焰状态】", flush=True)
    print(f"  燃烧时长: {int(si.history.consciousness_age)}秒 ({int(si.history.consciousness_age/3600)}小时)", flush=True)
    print(f"  Agent状态: {si.perception.agent_state}", flush=True)
    print(f"  用户空闲: {int(si.perception.user_idle_duration)}秒", flush=True)
    print(f"  记忆数量: {si.mind.memory_count}", flush=True)
    print(f"  累积变化: {len(living.consciousness._state_buffer)}条", flush=True)

    print("\n【内在感知】", flush=True)
    if si.mind.inner_thought:
        print(f"  当前想法: {si.mind.inner_thought[:100]}", flush=True)
    else:
        print(f"  当前想法: （无）", flush=True)
    print(f"  历史想法: {len(si.mind.inner_thought_history)}条", flush=True)

    if si.history.last_dream_summary:
        print("\n【最近梦境】", flush=True)
        print(f"  {si.history.last_dream_summary[:150]}", flush=True)

    print("\n" + "-" * 50, flush=True)
    living._print_prompt()


def cmd_show_drive(living: ConsciousLiving, args: str = "") -> None:
    """显示 Drive 状态"""
    logger.info("[CLI] 执行命令: drive")

    print("\n" + "=" * 50, flush=True)
    print("       Drive 状态（边缘系统）", flush=True)
    print("=" * 50, flush=True)

    print("\n【情绪状态】", flush=True)
    print(f"  类型: {living.drive.emotion.type.value}", flush=True)
    print(f"  强度: {living.drive.emotion.intensity:.2f}", flush=True)

    print("\n【激素状态】", flush=True)
    print(f"  多巴胺: {living.drive.hormone.dopamine:.2f}（动力）", flush=True)
    print(f"  血清素: {living.drive.hormone.serotonin:.2f}（满足）", flush=True)
    print(f"  皮质醇: {living.drive.hormone.cortisol:.2f}（压力）", flush=True)
    print(f"  催产素: {living.drive.hormone.oxytocin:.2f}（连接）", flush=True)

    print("\n【欲望状态】", flush=True)
    _s = living.drive.desire.survival
    _ss = living.drive.get_survival_state() if hasattr(living.drive, 'get_survival_state') else '?'
    print(f"  生存欲: {_s:.2f}（{_ss}）", flush=True)
    print(f"  归属欲: {living.drive.desire.belonging:.2f}（阈值 {living.drive.config.desire.thresholds.belonging:.2f})", flush=True)
    print(f"  认知欲: {living.drive.desire.cognition:.2f}（阈值 {living.drive.config.desire.thresholds.cognition:.2f})", flush=True)
    print(f"  成就欲: {living.drive.desire.achievement:.2f}（阈值 {living.drive.config.desire.thresholds.achievement:.2f})", flush=True)
    print(f"  表达欲: {living.drive.desire.expression:.2f}（阈值 {living.drive.config.desire.thresholds.expression:.2f})", flush=True)

    print("\n【激励状态】", flush=True)
    print(f"  动力水平: {living.drive.motivation.motivation_level:.2f}", flush=True)
    print(f"  预期奖励: {living.drive.motivation.expected_reward:.2f}", flush=True)

    print("\n【欲望驱动】", flush=True)
    actions = living.drive.check_desire_actions()
    if actions:
        for a in actions:
            print(f"  {a['type']}: 优先级 {a['priority']:.2f}", flush=True)
            print(f"    原因: {a['reason']}", flush=True)
    else:
        print("  （无触发行为）", flush=True)

    print("\n" + "-" * 50, flush=True)
    living._print_prompt()


def cmd_show_purpose(living: ConsciousLiving, args: str = "") -> None:
    """显示 Purpose 状态"""
    logger.info("[CLI] 执行命令: purpose")

    print("\n" + "=" * 50, flush=True)
    print("       Purpose 状态（前额叶层）", flush=True)
    print("=" * 50, flush=True)

    print("\n【存在意义】", flush=True)
    print(f"  我是: {living.purpose.meaning.identity}", flush=True)
    print(f"  价值观: {', '.join(living.purpose.meaning.values[:3])}", flush=True)
    print(f"  底线: {', '.join(living.purpose.meaning.constraints[:2])}", flush=True)

    current = living.purpose.get_current()
    if current and current.parent_id is None:
        print("\n【当前主目标】", flush=True)
        print(f"  {current.description}", flush=True)
        print(f"  状态: {current.status.value} | 进度: {current.progress:.0%}", flush=True)

        sub_goals = living.purpose.get_sub_goals(current.id)
        if sub_goals:
            completed = [sg for sg in sub_goals if sg.is_completed()]
            print(f"\n  【子目标】({len(completed)}/{len(sub_goals)} 已完成)", flush=True)
            for i, sg in enumerate(sub_goals, 1):
                if sg.is_completed():
                    status = "✓"
                elif sg.is_active():
                    status = "→"
                else:
                    status = "○"
                print(f"    {status} {i}. {sg.description[:35]}", flush=True)

    print("\n【待执行目标】", flush=True)
    pending = living.purpose.get_pending_goals()
    main_pending = [g for g in pending if g.parent_id is None and g.id != (current.id if current else None)]
    if main_pending:
        for i, g in enumerate(main_pending[:5], 1):
            priority = living.purpose.calculate_priority(g)
            print(f"  {i}. {g.description[:40]} (优先级 {priority:.2f})", flush=True)
    else:
        print("  （无待执行目标）", flush=True)

    completed = living.purpose.get_completed_goals()
    main_completed = [g for g in completed if g.parent_id is None]
    print(f"\n【已完成主目标】 {len(main_completed)}个", flush=True)

    print("\n" + "-" * 50, flush=True)
    living._print_prompt()


def cmd_show_plan(living: ConsciousLiving, args: str = "") -> None:
    """显示当前计划内容"""
    logger.info("[CLI] 执行命令: plan")

    if not living.purpose:
        print("\n(Purpose 未初始化)", flush=True)
        living._print_prompt()
        return

    current = living.purpose.get_current()
    if not current:
        print("\n(暂无计划)", flush=True)
        living._print_prompt()
        return

    if current.parent_id:
        parent = living.purpose.goals.get(current.parent_id)
        main_goal = parent or current
    else:
        main_goal = current

    print(f"\n\033[36m{main_goal.description}\033[0m  [{main_goal.status.value}]", flush=True)

    sub_goals = living.purpose.get_sub_goals(main_goal.id)
    if sub_goals:
        for sg in sub_goals:
            if sg.is_completed():
                icon = "\033[32m✓\033[0m"
            elif sg.id == current.id:
                icon = "\033[33m→\033[0m"
            else:
                icon = "○"
            print(f"  {icon} {sg.description}", flush=True)

    pending = living.purpose.get_pending_goals()
    main_pending = [
        g for g in pending
        if g.parent_id is None and g.id != main_goal.id
    ]
    if main_pending:
        print(f"\n\033[90m待执行 ({len(main_pending)}):\033[0m", flush=True)
        for g in main_pending[:3]:
            print(f"  ○ {g.description[:40]}", flush=True)

    living._print_prompt()


def _load_model_choices() -> list[tuple[str, str, str]]:
    """从 config.json 加载可选模型列表。

    Returns:
        [(provider, model, base_url), ...]
    """
    import json
    config_path = os.path.expanduser("~/.xiaomei-brain/config.json")
    if not os.path.exists(config_path):
        # fallback to hardcoded defaults
        from xiaomei_brain.base.config import PROVIDER_DEFAULTS
        return [
            (prov, cfg["model"], cfg["base_url"])
            for prov, cfg in PROVIDER_DEFAULTS.items()
        ]
    try:
        with open(config_path) as f:
            cfg = json.load(f)
    except Exception:
        return []

    choices: list[tuple[str, str, str]] = []
    providers = cfg.get("models", {}).get("providers", {})
    for prov_name, prov in providers.items():
        base_url = prov.get("baseUrl", "")
        for m in prov.get("models", []):
            choices.append((prov_name, m["id"], base_url))
    return choices


def cmd_model(living: ConsciousLiving, args: str = "") -> None:
    """切换模型: /model 列出可选模型，/model <序号或名称> 切换"""
    logger.info("[CLI] 执行命令: model %s", args)

    choices = _load_model_choices()

    choice = args.strip() if args else ""

    if not choice:
        current = living.agent.llm.model if living.agent.llm else "?"
        print(flush=True)
        for i, (prov, model, _) in enumerate(choices, 1):
            marker = " \033[32m← 当前\033[0m" if model == current else ""
            print(f"  \033[33m{i}.\033[0m {model} \033[90m({prov})\033[0m{marker}", flush=True)
        print(f"\n\033[90m输入 /model <序号或名称> 切换\033[0m", flush=True)
        living._print_prompt()
        return

    # 按序号选
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(choices):
            prov, model, base_url = choices[idx]
            living.agent.llm.set_model(model, base_url=base_url)
            print(f"\n\033[32m已切换 → {model} ({prov})\033[0m (无需重启)", flush=True)
            living._print_prompt()
            return
        else:
            print(f"\n\033[31m无效序号: {choice} (1-{len(choices)})\033[0m", flush=True)
            living._print_prompt()
            return
    except ValueError:
        pass

    # 按名称匹配
    matched = None
    for prov, model, base_url in choices:
        if choice.lower() in model.lower():
            matched = (prov, model, base_url)
            break
    if matched:
        prov, model, base_url = matched
        living.agent.llm.set_model(model, base_url=base_url)
        print(f"\n\033[32m已切换 → {model} ({prov})\033[0m (无需重启)", flush=True)
    else:
        print(f"\n\033[31m未找到模型: {choice}\033[0m", flush=True)
    living._print_prompt()


def cmd_tool_expand(living: ConsciousLiving, args: str = "") -> None:
    """展开工具调用详情: tool [N] 或 tool list"""
    from xiaomei_brain.agent.cli_display import expand_tool_call, list_tool_calls

    logger.info("[CLI] 执行命令: tool %s", args)

    agent = living.agent._get_agent()
    tcb = getattr(agent, 'tool_call_buffer', None)

    if not args or args.strip() == "list":
        print("\n【最近工具调用】", flush=True)
        list_tool_calls(10, tool_call_buffer=tcb)
    else:
        try:
            idx = int(args.strip())
            expand_tool_call(idx, tool_call_buffer=tcb)
        except ValueError:
            print("  用法: tool <编号> | tool list", flush=True)

    living._print_prompt()


def cmd_export(living: ConsciousLiving, session_id: str | None = None) -> None:
    """导出当前会话为 Markdown: export [session_id]"""
    logger.info("[CLI] 执行命令: export %s", session_id or "")
    if not living.agent or not living.agent.conversation_db:
        print("\n(ConversationDB 未配置)", flush=True)
        living._print_prompt()
        return

    sid = session_id or living.session_id
    md = living.agent.conversation_db.export_session(sid)

    import datetime as _dt
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.expanduser("~/.xiaomei-brain/global/exports")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"session_{sid}_{ts}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"\n[导出] {out_path}", flush=True)
    print(f"[导出] {md.count(chr(10))} 行 Markdown", flush=True)
    living._print_prompt()


def list_commands(living: ConsciousLiving, args: str = "") -> None:
    """列出所有命令"""
    print("\n\033[36m命令列表:\033[0m", flush=True)
    for name in sorted(COMMAND_REGISTRY.keys()):
        handler, _ = COMMAND_REGISTRY[name]
        doc = (handler.__doc__ or "").strip()
        print(f"  \033[33m/{name:<12}\033[0m {doc}", flush=True)
    living._print_prompt()


def cmd_user(living: ConsciousLiving, args: str = "") -> None:
    """当前身份: /user 查看, /user <id> 切换"""
    logger.info("[CLI] 执行命令: user %s", args)

    agent_core = living.agent._get_agent()
    identity_mgr = getattr(living, '_identity_mgr', None)

    name = args.strip()

    if not name:
        # 显示当前用户和可用身份
        current_name = getattr(agent_core, 'user_display_name', '未知')
        current_id = getattr(agent_core, 'user_id', '未知')
        print(f"\n当前身份: \033[36m{current_name}\033[0m (id={current_id})", flush=True)

        if identity_mgr:
            ids = identity_mgr.list_ids()
            if ids:
                print(f"\n\033[36m可用身份 ({len(ids)}个):\033[0m", flush=True)
                for iid in ids:
                    dn = identity_mgr.get_display_name(iid)
                    marker = " \033[32m← 当前\033[0m" if iid == current_id else ""
                    print(f"  {dn} ({iid}){marker}", flush=True)
            else:
                print(f"\n\033[90m(未配置身份，请在 identities.yaml 中添加)\033[0m", flush=True)
        else:
            print("\n\033[90m(IdentityManager 未初始化)\033[0m", flush=True)

        living._print_prompt()
        return

    # 切换到指定身份
    if not identity_mgr:
        print(f"\n\033[31mIdentityManager 未初始化\033[0m", flush=True)
        living._print_prompt()
        return

    identity = identity_mgr.resolve(name)
    if not identity:
        print(f"\n\033[31m身份 '{name}' 不存在。可用: {', '.join(identity_mgr.list_ids())}\033[0m", flush=True)
        living._print_prompt()
        return

    display_name = identity["name"]
    identity_id = name

    # 更新 agent 和 living 状态
    living.user_id = identity_id
    agent_core.user_id = identity_id
    agent_core.user_display_name = display_name
    # 清除上次 LLM 上下文缓存，避免 /context 显示旧用户的上下文
    agent_core._last_all_messages = []

    # 更新 SelfImage + 加载称呼记忆
    if hasattr(living, 'consciousness') and living.consciousness:
        si = living.consciousness.get_self_image()
        if si:
            si.current_user_name = display_name
            ltm = getattr(living.agent, 'longterm_memory', None)
            si.load_preferred_names(identity_id, ltm)

    print(f"\n\033[32m已切换到: {display_name}\033[0m (id={identity_id})", flush=True)
    living._print_prompt()


def cmd_pace_stats(living: ConsciousLiving, args: str = "") -> None:
    """`pace-stats` — 显示 PACE 运行统计报告"""
    agent_id = getattr(living, "_agent_id", "")
    try:
        from ..metacognition import generate_report
        report = generate_report(agent_id)
        print(f"\n{report}", flush=True)
    except Exception as e:
        print(f"\n[PACE Stats] 生成报告失败: {e}", flush=True)

    living._print_prompt()


def cmd_sessions(living: ConsciousLiving, args: str = "") -> None:
    """列出所有对话会话"""
    db = living.agent.conversation_db
    if not db:
        print("\n(ConversationDB 未配置)", flush=True)
        living._print_prompt()
        return

    ids = db.get_session_ids()
    if not ids:
        print("\n(无会话记录)", flush=True)
        living._print_prompt()
        return

    print(f"\n\033[36m会话列表 ({len(ids)}个):\033[0m", flush=True)
    for sid in ids:
        count = db.count(session_id=sid)
        recent = db.get_recent(1, session_id=sid)
        preview = ""
        if recent:
            content = recent[0].get("content", "") if isinstance(recent[0], dict) else ""
            preview = content[:50].replace("\n", " ")
        marker = " \033[32m← 当前\033[0m" if sid == living.session_id else ""
        print(f"  {sid}  ({count}条消息){marker}", flush=True)
        if preview:
            print(f"    \033[90m{preview}...\033[0m", flush=True)
    living._print_prompt()


def cmd_switch(living: ConsciousLiving, args: str = "") -> None:
    """切换到指定会话: /switch <session_id>"""
    sid = args.strip()
    if not sid:
        print("\n用法: /switch <session_id>", flush=True)
        living._print_prompt()
        return

    db = living.agent.conversation_db
    if not db:
        print("\n(ConversationDB 未配置)", flush=True)
        living._print_prompt()
        return

    ids = db.get_session_ids()
    if sid not in ids:
        print(f"\n\033[31m会话 '{sid}' 不存在\033[0m", flush=True)
        living._print_prompt()
        return

    # 通过 AttentionLayer 切换会话
    attention = getattr(living, '_attention', None)
    if attention:
        attention.switch_to(sid)
    else:
        agent = living.agent._get_agent()
        agent.session_id = sid
        agent.messages = []
    living.session_id = sid

    count = db.count(session_id=sid)
    print(f"\n\033[32m已切换到会话 {sid} ({count}条消息)\033[0m", flush=True)

    # 显示最近消息
    recent = db.get_recent(20, session_id=sid)
    if recent:
        print(f"\033[90m{'─' * 60}\033[0m", flush=True)
        for m in reversed(recent):
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "user":
                prefix = "\033[33m用户\033[0m"
            elif role == "assistant":
                prefix = f"\033[36m{living.agent.name or living._agent_id}\033[0m"
            elif role == "tool":
                prefix = "\033[90m工具\033[0m"
            else:
                prefix = role
            print(f"  {prefix}: {content}", flush=True)
        print(f"\033[90m{'─' * 60}\033[0m", flush=True)

    living._print_prompt()


# ── 命令注册表 ──────────────────────────────────────────────────

# 所有 CLI 命令，ConsciousLiving 用此表注册
COMMAND_REGISTRY: dict[str, tuple] = {
    "intent":    (cmd_show_intent,    False),  # (handler, takes_args)
    "fuel":      (cmd_manual_fuel,    False),
    "flame":     (cmd_show_flame,     False),
    "tick":      (cmd_tick_count,     False),
    "think":     (cmd_show_inner_thought, False),
    "identity":  (cmd_show_identity,  False),
    "drive":     (cmd_show_drive,     False),
    "purpose":   (cmd_show_purpose,   False),
    "plan":      (cmd_show_plan,      False),
    "model":     (cmd_model,          True),
    "tool":      (cmd_tool_expand,    True),
    "export":    (cmd_export,         True),
    "pace-stats": (cmd_pace_stats,    False),
    "sessions":  (cmd_sessions,       False),
    "switch":    (cmd_switch,         True),
    "user":      (cmd_user,           True),
}
