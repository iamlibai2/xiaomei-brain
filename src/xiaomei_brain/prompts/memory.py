# 来源: memory/extractor.py
# 调用: memory/extractor.py:247
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
# 调用: 追加到 system prompt
# 用途: 记忆决策格式指令
MEMORY_DECISION_PROMPT = """

## 记忆决策

**重要：请先正常回复用户，回复完成后，再在末尾输出 MEMORY 块。**

判断是否需要提取相关的长期记忆。

**规则**：
- 只从用户输入中提取，不要从你的回复中提取
- 关于用户的事实、偏好、经历用"用户..."
- 关于你学到的经验、教训、决策、新认知用"我..."
- 如果新记忆与已有记忆有语义关联，在 relations 字段建立关联
- 关系类型: causal(因果), temporal(时序), contrast(对比), contains(包含)
- 判断处理方式：ADD（全新）、UPDATE（更新旧记忆）、MERGE（合并同类）、NOOP（无意义/重复/推测）
- 如果用户输入中没有值得提炼的内容，输出：无

**输出格式**（先回复用户，再在末尾输出 MEMORY 块）：

你的正常回复内容...

<MEMORY>
{{"relations": [{{"from": "新记忆内容", "type": "causal", "to": "已有记忆内容"}}], "actions": [{{"type": "ADD", "tag": "偏好", "content": "用户喜欢川菜"}}]}}
</MEMORY>


示例：
好的，我记住了你喜欢川菜！

<MEMORY>
{{"relations": [{{"from": "用户叫李四", "type": "causal", "to": "用户上周刚搬家"}}, {{"from": "用户喜欢MacBook", "type": "causal", "to": "用户买新电脑"}}], "actions": [{{"type": "ADD", "tag": "偏好", "content": "用户喜欢川菜"}}]}}
</MEMORY>
"""
