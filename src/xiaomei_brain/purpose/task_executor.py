"""TaskExecutor - 目标执行相关业务逻辑

职责（纯逻辑，不做 I/O）：
- 确认信息构建（是否需要用户选择）
- 目标进度更新
- LLM 上下文构建
- 用户确认输入解析

与 conscious_living 的关系：
- 本模块只做业务逻辑计算，不 print，不直接控制状态流转
- conscious_living 调用本模块获取结果，然后处理 I/O 和状态流转
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def build_confirm_info(sub_goal, intent_result) -> dict | None:
    """
    构建确认信息（两 Tier）

    Tier 1: LLM 结构化输出（有具体选项）
    Tier 2: 默认对所有任务的第一个子目标展示确认框

    Returns:
        {"goal_id": ..., "question": ..., "options": [...], "default_answer": ...} | None
    """
    # Tier 1: LLM 结构化输出
    if intent_result.confirm_question and intent_result.confirm_options:
        return {
            "goal_id": sub_goal.id,
            "question": intent_result.confirm_question,
            "options": intent_result.confirm_options,
            "default_answer": intent_result.confirm_options[0],
        }

    # Tier 2: 默认确认第一个子目标（任何任务都需要讨论确认）
    return {
        "goal_id": sub_goal.id,
        "question": f"「{sub_goal.description[:40]}」—— 开始执行？",
        "options": ["开始执行", "跳过这个"],
        "default_answer": "开始执行",
    }


def build_intent_context(purpose, intent_result, chosen_by_user: bool = False) -> str:
    """构建 LLM 上下文（当前子目标 + 全局进度）

    核心原则：Agent 只知道当前执行的子目标，不暴露完整目标树
    MiniMax 限制：只能合并到 system prompt（不单独发 system message）

    Args:
        purpose: PurposeEngine 实例
        intent_result: IntentResult
        chosen_by_user: True 表示用户从"继续"列表中明确选择了此任务

    Returns:
        str: 上下文文本，空字符串表示无特殊上下文
    """
    if not intent_result:
        return ""

    # CHAT 闲聊：返回回应风格建议
    if intent_result.is_chat() and intent_result.response_guidance:
        lines = [
            "【闲聊回应建议】",
            intent_result.response_guidance,
            "",
            "（按上述风格自然回应即可，不要生硬）",
        ]
        return "\n".join(lines)

    # CLARIFICATION / QUERY：也要推进目标，告知当前子目标
    if intent_result.is_task():
        pass  # 继续往下走，提取子目标
    elif purpose and purpose.get_current():
        # 有当前活跃子目标，告知 LLM 回答后推进目标
        active = purpose.get_current()
        if active:
            lines = [
                f"【当前任务】{active.description}",
                "回答用户问题后，请在回复末尾加上进度块：",
                "",
                "<PROGRESS>",
                '{"status": "completed"}  ← 如果当前子目标已完成',
                '{"status": "in_progress"}  ← 如果当前子目标还需继续（如只做了反问/澄清）',
                "</PROGRESS>",
                "",
                "（这会使系统自动推进到下一个子目标或保持当前）",
            ]
            return "\n".join(lines)
    # 无活跃目标时，clarification/query 不需要特殊上下文
    if not intent_result.is_task():
        return ""

    # 找到当前正在执行的子目标
    current = purpose.get_current()
    if not current:
        return ""

    # 当前是子目标（有 parent_id），直接用它
    if current.parent_id:
        active_sub = current
        main_goal = purpose.goals.get(current.parent_id)
    else:
        # 当前是主目标，找它的活跃子目标
        active_sub = None
        sub_goals = purpose.get_sub_goals(current.id)
        for sg in sub_goals:
            if sg.is_active():
                active_sub = sg
                break
        main_goal = current

    if not active_sub:
        active_sub = current

    sub_goals = purpose.get_sub_goals(main_goal.id) if main_goal else []
    completed_subs = [sg for sg in sub_goals if sg.is_completed()]

    context_lines = []

    # 用户明确选择的任务：告知 Agent 不要再问选择
    if chosen_by_user:
        context_lines.append("【重要】用户已经从多个任务中明确选择了继续这个任务，不要再问用户选择。直接推进即可。")
        context_lines.append("")

    context_lines.extend([
        f"【当前任务】只执行这一个子目标，不要做其他事情：",
        f"「{active_sub.description}」",
        "",
        f"进度：{len(completed_subs)}/{len(sub_goals)} 子目标已完成",
    ])

    # 用户已确认的选择：直接使用，不要再问用户
    confirmed_answer = active_sub.metadata.get("answer")
    if confirmed_answer:
        context_lines.append("")
        context_lines.append(f"【已确认】用户已选择：{confirmed_answer}")
        context_lines.append("直接使用上述选择执行，不要再询问用户。")

    # 子目标列表（已完成标记，方便 Agent 了解全局）
    if sub_goals:
        context_lines.append("")
        context_lines.append("【全局进度】")
        for sg in sub_goals:
            status_mark = "✓" if sg.is_completed() else "○"
            active_mark = " →进行中" if sg.id == active_sub.id else ""
            context_lines.append(f"  {status_mark}{active_mark} {sg.description[:40]}")

    # 进度输出要求（XML 格式，和 MEMORY 块同级）
    context_lines.append("")
    context_lines.append(
        "【重要】先正常回复用户，回复完成后，再在末尾输出进度块：\n"
        "\n"
        "<PROGRESS>\n"
        "{\"status\": \"completed\"}  ← 当前子目标已完成时\n"
        "</PROGRESS>\n"
        "\n"
        "或\n"
        "\n"
        "<PROGRESS>\n"
        "{\"status\": \"in_progress\"}  ← 当前子目标未完成时（如只做了反问/澄清）\n"
        "</PROGRESS>\n"
        "\n"
        "如果用户输入中没有值得推进的内容，输出：无需推进"
    )

    return "\n".join(context_lines)


def update_goal_progress(purpose, drive, status: str) -> Optional[str]:
    """更新目标进度

    根据 PROGRESS 标签更新目标状态。
    由 conscious_living 在 LLM 对话完成后调用，返回状态描述供上层决定是否输出。

    Args:
        purpose: PurposeEngine 实例
        drive: DriveEngine 实例
        status: "completed" 或 "in_progress"

    Returns:
        Optional[str]: 状态描述文案（供上层 print/渲染），None 表示无变更
    """
    if not purpose:
        return None

    current = purpose.get_current()
    logger.info(
        "[Progress Debug] get_current() id=%s desc=%s parent_id=%s depth=%d status=%s",
        current.id[:8] if current else "None",
        current.description[:40] if current else "None",
        current.parent_id[:8] if current and current.parent_id else "None",
        current.depth if current else -1,
        current.status.value if current else "None",
    )
    if not current:
        return None

    # 如果 current 有 parent_id，说明当前执行的是子目标层级
    # active_sub = current 本身，siblings 从同一个 parent 的 children 中找
    if current.parent_id:
        # 当前是一个子目标
        active_sub = current
        # 获取所有兄弟子目标（同parent的children）
        siblings = purpose.get_sub_goals(current.parent_id)
        logger.info(
            "[Progress Debug] sub_goal mode: active=%s siblings=%d list=%s",
            active_sub.description[:30],
            len(siblings),
            [(sg.id[:8], sg.description[:30], sg.status.value) for sg in siblings],
        )
    else:
        # 当前是主目标，找它的 children
        sub_goals = purpose.get_sub_goals(current.id)
        logger.info(
            "[Progress Debug] main_goal mode: sub_goals=%d list=%s",
            len(sub_goals),
            [(sg.id[:8], sg.description[:30], sg.status.value) for sg in sub_goals],
        )
        active_sub = None
        for sg in sub_goals:
            if sg.is_active():
                active_sub = sg
                break

        if not active_sub:
            # 没有活跃子目标，激活第一个 pending
            pending_subs = [sg for sg in sub_goals if sg.is_pending()]
            if pending_subs:
                purpose.set_current(pending_subs[0].id)
                logger.info("[Progress] 激活第一个子目标: %s", pending_subs[0].description[:30])
            return None
        siblings = sub_goals

    if status == "completed":
        # 完成当前子目标（不触发 get_next 切换）
        purpose.complete_goal(active_sub.id)

        # 切换到下一个子目标
        next_sub = purpose.get_next_sibling(active_sub.id)
        status_msg = None
        if next_sub:
            purpose.set_current(next_sub.id)
            logger.info("[Progress] 子目标完成，切换到下一个: %s", next_sub.description[:30])
            status_msg = f"[进度] 子目标完成，下一个: {next_sub.description[:40]}"

        # 检查主目标是否完成（所有 siblings 完成）
        completed_subs = [sg for sg in siblings if sg.is_completed()]
        if len(completed_subs) == len(siblings):
            # 找主目标：如果 current 是子目标，parent 是主目标；否则 current 是主目标
            main_goal_id = current.parent_id if current.parent_id else current.id
            main_goal = purpose.goals.get(main_goal_id)
            if main_goal:
                main_goal.complete()
                logger.info("[Progress] 主目标完成: %s", main_goal.description[:30])
                status_msg = f"[目标] 主目标已完成: {main_goal.description[:40]}"

        return status_msg

    elif status == "in_progress":
        purpose.update_progress(active_sub.id, 0.1)
        logger.debug("[Progress] 子目标推进: %s (+10%%)", active_sub.description[:30])

    return None


def parse_confirmation_input(pending_confirm: dict, user_input: str) -> dict:
    """解析用户确认输入

    纯解析，不做 side effect。
    由 conscious_living 调用，根据返回的 action 决定后续流程。

    Returns:
        {"action": "proceed" | "skip" | "retry",
         "answer": str,
         "goal_id": str}
      - proceed: 正常执行（answer 是用户选择的选项）
      - skip: 跳过当前子目标（answer 固定为 "跳过这个"）
      - retry: 需要重试（输入无效/选择了自定义输入）
    """
    options = pending_confirm["options"]
    goal_id = pending_confirm["goal_id"]
    answer = ""

    inp = user_input.strip()
    if inp.isdigit():
        idx = int(inp)
        if idx == 0:
            # 自定义输入，需要下一次输入
            return {"action": "retry", "answer": "", "goal_id": goal_id}
        elif 1 <= idx <= len(options):
            answer = options[idx - 1]
        else:
            return {"action": "retry", "answer": "", "goal_id": goal_id}
    else:
        # 取消/放弃关键词：用户想退出当前任务
        cancel_keywords = ["不做", "放弃", "取消", "算了", "不要", "不做这个"]
        if any(kw in inp for kw in cancel_keywords):
            return {"action": "cancel", "answer": inp, "goal_id": goal_id}

        # 直接输入文字，匹配选项或作为自定义值
        matched = False
        for opt in options:
            if opt.lower() in inp.lower():
                answer = opt
                matched = True
                break
        if not matched:
            # 自定义值
            answer = inp

    if answer == "跳过这个":
        return {"action": "skip", "answer": answer, "goal_id": goal_id}

    return {"action": "proceed", "answer": answer, "goal_id": goal_id}


def apply_skip(purpose, goal_id: str) -> dict:
    """处理"跳过"选择

    Returns:
        {"status_msg": str | None, "new_goal_id": str | None}
      - status_msg: 状态变更文案（供上层 print）
      - new_goal_id: 新激活的子目标 id（None 表示无更多子目标）
    """
    goal = purpose.goals.get(goal_id)
    if not goal:
        return {"status_msg": None, "new_goal_id": None}

    purpose.goals[goal.id].complete()
    next_sub = purpose.get_next_sibling(goal.id)
    if next_sub:
        purpose.set_current(next_sub.id)
        return {
            "status_msg": f"[目标] 跳过，激活下一个: {next_sub.description[:40]}",
            "new_goal_id": next_sub.id,
        }
    else:
        return {
            "status_msg": "[目标] 无更多子目标",
            "new_goal_id": None,
        }


def apply_proceed(purpose, goal_id: str, answer: str) -> dict:
    """处理"执行"选择：完成当前子目标，推进到下一个子目标。

    Returns:
        {"status_msg": str, "new_goal_id": str | None}
      - new_goal_id: 下一个激活的子目标 id（None 表示无更多子目标）
    """
    goal = purpose.goals.get(goal_id)
    if not goal:
        return {"status_msg": None, "new_goal_id": None}

    goal.metadata["answer"] = answer  # 存储用户的选择
    purpose.goals[goal.id].complete()

    next_sub = purpose.get_next_sibling(goal.id)
    if next_sub:
        purpose.set_current(next_sub.id)
        return {
            "status_msg": f"[目标] 完成，激活下一个: {next_sub.description[:40]}",
            "new_goal_id": next_sub.id,
        }
    else:
        return {
            "status_msg": "[目标] 所有子目标已完成",
            "new_goal_id": None,
        }
