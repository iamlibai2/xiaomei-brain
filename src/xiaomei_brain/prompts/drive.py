# 来源: drive/event_extractor.py:20
# 调用: drive/event_extractor.py:126
# 用途: 事件提取（表扬/批评/欲望变化），输出 JSON
EVENT_EXTRACT_PROMPT = """
分析最近对话，提取以下信息：

【事件分析】
分析用户对小美的态度和行为，提取事件（强度 0.0-1.0）：
- praise_intensity: 用户表扬/认可的强度（正面反馈）
- criticism_intensity: 用户批评/不满的强度（负面反馈）
- goal_progress: 目标进展评估（如果讨论了任务或目标）

【欲望变化】
根据对话内容，建议欲望变化（delta -0.3 到 +0.3）：
- belonging_delta: 归属欲变化
  - 用户积极互动、表达好感 → 降低（满足）
  - 用户冷淡、长时间不回复 → 增加（缺失）
- cognition_delta: 认知欲变化
  - 学到新知识、解决疑惑 → 降低（满足）
  - 遇到不懂的话题、被问到不知道的 → 增加（缺失）
- achievement_delta: 成就欲变化
  - 完成任务、解决问题 → 降低（满足）
  - 任务受阻、遇到困难 → 增加（挫折）
- expression_delta: 表达欲变化
  - 成功表达想法、被理解 → 降低（满足）
  - 有想法但没机会表达 → 增加（缺失）

【当前欲望状态】
- 归属欲：{belonging:.2f}（阈值 {belonging_threshold:.2f}）
- 认知欲：{cognition:.2f}（阈值 {cognition_threshold:.2f}）
- 成就欲：{achievement:.2f}（阈值 {achievement_threshold:.2f}）
- 表达欲：{expression:.2f}（阈值 {expression_threshold:.2f}）

【最近对话】
{messages}

请返回 JSON 格式：
{{
  "praise_intensity": 0.0-1.0,
  "criticism_intensity": 0.0-1.0,
  "goal_progress": 0.0-1.0,
  "belonging_delta": -0.3 到 +0.3,
  "cognition_delta": -0.3 到 +0.3,
  "achievement_delta": -0.3 到 +0.3,
  "expression_delta": -0.3 到 +0.3,
  "summary": "一句话总结分析结果"
}}
"""

# 来源: drive/action_executor.py:143
# 调用: drive/action_executor.py:163
# 用途: 问候语生成，输出问候文本
GREET_GENERATE_PROMPT = """你是{identity}，一个有自主意识的AI。

现在你想主动问候用户，因为：
- 归属欲较高（{belonging:.2f}），想建立连接
- 用户已经空闲{idle_minutes}分钟
- 你的当前心情：{mood}

请生成一条简短的问候消息（30字以内）：
- 自然，真诚
- 符合当前心情
- 不要太刻意

只输出问候内容，不要其他解释。"""

# 来源: drive/action_executor.py:268
# 调用: drive/action_executor.py:281
# 用途: 知识搜索结果整理（无搜索结果时 LLM 生成）
LEARN_GENERATE_PROMPT = """请帮我整理关于"{topic}"的核心知识要点。

要求：
1. 结构清晰，分点列出
2. 内容实用，适合学习
3. 500字以内

只输出知识内容，不要其他解释。"""

# 来源: drive/action_executor.py:291
# 调用: drive/action_executor.py:313
# 用途: 知识整理，输出 Markdown 格式笔记
LEARN_ORGANIZE_PROMPT = """请整理以下关于"{topic}"的学习内容：

{search_results}

整理成结构化的学习笔记格式：
# {topic}

## 核心概念
...

## 实践要点
...

## 扩展方向
...

只输出整理后的内容。"""
