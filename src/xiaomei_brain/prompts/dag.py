# 来源: memory/dag.py
# 调用: memory/dag.py:605 (_llm_summarize)
# 用途: DAG 叶子摘要（压缩原始消息）

DAG_SUMMARIZE_PROMPT = """请总结以下对话，保留问答关系，用第三人称。

要求：
1. 先列出关键主题词（3-5个，逗号分隔），格式：主题词：xxx, xxx, xxx
2. 每段对话总结为"问：... 答：..."的格式，保留核心信息
3. 只写事实，不推测
4. 不超过300字

{content}
"""

# 来源: memory/dag.py
# 调用: memory/dag.py:231 (promote -> _llm_summarize)
# 用途: DAG 上层摘要（合并多个子摘要）

DAG_PROMOTE_PROMPT = """请合并以下多条对话摘要，提取更高层次的概括。

要求：
1. 提取共同主题词（3-5个），格式：主题词：xxx, xxx, xxx
2. 保留每条摘要的核心信息，去重但不丢失差异
3. 如果多条摘要讨论同一话题，合并为一条叙述
4. 不超过300字

{content}
"""
