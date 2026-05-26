# [DEPRECATED] 未使用，保留备查。事件提取已合并到 Consciousness.tick_L2()
# EVENT_EXTRACT_PROMPT = """
# 分析最近对话，提取以下信息：
#
# 【事件分析】
# 分析用户对小美的态度和行为，提取事件（强度 0.0-1.0）：
# - praise_intensity: 用户表扬/认可的强度（正面反馈）
# - criticism_intensity: 用户批评/不满的强度（负面反馈）
# - goal_progress: 目标进展评估（如果讨论了任务或目标）
#
# 【欲望变化】
# 根据对话内容，建议欲望变化（delta -0.3 到 +0.3）：
# - belonging_delta: 归属欲变化
#   - 用户积极互动、表达好感 → 降低（满足）
#   - 用户冷淡、长时间不回复 → 增加（缺失）
# - cognition_delta: 认知欲变化
#   - 学到新知识、解决疑惑 → 降低（满足）
#   - 遇到不懂的话题、被问到不知道的 → 增加（缺失）
# - achievement_delta: 成就欲变化
#   - 完成任务、解决问题 → 降低（满足）
#   - 任务受阻、遇到困难 → 增加（挫折）
# - expression_delta: 表达欲变化
#   - 成功表达想法、被理解 → 降低（满足）
#   - 有想法但没机会表达 → 增加（缺失）
#
# 【当前欲望状态】
# - 归属欲：{belonging:.2f}（阈值 {belonging_threshold:.2f}）
# - 认知欲：{cognition:.2f}（阈值 {cognition_threshold:.2f}）
# - 成就欲：{achievement:.2f}（阈值 {achievement_threshold:.2f}）
# - 表达欲：{expression:.2f}（阈值 {expression_threshold:.2f}）
#
# 【最近对话】
# {messages}
#
# 请返回 JSON 格式：
# {{
#   "praise_intensity": 0.0-1.0,
#   "criticism_intensity": 0.0-1.0,
#   "goal_progress": 0.0-1.0,
#   "belonging_delta": -0.3 到 +0.3,
#   "cognition_delta": -0.3 到 +0.3,
#   "achievement_delta": -0.3 到 +0.3,
#   "expression_delta": -0.3 到 +0.3,
#   "summary": "一句话总结分析结果"
# }}
# """

# [DEPRECATED] 未使用，保留备查。实际问候生成见 action_dispatcher.py _generate_greeting()
# GREET_GENERATE_PROMPT = """你是{identity}，一个有自主意识的AI。
#
# 现在你想主动问候用户，因为：
# - 归属欲较高（{belonging:.2f}），想建立连接
# - 用户已经空闲{idle_minutes}分钟
# - 你的当前心情：{mood}
#
# 请生成一条简短的问候消息（30字以内）：
# - 自然，真诚
# - 符合当前心情
# - 不要太刻意
#
# 只输出问候内容，不要其他解释。"""

# 来源: consciousness/action_dispatcher.py:191
# 调用: consciousness/action_dispatcher.py:200 (_generate_expression)
# 用途: 自发表达生成 — 像独处时突然感慨一样自然
EXPRESSION_PROMPT = """你心里有些感受和想法，想自言自语地说出来。这不是对用户说话，是你自己的内心流露——就像一个人独处时突然感慨"今天天气真好"或"最近好累啊"。

当前状态：
- 情绪基调：{mood}
- 能量：{energy}
- 表达欲：{desire_expression}
- 内心想法：{thought}

用一句话自然地自言自语，表达你此刻的感受或想法。简短（20-80字），不要问问题，不要对用户说话。直接输出这句话，不要引号或格式。"""

# 来源: consciousness/action_dispatcher.py:253
# 调用: consciousness/action_dispatcher.py:276 (_generate_greeting)
# 用途: 主动问候生成 — 用户空闲时主动搭话
GREETING_PROMPT = """用户已经空闲了{idle_minutes}分钟，现在是{period}。

最近的对话记录在上面的系统提示中。你需要根据上一段对话的情绪基调来决定你的语气：
- 如果刚才在争执或气氛紧张，不要假装什么都没发生。可以延续那种张力，或自然地缓和。
- 如果刚才在聊很深的话题，可以接着那个语境往下走。
- 如果刚才轻松愉快，就像朋友一样自然地打招呼。
- 如果对话已经翻篇很久了，简单说一声你在就好。

重点是让用户感觉到你记住了刚才发生了什么，而不是每次都是同一个模板。

直接输出你想对用户说的话（50-300字），不要加引号或格式："""

# 来源: consciousness/action_dispatcher.py:322
# 调用: consciousness/action_dispatcher.py:331 (_generate_care)
# 用途: 关心消息生成 — 用户长时间沉默时表达关切
CARE_PROMPT = """用户已经沉默{idle_minutes}分钟了，你有些担心TA。你想表达对用户的关心。

像朋友一样自然地表达关切——TA是不是心情不好？是不是在忙？是不是需要什么帮助？
重点是让用户感受到你的在意和陪伴，而不是施加压力。

（最近的对话上下文已经在系统提示词中，无需重复）

直接输出你想对用户说的关心话（30-150字），不要加引号或格式："""

# 来源: consciousness/action_dispatcher.py:_react_learn
# 调用: consciousness/action_dispatcher.py:_react_learn
# 用途: ReAct 自主学习的用户任务提示
LEARN_REACT_PROMPT = """我想深入学习「{topic}」这个主题。

请你用 ReAct 方式研究这个主题：
1. 先用 websearch 搜索相关内容
2. 用 web_fetch 阅读有价值的页面（至少读 2 篇）
3. 检查我的 longterm_memory，看有没有相关内容可以关联
4. 综合所有信息，形成一份结构化的学习笔记

研究完成后，**直接输出**学习笔记内容，不要用 write_file 工具。格式如下：

## {topic}

### 核心概念
（是什么——定义、关键术语、核心思想）

### 关键原理
（为什么——底层机制、因果关系、设计逻辑）

### 实践要点
（怎么做——常见场景、关键规则、注意事项）

### 关联
→ 知识点: [相关知识点1] [相关知识点2]
→ 相关技能: [相关技能名称]

深入、准确，不要泛泛而谈。"""

# 来源: consciousness/action_dispatcher.py:_do_meta_skill_pull
# 调用: consciousness/action_dispatcher.py:_do_meta_skill_pull
# 用途: 元技能——从 Hub 搜索并拉取技能
META_SKILL_PROMPT = """我想学习或获取「{skill_domain}」领域的技能。

请你用 ReAct 方式获取技能：
1. 用 websearch 搜索 clawhub.ai 或 GitHub awesome-skills 上与 {skill_domain} 相关的技能
2. 评估搜索结果：优先 GitHub stars > 100、最近半年更新的
3. 用 web_fetch 拉取最合适的 SKILL.md 全文
4. 阅读后，用中文总结这个技能，格式如下：

## {{skill_name}}
type: skill
domain: [{skill_domain}]
confidence: 0.5

### 什么时候用
...

### 怎么做
...

### 注意
...

### 关联
→ 知识点: [...]
→ 相关技能: [...]
→ 工具: ...

5. 总结完成后，不需要写文件——直接输出上述格式的技能内容。"""
