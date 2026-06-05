# 来源: purpose/intent.py:86 (已迁移至 prompts/purpose.py)
# 调用: purpose/intent.py:124 (understand_intent_type)
# 用途: 意图类型分类，输出 JSON
INTENT_CLASSIFY_PROMPT = """
分析对方输入，判断意图类型。

【当前状态】
存在意义：{meaning}
当前目标：{current_goal}
当前目标深度：{current_goal_depth}（0=顶层目标，1=一级子目标/已拆解）
待执行目标：{pending_goals}

【对方输入】
{user_input}

请判断意图类型（intent_type）：

- task: 对方要求执行某个新任务（如：帮我做X，开发X、做个X）
- query: 对方提出问题（如：X是什么、怎么做X、如何X）
- chat: 闲聊，无明确任务目的
- clarification: 请求解释或细化已有的当前目标

重要规则：
- **停止/放弃已有目标 → task**（如"别做X了"、"取消这个任务"）
- **明确的新任务请求 → task**（如"帮我做一个ERP"、"开发一个网站"）。必须有具体的任务描述才算 task，不能凭空编造
- **以"什么/怎么/如何/为什么"开头 → query**（如"ERP是什么"）
- **当前有活跃目标时，对方消息是关于当前目标的细化/解释 → clarification**
- **但注意：对方描述的任务与当前目标明显不同（核心交付物/领域/范围不同）→ task，不是 clarification**
- **"分成N个子目标执行" = 对当前目标的明确操作指令 → task**
- **不明确的继续类语句（"继续"、"接着做"、"next"）→ chat**，让 Agent 通过对话确认用户想继续什么

返回 JSON：
{{"intent_type": "task/query/chat/clarification", "confidence": 0.0-1.0, "reasoning": "判断理由", "goal_description": "目标描述（仅task时有）"}}
"""

# 来源: purpose/intent.py:115 (已迁移至 prompts/purpose.py)
# 调用: purpose/intent.py:136 (decompose_goal)
# 用途: 目标分解，输出 JSON
GOAL_DECOMPOSE_PROMPT = """
给定一个目标，将其分解为子目标。

【目标】
{goal_description}

{calibration_context}
分解原则：
- 涉及技术选择（语言/框架/数据库/方案）的 → 必须有对应的"确认X"子目标
- 复杂项目 → 按"了解需求 → 制定计划 → 执行 → 验收"顺序分解
- 单步操作（清空/删除/重置/简单查询）→ 返回空数组，不分解

返回 JSON：
{{"sub_goals": ["子目标1", "子目标2"]}}
如果不需要分解：
{{"sub_goals": []}}
"""

# 来源: purpose/purpose_engine.py:424
# 调用: purpose/purpose_engine.py:438
# 用途: LLM 目标分解，输出子目标列表
GOAL_LLM_DECOMPOSE_PROMPT = """请将以下目标分解为 2-4 个子目标，并识别依赖关系：

目标：{goal_description}

要求：
- 子目标应该是具体可执行的步骤
- 子目标之间有逻辑顺序
- 如果某些子目标必须在其他子目标完成后才能开始，标注依赖关系
- 每个子目标用一句话描述

输出格式（每行一个子目标，依赖关系用 <- 标注）：
子目标描述
子目标描述 <- 子目标1描述
子目标描述

其中 "<- 子目标X描述" 表示该子目标依赖子目标X（子目标X必须先完成）。
不需要编号。只输出子目标列表，不要其他解释。"""

# 来源: purpose/task_executor.py:163 (build_intent_context)
# 调用: purpose/task_executor.py:151 (追加到任务执行上下文)
# 用途: PROGRESS 块格式引导 — 教 LLM 输出任务进度
PROGRESS_BLOCK_INSTRUCTION = """【重要】先正常回复对方，回复完成后，再在末尾输出进度块：

<PROGRESS>
{"status": "completed", "summary": "一句话总结本子目标的产出"}  ← 当前子目标已完成时
</PROGRESS>

或

<PROGRESS>
{"status": "in_progress"}  ← 当前子目标未完成，但无需等待用户，系统会继续推进
</PROGRESS>

或

<PROGRESS>
{"status": "waiting_user"}  ← 你向对方提了问题/需要对方确认，必须暂停等待回复
</PROGRESS>

如果对方输入中没有值得推进的内容，输出：无需推进"""
