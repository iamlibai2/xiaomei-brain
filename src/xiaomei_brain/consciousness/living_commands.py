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
    import time as _time
    logger.info("[CLI] 执行命令: intent")
    G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"
    now = _time.time()

    intent = living.consciousness.get_pending_intent()

    # Buffer stats from DB
    db_source = getattr(living.agent, 'conversation_db', None) or getattr(living.agent, 'longterm_memory', None)
    buf_total = buf_pending = buf_done = 0
    buf_recent: list = []
    if db_source:
        try:
            conn = db_source._get_conn()
            buf_total = conn.execute("SELECT COUNT(*) FROM intent_buffer").fetchone()[0]
            if buf_total > 0:
                buf_pending = conn.execute("SELECT COUNT(*) FROM intent_buffer WHERE status='pending'").fetchone()[0]
                buf_done = conn.execute("SELECT COUNT(*) FROM intent_buffer WHERE status='done'").fetchone()[0]
                buf_recent = conn.execute(
                    "SELECT type, content, priority, status, created_at FROM intent_buffer ORDER BY created_at DESC LIMIT 5"
                ).fetchall()
        except Exception:
            pass

    print(f"\n  {G}意图{R}", flush=True)

    if intent:
        print(f"  {D}待处理{R}  {V}{intent.type.value}{R}  priority={intent.priority:.2f}", flush=True)
        print(f"  {intent.content[:120]}", flush=True)
    else:
        print(f"  {D}待处理{R}  {X}无{R}", flush=True)

    if buf_total > 0:
        print(f"  {D}缓冲区{R}  {V}{buf_total}{R} 条  {X}(pending {buf_pending}, done {buf_done}){R}", flush=True)
        print(f"  {D}最近{R}", flush=True)
        for b in buf_recent:
            ago = now - b["created_at"]
            if ago < 3600:
                ts = f"{int(ago // 60)}m前"
            elif ago < 86400:
                ts = f"{int(ago // 3600)}h前"
            else:
                ts = f"{int(ago // 86400)}d前"
            status_mark = f"{G}●{R}" if b["status"] == "pending" else f"{X}○{R}"
            print(f"  {status_mark} {D}{b['type']:<8}{R} {b['content'][:60]}  {X}{ts}{R}", flush=True)
    else:
        print(f"  {D}缓冲区{R}  {X}空{R}", flush=True)

    living._print_prompt()


