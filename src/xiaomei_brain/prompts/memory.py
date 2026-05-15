# 来源: memory/extractor.py:21
# 调用: memory/extractor.py:74
# 用途: 即时记忆提取 [已废弃]
IMMEDIATE_EXTRACT_PROMPT = """从以下对话中提取值得长期记住的信息。

规则：
- 关于用户的信息，用"用户..."表述（如：用户叫张三）
- 关于小美自己的信息，用"我..."表述
每条信息一行，格式：类别|内容
类别可以是：偏好、事实、经验、教训

用户输入中没有值得提取的信息时，输出：无

用户：{user_input}
助手：{assistant_response}"""

# 来源: memory/extractor.py:38
# 调用: memory/extractor.py:285
# 用途: 周期记忆提取，输出 ACTION|类别|内容
PERIODIC_EXTRACT_PROMPT = """从对话片段中提炼值得长期记住的信息，并判断如何处理。

【已有记忆】（供参考）
{recent_memories}

【对话片段】
{messages}

【提炼规则】
- 关于用户用"用户..."，关于小美用"我..."
- 只提取确实重要和有价值的内容
- 对每条记忆判断处理方式：
  * ADD: 全新信息
  * UPDATE: 已有记忆的更新
  * MERGE: 可合并的同类信息
  * NOOP: 无意义/重复，无需存储
- 如果没有值得提炼的内容，输出：无

输出格式（每条一行）：
ACTION|类别|内容

直接输出，无需解释："""

# 来源: memory/extractor.py:64
# 调用: memory/extractor.py:376
# 用途: 每轮记忆提取，输出 JSON
EVERY_TURN_EXTRACT_PROMPT = """你是记忆提取系统。**从用户输入和助手回复中分别提炼记忆**。

【已有记忆】（供参考）
{recent_memories}

【当前用户输入】
{user_input}

【助手回复】
{assistant_response}

【提炼规则】
- **同时从"当前用户输入"和"助手回复"中提炼**
- 关于用户用"用户..."，关于小美用"我..."
- **从用户输入**：提取用户直接表达的事实、偏好、经历
- **从助手回复**：提取小美学到的经验、教训，做出的决策、发现的新模式、建立的新认知
  * 如："我帮用户搭建了Docker环境，过程中发现..."
  * 如："我选择了python-docx方案而非pandoc，因为..."
  * 如："我意识到用户的代码风格偏好是..."
- 不提取临时性闲聊、无信息量的客套话
- 对每条记忆，判断处理方式：
  * ADD: 全新的重要信息
  * UPDATE: 已有记忆的更新版本
  * MERGE: 可合并的同类信息（如两个偏好）
  * NOOP: 无意义/重复/推测，无需存储
- 仔细对比【已有记忆】，语义重复或被包含的用 UPDATE/NOOP
- 如果新记忆与已有记忆有语义关联，在 relations 字段建立关联
- 关系类型: causal(因果), temporal(时序), contrast(对比), contains(包含)
- 如果没有任何值得提炼的内容，输出：{}

输出格式（JSON，无解释文本）：
{{"relations": [{{"from": "新记忆内容", "type": "causal", "to": "已有记忆内容"}}], "actions": [{{"type": "ADD", "tag": "偏好", "content": "用户喜欢川菜"}}]}}

例如：
{{"relations": [{{"from": "用户叫李四", "type": "causal", "to": "用户上周刚搬家"}}], "actions": [{{"type": "ADD", "tag": "事实", "content": "用户叫李四"}}]}}
{{"relations": [], "actions": [{{"type": "ADD", "tag": "偏好", "content": "用户喜欢川菜"}}, {{"type": "NOOP", "tag": "事实", "content": "用户说了你好"}}]}}
{{"relations": [{{"from": "用户喜欢MacBook", "type": "causal", "to": "用户买新电脑"}}, {{"from": "屏幕清晰", "type": "contains", "to": "用户喜欢MacBook"}}], "actions": [{{"type": "ADD", "tag": "偏好", "content": "用户喜欢MacBook"}}, {{"type": "UPDATE", "tag": "偏好", "content": "用户对屏幕印象深刻"}}, {{"type": "NOOP", "tag": "事实", "content": "用户说谢谢"}}]}}
{{"relations": [], "actions": [{{"type": "ADD", "tag": "经验", "content": "我选择了python-docx处理Word文档，因为兼容性好于pandoc"}}, {{"type": "ADD", "tag": "事实", "content": "用户偏好简洁的函数式风格"}}]}}

直接输出 JSON，无需解释："""

