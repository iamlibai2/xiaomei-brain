# 来源: purpose/intent.py:86
# 调用: purpose/intent.py:164
# 用途: 意图类型分类，输出 JSON
INTENT_CLASSIFY_PROMPT = """
分析用户输入，判断意图类型。

【当前状态】
存在意义：{meaning}
当前目标：{current_goal}
当前目标深度：{current_goal_depth}（0=顶层目标，1=一级子目标/已拆解）
待执行目标：{pending_goals}

【用户输入】
{user_input}

请判断意图类型（intent_type），只需返回一个类型：

- task: 用户要求执行某个任务（如：帮我做X，开发X、做个X）
  还需要判断 task_type：
  - execution: 有明确交付物（开发、搭建、实现，写代码）
  - learning: 学习知识/技能（学习、了解、掌握、入门）
  - reflection: 反思/自省（反思、思考自己、审视）
  - relationship: 关系维护（关心、关注他人状态）
  - exploration: 探索调研（研究、调研、对比方案、找资料）
- query: 用户提出问题（如：X是什么、怎么做X、如何X）
- chat: 闲聊，无明确任务目的
- clarification: 请求解释或细化已有的目标

重要规则：
- **停止/放弃已有目标 → task**（如"别做X了"、"取消这个任务"）
- **明确的任务请求 → task**（如"帮我做一个ERP"、"开发一个网站"）
- **以"什么/怎么/如何/为什么"开头 → query**（如"ERP是什么"）
- **当前有活跃目标时，用户消息是关于当前目标的细化/解释 → clarification**

返回 JSON：
{{"intent_type": "task/query/chat/clarification", "confidence": 0.0-1.0, "reasoning": "判断理由", "goal_description": "目标描述（仅task时有）", "task_type": "execution/learning/reflection/relationship/exploration（仅task时有）"}}
"""

# 来源: purpose/intent.py:122
# 调用: purpose/intent.py:189
# 用途: 目标分解，输出 JSON
GOAL_DECOMPOSE_PROMPT = """
给定一个目标，将其分解为子目标。

【目标】
{goal_description}

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
GOAL_LLM_DECOMPOSE_PROMPT = """请将以下目标分解为 2-4 个子目标：

目标：{goal_description}

要求：
- 子目标应该是具体可执行的步骤
- 子目标之间有逻辑顺序
- 每个子目标用一句话描述

只输出子目标列表，每行一个，不要其他解释。"""