def cmd_manual_fuel(living: ConsciousLiving, args: str = "") -> None:
    """手动触发加柴"""
    logger.info("[CLI] 执行命令: fuel")
    G, V, D, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[0m"
    print(f"\n  {G}手动触发 L2 加柴...{R}", flush=True)
    living.consciousness._last_intent_time = time.time()
    living.consciousness._last_emerge_time = time.time()
    intent = living.consciousness.tick_L2_intent("manual")
    emergence = living.consciousness.tick_L2_emergence("manual")
    logger.info("[ConsciousLiving] L2加柴: intent=%s, emergence=%d字",
                intent.type.value if intent else "None", len(emergence))

    intent = living.consciousness.get_pending_intent()
    if intent:
        print(f"  {G}意图{R}  {V}{intent.type.value}{R}  {intent.content[:50]}", flush=True)
    else:
        print(f"  {D}无意图生成（LLM未返回有效意图）{R}", flush=True)
    living._print_prompt()


def cmd_show_flame(living: ConsciousLiving, args: str = "") -> None:
    """显示火焰状态"""
    logger.info("[CLI] 执行命令: flame")
    si = living.consciousness.get_self_image()
    G, V, D, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[0m"
    print(f"\n  {G}火焰状态{R}", flush=True)
    print(f"  {D}燃烧时长{R}      {int(si.history.consciousness_age)}s", flush=True)
    print(f"  {D}状态{R}         {si.perception.agent_state}", flush=True)
    print(f"  {D}用户空闲{R}      {int(si.perception.user_idle_duration)}s", flush=True)
    print(f"  {D}能量{R}         {si.body.energy:.2f}", flush=True)
    print(f"  {D}累积变化{R}      {len(living.consciousness._state_buffer)} 条", flush=True)
    print(f"  {D}上次意图决策{R}  {int(time.time() - living.consciousness._last_intent_time)}s 前", flush=True)
    print(f"  {D}上次意识涌现{R}  {int(time.time() - living.consciousness._last_emerge_time)}s 前", flush=True)
    living._print_prompt()


def cmd_tick_count(living: ConsciousLiving, args: str = "") -> None:
    """显示心跳计数"""
    logger.info("[CLI] 执行命令: tick")
    G, V, D, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[0m"
    print(f"\n  {G}L0 心跳{R}  {V}{living.consciousness._l0_count}{R} 次  {D}状态{R} {living.state.value}", flush=True)
    living._print_prompt()


def cmd_show_inner_thought(living: ConsciousLiving, args: str = "") -> None:
    """显示当前内在想法"""
    logger.info("[CLI] 执行命令: think")
    si = living.consciousness.get_self_image()
    G, V, D, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[0m"

    print(f"\n  {G}内在感知{R}", flush=True)
    thought = si.mind.inner_thought[:100] if si.mind.inner_thought else f"{D}(无){R}"
    print(f"  {D}当前想法{R}  {thought}", flush=True)
    narratives = si.memory.internal_narratives
    print(f"  {D}内部叙事{R}  {V}{len(narratives)}{R} 条", flush=True)

    if narratives:
        print(f"\n  {D}最近叙事{R}", flush=True)
        for i, n in enumerate(narratives[-3:]):
            print(f"  {G}[{i}]{R} {n.get('content', '')[:80]}", flush=True)

    living._print_prompt()


def cmd_show_identity(living: ConsciousLiving, args: str = "") -> None:
    """显示意识全景: /identity, /identity map <alias> <target>"""
    G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"
    args = args.strip()

    # ── /identity map <alias> <target> ─────────────────
    if args.startswith("map "):
        rest = args[4:].strip()
        parts = rest.split()
        if len(parts) < 2:
            print(f"\n  {X}用法: /identity map <alias> <target>{R}", flush=True)
            print(f"  {X}例如: /identity map ou_xxxx boshi{R}", flush=True)
            living._print_prompt()
            return
        alias, target = parts[0], parts[1]
        identity_mgr = getattr(living, '_identity_mgr', None)
        if not identity_mgr:
            print(f"\n  {V}IdentityManager 未初始化{R}", flush=True)
            living._print_prompt()
            return
        if identity_mgr.add_alias(alias, target):
            dn = identity_mgr.get_display_name(target)
            print(f"\n  {G}已添加别名{R} {alias} → {V}{target}{R} {X}({dn}){R}", flush=True)
        else:
            print(f"\n  {V}添加失败。可用主 id: {', '.join(identity_mgr.list_ids())}{R}", flush=True)
        living._print_prompt()
        return

    # ── /identity（无参数）─ 显示全景 ─────────────────
    logger.info("[CLI] 执行命令: identity")
    si = living.consciousness.get_self_image()

    print(f"\n  {V}══ 意识全景 ══{R}", flush=True)

    print(f"\n  {G}L0 · 先天身份{R}  {X}(不可变，见 Essence 底色){R}", flush=True)
    print(f"  {D}名字{R}      {si.being.name}", flush=True)
    print(f"  {D}诞生{R}      {si.being.birth_date}", flush=True)
    print(f"  {D}基础性格{R}  {si.being.personality}", flush=True)

    print(f"\n  {G}L2 · 社会身份{R}  {X}(动态变化){R}", flush=True)
    print(f"  {D}关系状态{R}  {si.being.relationship_status}", flush=True)
    print(f"  {D}关系深度{R}  {si.being.relationship_depth:.2f}", flush=True)
    print(f"  {D}用户信任{R}  {si.being.trust_level:.2f}", flush=True)

    print(f"\n  {G}L4 · 状态身份{R}  {X}(实时变化){R}", flush=True)
    print(f"  {D}心情{R}      {si.body.mood}", flush=True)
    print(f"  {D}能量{R}      {si.body.energy:.2f}", flush=True)
    print(f"  {D}注意力{R}    {si.body.attention}", flush=True)

    print(f"\n  {G}环境{R}", flush=True)
    print(f"  {D}当前位置{R}  {si.perception.environment}", flush=True)

    print(f"\n  {G}火焰状态{R}", flush=True)
    age_h = int(si.history.consciousness_age / 3600)
    print(f"  {D}燃烧时长{R}  {V}{int(si.history.consciousness_age)}s{R} ({age_h}h)", flush=True)
    print(f"  {D}Agent{R}    {si.perception.agent_state}", flush=True)
    print(f"  {D}用户空闲{R}  {int(si.perception.user_idle_duration)}s", flush=True)
    print(f"  {D}记忆数量{R}  {si.mind.memory_count}", flush=True)
    print(f"  {D}累积变化{R}  {len(living.consciousness._state_buffer)} 条", flush=True)

    print(f"\n  {G}内在感知{R}", flush=True)
    thought = si.mind.inner_thought[:100] if si.mind.inner_thought else f"{X}(无){R}"
    print(f"  {D}当前想法{R}  {thought}", flush=True)
    print(f"  {D}内部叙事{R}  {len(si.memory.internal_narratives)} 条", flush=True)

    if si.history.last_dream_summary:
        print(f"\n  {G}最近梦境{R}", flush=True)
        print(f"  {si.history.last_dream_summary[:150]}", flush=True)

    identity_mgr = getattr(living, '_identity_mgr', None)
    if identity_mgr:
        aliases = identity_mgr.list_aliases()
        if aliases:
            print(f"\n  {G}平台别名{R}", flush=True)
            for alias, target in sorted(aliases.items()):
                dn = identity_mgr.get_display_name(target)
                print(f"  {alias} → {V}{target}{R} {X}({dn}){R}", flush=True)

    print(f"\n  {X}──{R}", flush=True)
    living._print_prompt()


def cmd_show_drive(living: ConsciousLiving, args: str = "") -> None:
    """显示 Drive 状态"""
    logger.info("[CLI] 执行命令: drive")
    G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"

    print(f"\n  {V}══ Drive · 边缘系统 ══{R}", flush=True)

    print(f"\n  {G}情绪{R}", flush=True)
    e = living.drive.emotion
    if e.is_empty():
        print(f"  {D}平静{R}", flush=True)
    else:
        for name, intensity in sorted(e.emotions.items(), key=lambda x: x[1], reverse=True):
            print(f"  {name}  {V}{intensity:.2f}{R}", flush=True)

    print(f"\n  {G}激素{R}", flush=True)
    print(f"  {D}多巴胺{R}  {living.drive.hormone.dopamine:.2f}  {X}(动力){R}", flush=True)
    print(f"  {D}血清素{R}  {living.drive.hormone.serotonin:.2f}  {X}(满足){R}", flush=True)
    print(f"  {D}皮质醇{R}  {living.drive.hormone.cortisol:.2f}  {X}(压力){R}", flush=True)
    print(f"  {D}催产素{R}  {living.drive.hormone.oxytocin:.2f}  {X}(连接){R}", flush=True)

    print(f"\n  {G}欲望{R}", flush=True)
    _s = living.drive.desire.survival
    _ss = living.drive.get_survival_state() if hasattr(living.drive, 'get_survival_state') else '?'
    cfg = living.drive.config.desire.thresholds
    print(f"  {D}生存欲{R}  {_s:.2f}  {X}({_ss}){R}", flush=True)
    print(f"  {D}归属欲{R}  {living.drive.desire.belonging:.2f}  {X}>={cfg.belonging:.2f}{R}", flush=True)
    print(f"  {D}认知欲{R}  {living.drive.desire.cognition:.2f}  {X}>={cfg.cognition:.2f}{R}", flush=True)
    print(f"  {D}成就欲{R}  {living.drive.desire.achievement:.2f}  {X}>={cfg.achievement:.2f}{R}", flush=True)
    print(f"  {D}表达欲{R}  {living.drive.desire.expression:.2f}  {X}>={cfg.expression:.2f}{R}", flush=True)

    print(f"\n  {G}激励{R}", flush=True)
    print(f"  {D}动力水平{R}  {living.drive.motivation.motivation_level:.2f}", flush=True)
    print(f"  {D}预期奖励{R}  {living.drive.motivation.expected_reward:.2f}", flush=True)

    print(f"\n  {G}触发的行为{R}", flush=True)
    actions = living.drive.check_desire_actions()
    if actions:
        for a in actions:
            print(f"  {V}{a['type']}{R}  priority={a['priority']:.2f}", flush=True)
            print(f"  {X}{a['reason']}{R}", flush=True)
    else:
        print(f"  {D}(无触发行为){R}", flush=True)

    print(f"\n  {X}──{R}", flush=True)
    living._print_prompt()


def cmd_show_purpose(living: ConsciousLiving, args: str = "") -> None:
    """显示 Purpose 状态"""
    logger.info("[CLI] 执行命令: purpose")
    G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"

    print(f"\n  {V}══ Purpose · 前额叶层 ══{R}", flush=True)

    print(f"\n  {G}存在意义{R}", flush=True)
    print(f"  {D}存在意义{R}  {living.purpose.meaning}", flush=True)

    current = living.purpose.get_current()
    if current and current.parent_id is None:
        print(f"\n  {G}当前主目标{R}", flush=True)
        print(f"  {current.description}", flush=True)
        print(f"  {D}状态{R} {current.status.value}  {D}进度{R} {V}{current.progress:.0%}{R}", flush=True)

        sub_goals = living.purpose.get_sub_goals(current.id)
        if sub_goals:
            completed = [sg for sg in sub_goals if sg.is_completed()]
            print(f"\n    {G}子目标{R}  {V}{len(completed)}{R}/{len(sub_goals)} 已完成", flush=True)
            for i, sg in enumerate(sub_goals, 1):
                if sg.is_completed():
                    status = f"{G}✓{R}"
                elif sg.is_active():
                    status = f"{V}→{R}"
                else:
                    status = f"{X}○{R}"
                print(f"    {status} {i}. {sg.description[:35]}", flush=True)

    print(f"\n  {G}待执行目标{R}", flush=True)
    pending = living.purpose.get_pending_goals()
    main_pending = [g for g in pending if g.parent_id is None and g.id != (current.id if current else None)]
    if main_pending:
        for i, g in enumerate(main_pending[:5], 1):
            priority = living.purpose.calculate_priority(g)
            print(f"  {V}{i}.{R} {g.description[:40]}  {X}(优先级 {priority:.2f}){R}", flush=True)
    else:
        print(f"  {X}(无待执行目标){R}", flush=True)

    completed = living.purpose.get_completed_goals()
    main_completed = [g for g in completed if g.parent_id is None]
    print(f"\n  {G}已完成主目标{R}  {V}{len(main_completed)}{R} 个", flush=True)

    print(f"\n  {X}──{R}", flush=True)
    living._print_prompt()


def cmd_show_plan(living: ConsciousLiving, args: str = "") -> None:
    """显示当前计划内容"""
    logger.info("[CLI] 执行命令: plan")
    G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"

    if not living.purpose:
        print(f"\n  {D}Purpose 未初始化{R}", flush=True)
        living._print_prompt()
        return

    current = living.purpose.get_current()
    if not current:
        print(f"\n  {D}暂无计划{R}", flush=True)
        living._print_prompt()
        return

    if current.parent_id:
        parent = living.purpose.goals.get(current.parent_id)
        main_goal = parent or current
    else:
        main_goal = current

    print(f"\n  {G}{main_goal.description}{R}  {X}[{main_goal.status.value}]{R}", flush=True)

    sub_goals = living.purpose.get_sub_goals(main_goal.id)
    if sub_goals:
        for sg in sub_goals:
            if sg.is_completed():
                icon = f"{G}✓{R}"
            elif sg.id == current.id:
                icon = f"{V}→{R}"
            else:
                icon = f"{X}○{R}"
            print(f"  {icon} {sg.description}", flush=True)

    pending = living.purpose.get_pending_goals()
    main_pending = [
        g for g in pending
        if g.parent_id is None and g.id != main_goal.id
    ]
    if main_pending:
        print(f"\n  {X}待执行 ({len(main_pending)}):{R}", flush=True)
        for g in main_pending[:3]:
            print(f"  {X}○{R} {g.description[:40]}", flush=True)

    living._print_prompt()


def _load_model_choices() -> list[tuple[str, str, str, str]]:
    """从 config.json 加载可选模型列表。

    Returns:
        [(provider, model, base_url, api_key), ...]
    """
    import json
    config_path = os.path.expanduser("~/.xiaomei-brain/config.json")
    if not os.path.exists(config_path):
        # fallback to hardcoded defaults
        from xiaomei_brain.base.config import PROVIDER_DEFAULTS
        return [
            (prov, cfg["model"], cfg["base_url"], "")
            for prov, cfg in PROVIDER_DEFAULTS.items()
        ]
    try:
        with open(config_path) as f:
            cfg = json.load(f)
    except Exception:
        return []

    choices: list[tuple[str, str, str, str]] = []
    providers = cfg.get("models", {}).get("providers", {})
    for prov_name, prov in providers.items():
        base_url = prov.get("baseUrl", "")
        api_key = prov.get("apiKey", "")
        for m in prov.get("models", []):
            choices.append((prov_name, m["id"], base_url, api_key))
    return choices


def _persist_model_choice(agent_id: str, provider: str, model: str) -> None:
    """将模型选择写回 config.json，重启后保持。"""
    import json
    config_path = os.path.expanduser("~/.xiaomei-brain/config.json")
    if not os.path.exists(config_path):
        return
    try:
        with open(config_path) as f:
            cfg = json.load(f)
    except Exception:
        return

    agent_list = cfg.get("agents", {}).get("list", [])
    for entry in agent_list:
        if entry.get("id") == agent_id:
            entry.setdefault("model", {})["primary"] = f"{provider}/{model}"
            break
    else:
        return

    try:
        with open(config_path, "w") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
            f.write("\n")
        logger.info("[CLI] 模型选择已持久化: %s/%s → %s", provider, model, config_path)
    except Exception as e:
        logger.warning("[CLI] 持久化模型选择失败: %s", e)


def cmd_model(living: ConsciousLiving, args: str = "") -> None:
    """切换模型: /model 列出可选模型，/model <序号或名称> 切换"""
    logger.info("[CLI] 执行命令: model %s", args)
    G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"

    choices = _load_model_choices()

    choice = args.strip() if args else ""

    if not choice:
        llm = living.agent.llm
        current = llm.model if llm else "?"
        current_provider = llm.provider if llm else "?"
        print(flush=True)
        for i, (prov, model, _, _) in enumerate(choices, 1):
            marker = f" {G}← 当前{R}" if model == current else ""
            print(f"  {V}{i}.{R} {model} {X}({prov}){R}{marker}", flush=True)
        print(f"\n  {X}输入 /model <序号或名称> 切换{R}", flush=True)
        living._print_prompt()
        return

    def _apply_switch(llm, prov: str, model: str, base_url: str, api_key: str) -> None:
        """Switches provider profile if crossing providers, otherwise just updates model."""
        current_provider = getattr(llm, 'provider', None)
        if current_provider and current_provider != prov:
            # 跨 provider 切换：更换整个 profile + transport + api_key
            llm.set_provider(prov, model=model)
            # set_provider 只从环境变量解析 api_key，config.json 的 key 需额外设置
            if api_key:
                llm.set_model(model, api_key=api_key)
        else:
            llm.set_model(model, base_url=base_url, api_key=api_key)

    # 按序号选
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(choices):
            prov, model, base_url, api_key = choices[idx]
            _apply_switch(living.agent.llm, prov, model, base_url, api_key)
            _persist_model_choice(living._agent_id, prov, model)
            print(f"\n  {G}已切换 → {model} ({prov}){R}  {X}(无需重启){R}", flush=True)
            living._print_prompt()
            return
        else:
            print(f"\n  {V}无效序号: {choice}{R}  {X}(1-{len(choices)}){R}", flush=True)
            living._print_prompt()
            return
    except ValueError:
        pass

    # 按名称匹配
    matched = None
    for prov, model, base_url, api_key in choices:
        if choice.lower() in model.lower():
            matched = (prov, model, base_url, api_key)
            break
    if matched:
        prov, model, base_url, api_key = matched
        _apply_switch(living.agent.llm, prov, model, base_url, api_key)
        _persist_model_choice(living._agent_id, prov, model)
        print(f"\n  {G}已切换 → {model} ({prov}){R}  {X}(无需重启){R}", flush=True)
    else:
        print(f"\n  {V}未找到模型: {choice}{R}", flush=True)
    living._print_prompt()


def cmd_tool_expand(living: ConsciousLiving, args: str = "") -> None:
    """展开工具调用详情: tool [N] 或 tool list"""
    from xiaomei_brain.agent.cli_display import expand_tool_call, list_tool_calls

    logger.info("[CLI] 执行命令: tool %s", args)
    G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"

    agent = living.agent._get_agent()
    tcb = getattr(agent, 'tool_call_buffer', None)

    if not args or args.strip() == "list":
        print(f"\n  {G}最近工具调用{R}", flush=True)
        list_tool_calls(10, tool_call_buffer=tcb)
    else:
        try:
            idx = int(args.strip())
            expand_tool_call(idx, tool_call_buffer=tcb)
        except ValueError:
            print(f"  {X}用法: /tool <编号> | /tool list{R}", flush=True)

    living._print_prompt()


def cmd_export(living: ConsciousLiving, session_id: str | None = None) -> None:
    """导出当前会话为 Markdown: export [session_id]"""
    logger.info("[CLI] 执行命令: export %s", session_id or "")
    G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"

    if not living.agent or not living.agent.conversation_db:
        print(f"\n  {D}ConversationDB 未配置{R}", flush=True)
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

    print(f"\n  {G}导出完成{R}", flush=True)
    print(f"  {D}路径{R}  {out_path}", flush=True)
    print(f"  {D}内容{R}  {V}{md.count(chr(10))}{R} 行 Markdown", flush=True)
    living._print_prompt()


def list_commands(living: ConsciousLiving, args: str = "") -> None:
    """列出所有命令"""
    G, D, R = "\033[32m", "\033[38;5;73m", "\033[0m"
    for name in sorted(COMMAND_REGISTRY.keys()):
        handler, _ = COMMAND_REGISTRY[name]
        doc = (handler.__doc__ or "").strip()
        print(f"  {G}/{name:<12}{R} {D}{doc}{R}", flush=True)
    living._print_prompt()


def cmd_user(living: ConsciousLiving, args: str = "") -> None:
    """当前身份: /user 查看, /user <id> 切换"""
    logger.info("[CLI] 执行命令: user %s", args)

    G = "\033[32m"
    D = "\033[38;5;73m"
    R = "\033[0m"

    agent_core = living.agent._get_agent()
    identity_mgr = getattr(living, '_identity_mgr', None)

    name = args.strip()

    if not name:
        # 显示当前用户和可用身份
        current_name = getattr(agent_core, 'user_display_name', '未知')
        current_id = getattr(agent_core, 'user_id', '未知')
        print(f"\n  \033[32m当前身份\033[0m  \033[38;5;203m{current_name}\033[0m  \033[90m(id={current_id})\033[0m", flush=True)

        if identity_mgr:
            ids = identity_mgr.list_ids()
            if ids:
                print(f"\n  \033[32m可用身份\033[0m \033[90m({len(ids)}个)\033[0m", flush=True)
                for iid in ids:
                    dn = identity_mgr.get_display_name(iid)
                    marker = " \033[32m← 当前\033[0m" if iid == current_id else ""
                    print(f"    {dn} {D}{iid}{R}{marker}", flush=True)
            else:
                print(f"\n  \033[90m(未配置身份，请在 identities.yaml 中添加)\033[0m", flush=True)
        else:
            print(f"\n  \033[90m(IdentityManager 未初始化)\033[0m", flush=True)

        living._print_prompt()
        return

    # 切换到指定身份
    if not identity_mgr:
        print(f"\n  \033[38;5;203mIdentityManager 未初始化\033[0m", flush=True)
        living._print_prompt()
        return

    identity = identity_mgr.resolve(name)
    if not identity:
        print(f"\n  \033[38;5;203m身份 '{name}' 不存在\033[0m  \033[90m可用: {', '.join(identity_mgr.list_ids())}\033[0m", flush=True)
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
            si.current_user_id = identity_id
            identity_mgr = getattr(living, '_identity_mgr', None)
            if identity_mgr:
                si.current_user_relation = identity_mgr.get_relation(identity_id)
            ltm = getattr(living.agent, 'longterm_memory', None)
            si.load_preferred_names(identity_id, ltm)

    print(f"\n  \033[32m已切换到\033[0m  \033[38;5;203m{display_name}\033[0m  \033[90m(id={identity_id})\033[0m", flush=True)
    living._print_prompt()


def cmd_pace_stats(living: ConsciousLiving, args: str = "") -> None:
    """`pace-stats` — 显示 PACE 运行统计报告"""
    G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"
    agent_id = getattr(living, "_agent_id", "")
    try:
        from ..metacognition import generate_report
        report = generate_report(agent_id)
        print(f"\n  {G}PACE 运行统计{R}", flush=True)
        print(report, flush=True)
    except Exception as e:
        print(f"\n  {V}PACE Stats 生成报告失败: {e}{R}", flush=True)

    living._print_prompt()


def cmd_sessions(living: ConsciousLiving, args: str = "") -> None:
    """列出所有对话会话"""
    G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"
    db = living.agent.conversation_db
    if not db:
        print(f"\n  {D}ConversationDB 未配置{R}", flush=True)
        living._print_prompt()
        return

    ids = db.get_session_ids()
    if not ids:
        print(f"\n  {D}无会话记录{R}", flush=True)
        living._print_prompt()
        return

    print(f"\n  {G}会话列表{R}  {V}{len(ids)}{R} 个", flush=True)
    for sid in ids:
        count = db.count(session_id=sid)
        recent = db.get_recent(1, session_id=sid)
        preview = ""
        if recent:
            content = recent[0].get("content", "") if isinstance(recent[0], dict) else ""
            preview = content[:50].replace("\n", " ")
        marker = f" {G}← 当前{R}" if sid == living.session_id else ""
        print(f"  {D}{sid}{R}  {V}{count}{R} 条消息{marker}", flush=True)
        if preview:
            print(f"    {X}{preview}...{R}", flush=True)
    living._print_prompt()


def cmd_switch(living: ConsciousLiving, args: str = "") -> None:
    """切换到指定会话: /switch <session_id>"""
    G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"
    sid = args.strip()
    if not sid:
        print(f"\n  {X}用法: /switch <session_id>{R}", flush=True)
        living._print_prompt()
        return

    db = living.agent.conversation_db
    if not db:
        print(f"\n  {D}ConversationDB 未配置{R}", flush=True)
        living._print_prompt()
        return

    ids = db.get_session_ids()
    if sid not in ids:
        print(f"\n  {V}会话 '{sid}' 不存在{R}", flush=True)
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
    print(f"\n  {G}已切换到会话{R} {D}{sid}{R}  {V}{count}{R} 条消息", flush=True)

    # 显示最近消息
    recent = db.get_recent(20, session_id=sid)
    if recent:
        print(f"  {X}{'─' * 60}{R}", flush=True)
        for m in reversed(recent):
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "user":
                prefix = f"{G}用户{R}"
            elif role == "assistant":
                prefix = f"{V}{living.agent.name or living._agent_id}{R}"
            elif role == "tool":
                prefix = f"{X}工具{R}"
            else:
                prefix = role
            print(f"  {prefix}: {content}", flush=True)
        print(f"  {X}{'─' * 60}{R}", flush=True)

    living._print_prompt()


# ── Body 感官命令 ──────────────────────────────────────────────

def cmd_eyes(living, args: str) -> None:
    """显示眼睛状态。"""
    G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"
    body = getattr(living, 'body', None)
    if not body:
        print(f"\n  {V}Body 层未加载{R}", flush=True)
        return
    eyes = body.eyes
    if not eyes:
        print(f"\n  {V}眼睛未注册{R}", flush=True)
        return
    available = eyes.is_available()
    status = f"{G}在线{R}" if available else f"{V}离线{R}"
    print(f"\n  {G}眼睛{R} {D}[{eyes.name}]{R} {status}", flush=True)
    if available:
        faces = eyes.recognize_faces()
        face_str = ", ".join(f.get("face_id", "?") for f in faces) if faces else f"{X}无人{R}"
        print(f"  {D}人脸{R}  {face_str}", flush=True)


def cmd_ears(living, args: str) -> None:
    """显示耳朵状态。"""
    G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"
    body = getattr(living, 'body', None)
    if not body:
        print(f"\n  {V}Body 层未加载{R}", flush=True)
        return
    ears = body.ears
    if not ears:
        print(f"\n  {V}耳朵未注册{R}", flush=True)
        return
    available = ears.is_available()
    status = f"{G}在线{R}" if available else f"{V}离线{R}"
    print(f"\n  {G}耳朵{R} {D}[{ears.name}]{R} {status}", flush=True)
    if available:
        voice_id = ears.recognize_voice()
        print(f"  {D}声纹{R}  {voice_id or f'{X}未识别{R}'}", flush=True)


def cmd_see(living, args: str) -> None:
    """看当前场景。"""
    G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"
    body = getattr(living, 'body', None)
    if not body or not body.eyes:
        print(f"\n  {V}眼睛不可用{R}", flush=True)
        return
    if not body.eyes.is_available():
        print(f"\n  {V}眼睛离线{R}", flush=True)
        return
    scene = body.eyes.see(args or "描述这个画面")
    faces = body.eyes.recognize_faces()
    print(f"\n  {G}场景{R}  {scene or f'{X}无{R}'}", flush=True)
    if faces:
        identity_mgr = getattr(living, '_identity_mgr', None)
        for f in faces:
            fid = f.get("face_id", "")
            name = identity_mgr.get_display_name(fid) if identity_mgr else ""
            print(f"  {D}人脸{R}  {name or fid}", flush=True)
    print(flush=True)


def cmd_hear(living, args: str) -> None:
    """听周围声音。"""
    G, V, D, X, R = "\033[32m", "\033[38;5;203m", "\033[38;5;73m", "\033[90m", "\033[0m"
    body = getattr(living, 'body', None)
    if not body or not body.ears:
        print(f"\n  {V}耳朵不可用{R}", flush=True)
        return
    if not body.ears.is_available():
        print(f"\n  {V}耳朵离线{R}", flush=True)
        return
    result = body.ears.listen(args or "分析音频")
    voice_id = body.ears.recognize_voice()
    print(f"\n  {G}音频{R}  {result or f'{X}无{R}'}", flush=True)
    print(f"  {D}声纹{R}  {voice_id or f'{X}未识别{R}'}", flush=True)


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
    "eyes":      (cmd_eyes,           False),
    "ears":      (cmd_ears,           False),
    "see":       (cmd_see,            True),
    "hear":      (cmd_hear,           True),
}
