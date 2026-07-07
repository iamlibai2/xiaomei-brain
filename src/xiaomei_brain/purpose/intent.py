"""
Intent Understanding - 用户意图理解 + 目标分解

两阶段设计：
1. 第1次LLM：判断意图类型（TASK/QUERY/CHAT/CLARIFICATION）
2. 第2次LLM：如果是TASK，分解子目标

流程：
用户输入 → 意图判断 → 目标分解（仅TASK） → IntentResult → PurposeEngine 处理
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from .goal import Goal, GoalType, GoalStatus

logger = logging.getLogger(__name__)


class IntentType(Enum):
    """意图类型"""
    TASK = "task"                # 执行任务
    QUERY = "query"              # 提问
    CHAT = "chat"                # 闲聊
    CLARIFICATION = "clarification"  # 澄清


class GoalRelation(Enum):
    """目标关系"""
    NEW = "new"                  # 新建目标
    SUB_GOAL_OF = "sub_goal_of"  # 子目标
    MODIFIES = "modifies"        # 修改已有目标
    NONE = "none"                # 无目标


@dataclass
class IntentResult:
    """
    意图分析结果

    包含：
    - 意图类型
    - 相关目标
    - 子目标（自动分解）
    - 目标关系
    - 置信度
    - LLM 推理过程
    - 确认信息（第一个子目标需要用户选择时填充）
    """
    intent_type: IntentType = IntentType.CHAT
    goals: list[Goal] = field(default_factory=list)
    sub_goals: list[str] = field(default_factory=list)  # 子目标描述列表
    relation: GoalRelation = GoalRelation.NONE
    target_goal_id: Optional[str] = None
    confidence: float = 0.0
    reasoning: str = ""
    task_type: str = ""                   # 任务类型（execution/learning/exploration等）
    confirm_question: str = ""            # 需要用户确认的问题
    confirm_options: list[str] = field(default_factory=list)  # 选项列表
    response_guidance: str = ""           # CHAT 类型的回应风格建议

    def has_goal(self) -> bool:
        """是否有目标"""
        return len(self.goals) > 0

    def has_sub_goals(self) -> bool:
        """是否有子目标"""
        return len(self.sub_goals) > 0

    def is_task(self) -> bool:
        """是否是任务"""
        return self.intent_type == IntentType.TASK

    def is_query(self) -> bool:
        """是否是提问"""
        return self.intent_type == IntentType.QUERY

    def is_chat(self) -> bool:
        """是否是闲聊"""
        return self.intent_type == IntentType.CHAT

from ..prompts import INTENT_CLASSIFY_PROMPT, GOAL_DECOMPOSE_PROMPT


class IntentUnderstanding:
    """意图理解模块"""

    def __init__(self, llm_client: Any = None):
        self.llm = llm_client

    def understand_intent_type(
        self,
        user_input: str,
        meaning: str,
        current_goal: str,
        current_goal_depth: int = 0,
        pending_goals: str = "",
    ) -> dict:
        """第1次LLM调用：判断意图类型。

        返回：
            {"intent_type": IntentType, "confidence": float,
             "reasoning": str, "goal_description": str}
        """
        if not self.llm:
            logger.warning("[Intent] 无 LLM，使用规则分析")
            return self._rule_classify(user_input)

        prompt = INTENT_CLASSIFY_PROMPT.format(
            meaning=meaning,
            current_goal=current_goal or "无",
            current_goal_depth=current_goal_depth,
            pending_goals=pending_goals or "无",
            user_input=user_input,
        )

        try:
            response = self.llm.chat([{"role": "user", "content": prompt}])
            text = response.content if hasattr(response, "content") else str(response)
            return self._parse_classify_response(text)
        except Exception as e:
            logger.warning(f"[Intent] 意图判断失败: {e}")
            return self._rule_classify(user_input)

    def decompose_goal(self, goal_description: str, calibration_context: str = "") -> list[str]:
        """第2次LLM调用：目标分解。

        返回：子目标描述列表（空列表=单步任务）
        """
        if not self.llm:
            # 无LLM时用规则判断是否需要分解
            return self._rule_should_decompose(goal_description)

        prompt = GOAL_DECOMPOSE_PROMPT.format(
            goal_description=goal_description,
            calibration_context=calibration_context,
        )

        try:
            response = self.llm.chat([{"role": "user", "content": prompt}])
            text = response.content if hasattr(response, "content") else str(response)
            return self._parse_decompose_response(text)
        except Exception as e:
            logger.warning(f"[Intent] 目标分解失败: {e}")
            return []

    def understand(
        self,
        user_input: str,
        meaning: str,
        current_goal: str,
        current_goal_depth: int = 0,
        pending_goals: str = "",
        calibration_context: str = "",
    ) -> IntentResult:
        """
        分析用户输入，提取意图。两阶段LLM：
        1. 判断意图类型
        2. 如果是TASK，分解子目标
        """
        # 第1次LLM：判断意图类型
        type_info = self.understand_intent_type(
            user_input, meaning, current_goal, current_goal_depth, pending_goals,
        )

        intent_type = type_info["intent_type"]
        confidence = type_info["confidence"]
        reasoning = type_info["reasoning"]
        goal_description = type_info.get("goal_description", "")

        logger.info(
            f"[Intent] 意图判断: type={intent_type.value}, "
            f"confidence={confidence:.2f}, goal={goal_description[:30] if goal_description else 'none'}"
        )

        # 非TASK，不需要分解
        if intent_type != IntentType.TASK:
            return IntentResult(
                intent_type=intent_type,
                confidence=confidence,
                reasoning=reasoning,
                response_guidance=type_info.get("response_guidance", ""),
            )

        # 第2次LLM：分解子目标
        sub_goals = self.decompose_goal(goal_description, calibration_context) if goal_description else []

        # 构造目标
        goal = Goal(
            description=goal_description,
            goal_type=GoalType.EXECUTABLE,
            status=GoalStatus.PENDING,
        )

        logger.info(
            f"[Intent] 目标分解: {len(sub_goals)}个子目标"
        )

        return IntentResult(
            intent_type=intent_type,
            goals=[goal],
            sub_goals=sub_goals,
            relation=GoalRelation.NEW,
            confidence=confidence,
            reasoning=reasoning,
            response_guidance=type_info.get("response_guidance", ""),
        )

    def _parse_response(self, response: str) -> IntentResult:
        """解析 LLM 返回"""
        import json

        # 提取 JSON
        json_match = re.search(r"\{[\s\S]*\}", response)
        if not json_match:
            logger.warning(f"[IntentUnderstanding] 未找到 JSON")
            return IntentResult(intent_type=IntentType.CHAT)

        try:
            data = json.loads(json_match.group())

            # 解析意图类型
            intent_type = IntentType(
                data.get("intent_type", "chat")
            )

            # 解析目标关系
            relation = GoalRelation(
                data.get("relation", "none")
            )

            # 解析目标列表
            goals = []
            for g_data in data.get("goals", []):
                goal = Goal(
                    description=g_data.get("description", ""),
                    goal_type=GoalType(
                        g_data.get("goal_type", "executable")
                    ),
                    status=GoalStatus.PENDING,
                )
                goals.append(goal)

            # 解析子目标列表
            sub_goals = data.get("sub_goals", [])
            if not isinstance(sub_goals, list):
                sub_goals = []

            # 解析确认信息
            confirm_question = data.get("confirm_question", "")
            confirm_options = data.get("confirm_options", [])
            if not isinstance(confirm_options, list):
                confirm_options = []

            # 其他字段
            target_goal_id = data.get("target_goal_id")
            confidence = data.get("confidence", 0.5)
            reasoning = data.get("reasoning", "")

            logger.info(
                f"[IntentUnderstanding] 解析完成: "
                f"type={intent_type.value}, "
                f"goals={len(goals)}, "
                f"sub_goals={len(sub_goals)}, "
                f"confidence={confidence:.2f}"
            )

            return IntentResult(
                intent_type=intent_type,
                goals=goals,
                sub_goals=sub_goals,
                relation=relation,
                target_goal_id=target_goal_id,
                confidence=confidence,
                reasoning=reasoning,
                confirm_question=confirm_question,
                confirm_options=confirm_options,
            )

        except Exception as e:
            logger.warning(f"[IntentUnderstanding] JSON 解析失败: {e}")
            return IntentResult(intent_type=IntentType.CHAT)

    def _parse_classify_response(self, response: str) -> dict:
        """解析第1次LLM返回的意图分类结果"""
        import json
        json_match = re.search(r"\{[\s\S]*\}", response)
        if not json_match:
            return self._rule_classify("")
        try:
            data = json.loads(json_match.group())
            return {
                "intent_type": IntentType(data.get("intent_type", "chat")),
                "confidence": float(data.get("confidence", 0.5)),
                "reasoning": data.get("reasoning", ""),
                "goal_description": data.get("goal_description", ""),
                "target_goal_id": data.get("target_goal_id", ""),
                "response_guidance": data.get("response_guidance", ""),
            }
        except Exception:
            logger.warning("Failed to parse LLM intent response, falling back to rule classify", exc_info=True)
            return self._rule_classify("")

    def _parse_decompose_response(self, response: str) -> list[str]:
        """解析第2次LLM返回的子目标分解结果"""
        import json
        json_match = re.search(r"\{[\s\S]*\}", response)
        if not json_match:
            return []
        try:
            data = json.loads(json_match.group())
            subs = data.get("sub_goals", [])
            return subs if isinstance(subs, list) else []
        except Exception:
            logger.warning("Failed to parse LLM goal decomposition response", exc_info=True)
            return []

    def _rule_classify(self, user_input: str) -> dict:
        """规则分析（后备）：只返回意图分类信息，不做分解"""
        import re
        task_keywords = ["帮我", "开发", "做一个", "设计", "搭建", "实现", "开发"]
        simple_keywords = ["写.*文件", "读.*文件", "搜索", "翻译", "执行", "运行"]
        query_keywords = ["是什么", "为什么", "怎么", "如何", "？"]

        for pattern in simple_keywords:
            if re.search(pattern, user_input):
                return {"intent_type": IntentType.QUERY, "confidence": 0.7,
                        "reasoning": f"简单操作: {pattern}", "goal_description": ""}

        for kw in task_keywords:
            if kw in user_input:
                desc = user_input.replace(kw, "").strip()[:50]
                return {"intent_type": IntentType.TASK, "confidence": 0.6,
                        "reasoning": f"任务关键词: {kw}", "goal_description": desc}

        for kw in query_keywords:
            if kw in user_input:
                return {"intent_type": IntentType.QUERY, "confidence": 0.5,
                        "reasoning": f"问题关键词: {kw}", "goal_description": ""}

        return {"intent_type": IntentType.CHAT, "confidence": 0.3,
                "reasoning": "无明确意图", "goal_description": ""}

    def _rule_should_decompose(self, goal_description: str) -> list[str]:
        """规则判断：是否需要分解（后备，无LLM时）"""
        single_step = ["清空", "删除", "重置", "查看", "显示", "查询", "备份", "同步"]
        for kw in single_step:
            if kw in goal_description:
                return []
        return [f"执行{goal_description}"]

    def _rule_analyze(
        self,
        user_input: str,
        current_goal: str,
    ) -> IntentResult:
        """
        规则分析（后备）

        简单关键词检测，包含默认子目标分解
        """
        # 任务关键词（复杂多步骤工作）
        task_keywords = ["帮我", "开发", "做一个", "设计", "搭建", "实现.*系统", "开发.*项目"]
        # 简单操作关键词（单步工具调用，不进目标系统）
        simple_keywords = ["写.*文件", "读.*文件", "搜索", "翻译", "执行", "运行", "创建.*文件"]
        # 问题关键词
        query_keywords = ["是什么", "为什么", "怎么", "如何", "？"]

        # 检测简单操作（直接走对话，不进目标系统）
        import re
        for pattern in simple_keywords:
            if re.search(pattern, user_input):
                return IntentResult(
                    intent_type=IntentType.QUERY,
                    confidence=0.7,
                    reasoning=f"检测到简单操作: {pattern}",
                )

        # 检测任务
        for kw in task_keywords:
            if kw in user_input:
                # 提取目标描述
                description = user_input.replace(kw, "").strip()[:50]
                if description:
                    goal = Goal(description=description)
                    # 默认子目标分解（规则后备）
                    default_sub_goals = [
                        f"了解{description}的需求和背景",
                        f"制定{description}的计划",
                        f"执行{description}",
                        f"总结和验收",
                    ]
                    return IntentResult(
                        intent_type=IntentType.TASK,
                        goals=[goal],
                        sub_goals=default_sub_goals,
                        relation=GoalRelation.NEW,
                        confidence=0.6,
                        reasoning=f"检测到任务关键词: {kw}",
                    )

        # 检测问题
        for kw in query_keywords:
            if kw in user_input:
                return IntentResult(
                    intent_type=IntentType.QUERY,
                    confidence=0.5,
                    reasoning=f"检测到问题关键词: {kw}",
                )

        # 默认：闲聊
        return IntentResult(
            intent_type=IntentType.CHAT,
            confidence=0.3,
            reasoning="无明确任务或问题",
        )