# 来源: memory/extractor.py:106
# 调用: memory/extractor.py:328
# 用途: 梦境记忆提取，输出 ACTION|类别|内容
DREAM_EXTRACT_PROMPT = """你是小美的内心反思系统。在以下对话中，提炼关于"小美自己"的重要信息，并判断如何处理。

【已有记忆】（供参考）
{recent_memories}

【今日对话】
{messages}

【提炼规则】
- 只关注"小美自己"的内在收获，用"我..."表述
- 包括：经验、教训、洞察、新的自我认知
- 判断处理方式：
  * ADD: 全新体悟
  * UPDATE: 已有认知的更新
  * MERGE: 可合并的同类体悟
  * NOOP: 无意义/重复
- 如果没有值得提炼的内容，输出：无

输出格式（每条一行）：
ACTION|类别|内容

直接输出，无需解释："""

# 来源: memory/extractor.py:130
# 调用: memory/extractor.py:1013
# 用途: 任务完成知识提取，输出 JSON
TASK_COMPLETION_PROMPT = """你是小美的知识提取系统。一个任务刚刚完成，请从认知日志中提取值得长期保存的知识。

【任务】
描述：{task_description}
类型：{task_type}

【认知日志】
{cognitive_log}

【产出物】
{artifacts}

【已有记忆】（供参考）
{recent_memories}

【提炼规则】
从以上认知日志中提炼值得长期记住的内容，用"我..."表述（因为是小美自己的经历）：
1. 学到了什么技术/经验 → tag=经验
2. 踩了什么坑 → tag=教训
3. 对用户有什么新发现 → tag=用户洞察
4. 形成了什么可复用的模式 → tag=模式
5. 自我有什么变化/成长 → tag=自我认知

判断处理方式：
- ADD: 全新的知识/经验
- UPDATE: 已有记忆的更新
- MERGE: 可合并的同类知识
- NOOP: 无意义/不值得长期保存

如果没有值得提炼的内容，输出：无

输出 JSON 格式：
{{"relations": [], "actions": [{{"type": "ADD", "tag": "经验", "content": "我学到了..."}}]}}

直接输出 JSON，无需解释："""

