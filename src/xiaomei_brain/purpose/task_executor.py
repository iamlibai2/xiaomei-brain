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


from ..prompts.purpose import PROGRESS_BLOCK_INSTRUCTION

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


def build_intent_context(purpose, intent_result, chosen_by_user: bool = False, resume_snapshot: str = "") -> str:
    """构建 LLM 上下文（当前子目标 + 全局进度）

    核心原则：Agent 只知道当前执行的子目标，不暴露完整目标树
    MiniMax 限制：只能合并到 system prompt（不单独发 system message）

    Args:
        purpose: PurposeEngine 实例
        intent_result: IntentResult
        chosen_by_user: True 表示用户从"继续"列表中明确选择了此任务
        resume_snapshot: 任务恢复时的认知快照（来自 TaskManager）

    Returns:
        str: 上下文文本，空字符串表示无特殊上下文
    """
    if not intent_result:
        return ""

    # CHAT 闲聊：不需要特殊上下文（人格由 identity.md/SelfModel 处理）
    # 但有活跃/暂停目标时，提示 LLM 用 resume_goal 恢复 PACE 执行
    if intent_result.is_chat():
        if purpose:
            current = purpose.get_current()
            if current:
                # 找到根目标（顶层业务目标，而非子目标/元目标）
                root = current
                while root.parent_id:
                    parent = purpose.goals.get(root.parent_id)
                    if parent:
                        root = parent
                    else:
                        break
                goal_desc = root.description[:80]
            else:
                # 无活跃目标，检查是否有暂停/待执行的目标
                paused = purpose.get_paused_tasks()
                pending = purpose.get_pending_goals()
                if paused or pending:
                    return (
                        '[提示] 当前没有正在执行的目标，但有暂停或待执行的任务。\n'
                        '如果对方提到之前的任务（如继续、提到项目名等），\n'
                        '请先用 list_goals 查看目标列表，确认后调用 resume_goal 恢复执行。\n'
                        '如果对方明确要求新建任务，则正常处理。'
                    )
                else:
                    return ''

            return (
                f'[提示] 当前有活跃目标「{goal_desc}」。\n'
                '如果对方想继续这个任务（如说继续、接着做、确认推进等），\n'
                '请先调用 resume_goal 工具来恢复执行，不要直接开始工作。\n'
                '如果对方说的是其他无关内容，忽略此提示。'
            )
        return ''

    # CLARIFICATION / QUERY：如果无活跃目标，不需要特殊上下文
    # 有活跃目标时，统一走下面的 TASK 强约束上下文（"只执行这一个子目标"）
    if not intent_result.is_task() and not (purpose and purpose.get_current()):
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

    # 任务恢复：注入认知快照
    if resume_snapshot:
        context_lines.append(resume_snapshot)
        context_lines.append("")

    # 用户明确选择的任务：告知 Agent 不要再问选择
    if chosen_by_user:
        context_lines.append("【重要】对方已经从多个任务中明确选择了继续这个任务，不要再问对方选择。直接推进即可。")
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
        context_lines.append(f"【已确认】对方已选择：{confirmed_answer}")
        context_lines.append("直接使用上述选择执行，不要再询问对方。")

    # 子目标列表（已完成标记，方便 Agent 了解全局）
    if sub_goals:
        # 已完成子目标的产出摘要
        completed_with_output = [
            sg for sg in completed_subs
            if sg.metadata.get("output")
        ]
        if completed_with_output:
            context_lines.append("")
            context_lines.append("【已完成子目标】")
            for sg in completed_with_output:
                context_lines.append(f"  ✓ {sg.description[:30]} → {sg.metadata['output'][:100]}")

        context_lines.append("")
        context_lines.append("【全局进度】")
        for sg in sub_goals:
            status_mark = "✓" if sg.is_completed() else "○"
            active_mark = " →进行中" if sg.id == active_sub.id else ""
            context_lines.append(f"  {status_mark}{active_mark} {sg.description[:40]}")

    # 进度输出要求（XML 格式，和 MEMORY 块同级）
    context_lines.append("")
    context_lines.append(PROGRESS_BLOCK_INSTRUCTION)

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

    elif status == "waiting_user":
        # LLM 明确表示需要等待用户回复，标记进度但不完成
        purpose.update_progress(active_sub.id, 0.1)
        logger.info("[Progress] 子目标等待用户: %s", active_sub.description[:30])

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


def handle_sub_goal_error(purpose, goal_id: str, error_message: str = "") -> dict:
    """处理子目标执行异常：记录错误计数，超阈值则放弃并推进。

    Args:
        purpose: PurposeEngine 实例
        goal_id: 出错的子目标 id
        error_message: 错误详情

    Returns:
        {"action": "retry" | "abandon" | "none",
         "error_count": int,
         "status_msg": str | None,
         "next_goal_id": str | None}
    """
    if not purpose:
        return {"action": "none", "error_count": 0, "status_msg": None, "next_goal_id": None}

    goal = purpose.goals.get(goal_id)
    if not goal or not goal.parent_id:
        return {"action": "none", "error_count": 0, "status_msg": None, "next_goal_id": None}

    error_count = goal.metadata.get("error_count", 0) + 1
    goal.metadata["error_count"] = error_count

    # 记录错误详情
    import time
    errors = goal.metadata.setdefault("errors", [])
    errors.append({
        "count": error_count,
        "message": error_message[:200],
        "time": time.time(),
    })

    if error_count >= 3:
        goal.abandon()
        purpose.save()
        next_sub = purpose.get_next_sibling(goal.id)
        if next_sub:
            purpose.set_current(next_sub.id)
            return {
                "action": "abandon",
                "error_count": error_count,
                "status_msg": f"[放弃] {goal.description[:30]} 连续失败3次，跳过 → {next_sub.description[:30]}",
                "next_goal_id": next_sub.id,
            }
        else:
            purpose.current_goal = None
            return {
                "action": "abandon",
                "error_count": error_count,
                "status_msg": f"[放弃] {goal.description[:30]} 连续失败3次，无更多子目标",
                "next_goal_id": None,
            }

    return {
        "action": "retry",
        "error_count": error_count,
        "status_msg": f"[重试] {goal.description[:30]} 第{error_count}次失败，下次重试",
        "next_goal_id": None,
    }
