"""
Intent Understanding - 用户意图理解 + 目标分解

分析用户输入，提取：
- 意图类型：TASK/QUERY/CHAT/CLARIFICATION
- 目标：新建/关联/修改
- 子目标：自动分解（如果是 TASK）
- 置信度

流程：
用户输入 → LLM 分析 → IntentResult（含子目标） → PurposeEngine 处理

合并优化：一次 LLM 调用完成意图识别 + 目标分解
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
    confirm_question: str = ""            # 需要用户确认的问题
    confirm_options: list[str] = field(default_factory=list)  # 选项列表

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


INTENT_PROMPT = """
分析用户输入，提取意图和目标，并自动分解子目标。

【当前状态】
存在意义：{meaning}
当前目标：{current_goal}
当前目标深度：{current_goal_depth}（0=顶层目标，1=一级子目标/已拆解，2=二级子目标/不可再拆）
待执行目标：{pending_goals}
最大分解深度：{max_depth}

【用户输入】
{user_input}

请分析：
1. 意图类型（intent_type）：
   - task: 用户要求执行某个任务
   - query: 用户提出问题
   - chat: 闲聊，无明确任务
   - clarification: 澄清之前的对话

2. 目标信息（如果 intent_type 是 task）：
   - description: 目标描述（一句话）
   - goal_type: executable（可执行）
   - relation: 与现有目标的关系
     - new: 新目标
     - sub_goal_of: 是某目标的子目标（需指定 target_goal_id）
     - modifies: 修改某目标（需指定 target_goal_id）

3. 子目标分解（仅当任务需要时）：
   - 复杂任务（涉及多步骤、选择、计划）才需要分解为 2-4 个子目标
   - **单步操作不需要分解**，直接返回空 sub_goals：
     - 清空/删除/重置类："清空记忆"、"删除所有记录"、"重置设置"
     - 简单查询："查看状态"、"显示列表"
     - 单一执行："执行备份"、"开始同步"
   - 子目标应该有逻辑顺序，每个用一句话描述

4. 置信度（confidence）：0.0-1.0

重要规则：
- **clarification 的准确定义（极其重要）**：
  - clarification = 用户在请求解释、细化、或修改**已有的、正在讨论的**目标
  - 典型问句：以"什么/哪个/怎么/为何/能否详细说说"开头，或明确要求解释某目标
  - 例如："ERP是什么"、"目标具体要怎么做"、"为什么要分这几步"
  - **明确的任务请求（要做什么）永远不是 clarification**
  - 例如："帮我做一个ERP"、"开发一个网站"、"做个博客" → task
  - 当前目标深度>=1 时，用户消息一定是当前子目标的澄清/细化，intent_type 为 clarification
  - 当前目标深度=0 时，只有明确在问"某目标是什么/怎么做"的才是 clarification
- **软件开发/项目类请求 → 必须是 task（极其重要）**
  - 关键词：做个X、开发X、做个软件/应用/小程序/网站/系统、帮我做、帮我写、帮我开发
  - 即使涉及写代码，也是复杂多步骤工作（需求分析→设计→编码→测试），必须归类为 task
  - 置信度 0.7-0.9，不要给低分
- **简单操作（单次工具调用即可完成）→ 分类为 query，而不是 task**
  - 例如：搜索网页、翻译单词、查天气、读文件、执行单条shell命令
  - 这些不需要目标分解，Agent 在对话中直接调用工具即可
- **极简指令处理**：
  - 用户输入非常简短且 imperative（祈使句），如"随便"、"快写"、"开始"、"做了"
  - 但"帮我做X"（X≥3字）不是极简指令，是完整任务请求，必须归类为 task
- **停止/放弃已有目标（极其重要）**：
  - 如果用户要求停止、放弃、取消、中止某个已在执行的任务 → relation=modifies，target_goal_id=匹配的已有目标
  - 关键词模式：别[X]了、停止[X]、取消[X]、不做[X]了、算了[X]、中止[X]
  - 例："别写ERP了" → 匹配现有ERP目标，relation=modifies，目标是"停止ERP开发"
  - 例："取消这个任务" → 匹配当前执行中的目标，relation=modifies
  - 只有当没有匹配的已有目标时，才创建新的"停止X"目标

5. 确认信息（关键）：如果第一个子目标涉及需要用户选择的参数，
   请填写 confirm_question 和 confirm_options。
   适用场景（不限于此）：
   - 技术栈选择：子目标如"确定技术栈"
   - 开发语言选择：子目标如"选择开发语言"
   - 数据库选择：子目标如"确定数据库方案"
   - 框架选择：子目标如"选择后端框架"
   - 文章风格/字数：子目标如"确认文章风格和篇幅"
   - 设计方向：子目标如"确认设计方案"
   - 任何需要用户拍板的参数

   格式示例：
   "confirm_question": "请选择开发技术栈：",
   "confirm_options": ["Python/Flask", "Python/Django", "Java/Spring", "Go/Gin"]

   如果第一个子目标不涉及选择，confirm_question 设为空字符串，
   confirm_options 设为空数组。

返回 JSON 格式：
{{
  "intent_type": "task/query/chat/clarification",
  "goals": [{{"description": "...", "goal_type": "executable"}}],
  "sub_goals": ["子目标1", "子目标2", "子目标3"],
  "relation": "new/sub_goal_of/modifies/none",
  "target_goal_id": "xxx",
  "confidence": 0.8,
  "reasoning": "用户说...",
  "confirm_question": "请选择开发技术栈：",
  "confirm_options": ["Python/Flask", "Python/Django", "Java/Spring"]
}}
"""


class IntentUnderstanding:
    """意图理解模块"""

    def __init__(self, llm_client: Any = None):
        self.llm = llm_client

    def understand(
        self,
        user_input: str,
        meaning: str,
        current_goal: str,
        current_goal_depth: int = 0,
        pending_goals: str = "",
    ) -> IntentResult:
        """
        分析用户输入，提取意图

        user_input: 用户消息
        meaning: 存在意义摘要
        current_goal: 当前活跃目标描述
        current_goal_depth: 当前目标深度（0=顶层，1=一级子目标，2=二级）
        pending_goals: 待执行目标列表描述

        返回：IntentResult
        """
        if not self.llm:
            logger.warning("[IntentUnderstanding] 无 LLM，使用规则分析")
            return self._rule_analyze(user_input, current_goal)

        # 构建 prompt
        prompt = INTENT_PROMPT.format(
            meaning=meaning,
            current_goal=current_goal or "无",
            current_goal_depth=current_goal_depth,
            max_depth=Goal.MAX_DEPTH,
            pending_goals=pending_goals or "无",
            user_input=user_input,
        )

        try:
            # 调用 LLM
            if hasattr(self.llm, "chat"):
                messages = [{"role": "user", "content": prompt}]
                response = self.llm.chat(messages)
                if response and hasattr(response, "content"):
                    text = response.content
                else:
                    text = str(response)
            else:
                text = str(self.llm.call(prompt))

            # 解析结果
            result = self._parse_response(text)

            logger.info(
                f"[IntentUnderstanding] 分析完成: "
                f"type={result.intent_type.value}, "
                f"goals={len(result.goals)}, "
                f"confidence={result.confidence:.2f}"
            )

            return result

        except Exception as e:
            logger.warning(f"[IntentUnderstanding] LLM 分析失败: {e}")
            return self._rule_analyze(user_input, current_goal)

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