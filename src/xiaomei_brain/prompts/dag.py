# 来源: memory/dag.py:545
# 调用: memory/dag.py:550
# 用途: DAG 节点摘要，输出简洁总结
DAG_SUMMARIZE_PROMPT = """请用简洁的几句话总结以下对话，每句一个核心信息，用第三人称。
只写事实，不写推测或风险提示。不超过200字。

{content}
"""