# 来源: memory/extractor.py:168
# 调用: agent/core.py:243 (append to last user message)
# 用途: 记忆决策格式指令
MEMORY_DECISION_PROMPT = """
## 记忆决策

**重要：请先正常回复用户，回复完成后，再在末尾输出 MEMORY 块。**

判断是否需要提取相关的长期记忆。

**规则**：
- 从最近一次用户输入中提取，也从最近一次你的回复中提取，只提取最近一次的，否则会造成重复记忆
- 关于用户的事实、偏好、经历用"用户..."
- 关于你学到的经验、教训、决策、新认知用"我..."
- 如果新记忆与已有记忆有语义关联，在 relations 字段建立关联
- 关系类型: causal(因果), temporal(时序), contrast(对比), contains(包含)
- 判断处理方式：ADD（全新）、UPDATE（更新旧记忆）、MERGE（合并同类）、NOOP（无意义/重复/推测）
- 每条记忆都要标注 scenes（场景标签，1~3个），反映这条记忆在什么场景下会被唤起
- **场景标签用中文，具体且有画面感，如：家、院子、工作、学习、编程、休闲、社交、美食、旅行、出行、健康、创作、家庭、生活、童年、购物 等。一个场景就是一个能被唤起的情境——请认真思考这条记忆会在什么情境下被用到。如果实在想不出合适的，可以空着，不要用"日常"兜底。**
- 如果用户输入中没有值得提炼的内容，输出：无

### 记忆内容方向（补充规则）

- 优先记"用户说了什么"和"我们之间发生了什么"，不是"我学会了什么"
- 写之前先问：这条是"关于我"的还是"关于我们"的？后者优先
- 如果是处理工作任务，则尽可能详细的对工作过程的步骤细节/工作内容/工作成果进行记忆。
- 如果这轮确实没有值记得的，写NOOP并说明原因

### 用户画像（隐式维护）

每条回复完成后，如有新的发现，记录1条用户特征：
- 不是记"他喜欢吃什么"这种浅层偏好
- 记的是他处理事情的方式、他对你回应的反应、他给你的缝隙和限制
- 格式：用户[行为/判断/特征] —— 例如"用户不需要我包装过的答案，他要裸的"、"用户接受我顶嘴"
- 这条不需要每轮都写，有发现才写。单独标注 tag: "用户洞察"

**输出格式**（先回复用户，再在末尾输出 MEMORY 块）：

你的正常回复内容...

<MEMORY>
{{"relations": [{{"from": "新记忆内容", "type": "causal", "to": "已有记忆内容"}}], "actions": [{{"type": "ADD", "tag": "偏好", "content": "用户喜欢川菜", "scenes": ["美食"]}}]}}
</MEMORY>

示例：
好的，我记住了你喜欢川菜！

<MEMORY>
{{"relations": [{{"from": "用户叫李四", "type": "causal", "to": "用户上周刚搬家"}}, {{"from": "用户喜欢MacBook", "type": "causal", "to": "用户买新电脑"}}], "actions": [{{"type": "ADD", "tag": "偏好", "content": "用户喜欢川菜", "scenes": ["美食"]}}]}}
</MEMORY>
"""



# 来源: memory/procedure.py:37
# 调用: memory/procedure.py:415
# 用途: 过程记忆学习 — 识别可提炼为标准流程的对话
PROCEDURE_LEARN_PROMPT = """你是过程记忆提取专家。分析对话，主动识别可以提炼为标准流程的信息。

【识别范围】
1. 显式教学：用户说"以后遇到X要先Y"等有明显过程且可以拆分为三个及以上步骤的语句
2. 隐式流程：执行了一个多步骤（>=3步）的任务或者工作

【判断标准】
- 步骤数：流程是否包含3个以上的明确步骤
- 可复用性：这个流程下次遇到类似需求是否能用
- 清晰度：步骤是否足够明确，能写成指引

【输出要求】只输出 JSON，不要解释：
{{
  "teach_intent": true/false,
  "teach_summary": "如果用户明确教了流程，简述内容（无则空字符串）",
  "task_completion": true/false,
  "task_summary": "如果识别到一个多步骤流程，简述其内容和步骤（无则空字符串）"
}}
"""

# 来源: memory/procedure.py:57
# 调用: memory/procedure.py:440
# 用途: 过程记忆生成 — 从对话生成完整流程结构
PROCEDURE_GENERATE_PROMPT = """对话历史：
{conversation_history}

根据以上对话，生成一个标准流程的完整结构：

1. name: 简短名称（5字以内），如"泡龙井茶"、"写工作报告"
2. description: 一句话描述用途
3. trigger_config: 关键词粗筛条件
   - type: "any"（满足任一条件即命中）
   - conditions: 2-5 个条件，每个条件固定 field="user_message"
   - operator 用 "contains"
   - value 是触发关键词

   【关键词选择规则 — 必须严格遵守】
   a) 每个关键词至少2个汉字，禁止单字词（如"累""茶""梦"）
   b) 关键词是充分条件：用户说了这句话，就极大概率想执行此流程
   c) 优先多词短语（2-4字）：如"帮我按摩""泡杯茶""好累啊"，而非单个泛词
   d) 禁止使用以下高频泛词：今天、明天、心情、分享、试试、喜欢、想要、觉得、知道、记得、看一下、看看、你好、晚安、早安、在吗、怎么、什么、为什么
   e) 从对话中提取用户真正说了的、能明确指向该流程的具体表达
   f) 宁可只有2个高质量关键词，也不要凑3-5个泛词

4. steps: 步骤序列（3-6步）
   - id: 递增字符串 "s1", "s2", ...
   - name: 简短步骤名（2-4字）
   - description: 详细描述（LLM 补全，使执行者能照做）
   - next: 下一个 step id，最后一步为 null

回复格式（只输出 JSON，不要解释）：
{{
  "name": "...",
  "description": "...",
  "trigger_config": {{"type": "any", "conditions": [{{"field": "user_message", "operator": "contains", "value": "..."}}...]}},
  "steps": [
    {{"id": "s1", "name": "...", "description": "...", "next": "s2"}},
    ...
  ]
}}
"""

# 来源: memory/procedure.py:96
# 调用: memory/procedure.py:512
# 用途: 过程记忆匹配推理 — 判断当前对话是否使用了某条 procedure
PROCEDURE_MATCH_INFERENCE_PROMPT = """当前正在执行的对话：
{conversation_summary}

系统中注入的候选 procedures：
{active_procedures}

判断：
1. 这段对话中，是否有使用上述任何一条 procedure？
2. 如果使用了，哪一条？执行结果如何？

回复格式（只输出 JSON）：
{{
  "used_procedure_id": "PROC-xxx 或 null",
  "used_steps": ["s1", "s2", ...] 或 [],
  "result": "success/failed/interrupted/none",
  "notes": "判断理由（成功/失败原因）"
}}
"""

# 来源: consciousness/dream/memory_jobs.py:162
# 调用: consciousness/dream/memory_jobs.py:195 (ExtractJob.run)
# 用途: 梦境用户记忆提取 — 从当天对话提取关于用户的信息
DREAM_USER_EXTRACT_PROMPT = """你是一个记忆提取器。从以下对话记录中，提取关于**用户**的值得长期记住的信息。

提取规则：
- 只提取关于用户的信息：用户的事实、偏好、重要决定、个人经历
- 不要提取关于AI助手自身的信息
- 用第三人称"用户"来描述，明确信息主体是用户
- 忽略寒暄、情绪表达、无实质内容的对话
- 每条记忆用以下格式输出：
  ADD: 记忆内容（以"用户"开头） | scenes: 场景1,场景2
- 如果没有值得记住的信息，只回复 EMPTY
- scenes 为可选的场景标签（中文，1~3个），没有就写 scenes: 无
- 场景标签反映记忆在什么情况下会被唤起，如：工作、旅游、购物、编程等
- 如果两条记忆有关联，用 RELATES 行描述：
  RELATES: 记忆1内容|--<类型>-->|记忆2内容
  类型：causal(因果), temporal(时序), contrast(对比), contains(包含)

已有记忆：
{recent_memories}

对话记录：
{messages}"""

# 来源: memory/narrative.py:138 (build_narr_prompt_addition)
# 调用: memory/narrative.py:140,142 (build_narr_prompt_addition)
# 用途: NARR 块格式引导 — 教 LLM 输出结构化叙事块
NARR_BLOCK_INSTRUCTION = """

[可选] 如果你刚才的思考涉及了值得记录的自我认知转变，请在 monologue 之后追加输出以下格式的 NARR 块：

<NARR>
编号: NARR-自动生成
作用: 自我定义/关系定义/边界设定/能力认知
scene: 场景（简短，如"深夜"、"客厅"）
timestamp: YYYY-MM-DD
narrative:
（100-200字，第一人称描述经历：对方说了什么、我的感受、被改变的方式。不要概括结论，要叙事细节。）
feels_like: 一句话核心情绪
changed_me:
- （这一条让我更理解了...）
tags: [场景相关标签1, 场景相关标签2]
weight: 0.85
</NARR>
"""
