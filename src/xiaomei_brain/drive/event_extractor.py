"""
事件提取器 —— 已废弃

功能已合并到 Consciousness.tick_L2() 中：
- 一次 LLM 调用同时产出意识涌现 + 驱动事件（表扬/批评/欲望变化）
- 通过 ---EVENTS--- 分隔符分离两部分产出
- Consciousness._apply_drive_events() 解析 JSON 并应用到 DriveEngine

保留此文件便于参考，后续集中清理时删除。

原设计：LLM 独立分析最近对话，提取事件类型和欲望变化建议。
"""

# 废弃代码（后续集中清理）：
#
# import json
# import logging
# import re
# from typing import Any
#
# from xiaomei_brain.prompts import EVENT_EXTRACT_PROMPT
#
# logger = logging.getLogger(__name__)
#
#
# class EventExtractor:
#     """
#     事件提取器
#
#     用 LLM 分析对话，提取事件和欲望变化
#     """
#
#     def __init__(self, llm_client: Any = None):
#         self.llm = llm_client
#
#     def extract(self, messages: list[dict], desire_state: dict, thresholds: dict) -> dict:
#         ...
#
#     def _format_messages(self, messages: list[dict]) -> str:
#         ...
#
#     def _parse_response(self, response: str) -> dict:
#         ...
#
#     def _fallback_extract(self, messages: list[dict]) -> dict:
#         ...
#
#     def apply_to_drive(self, result: dict, drive: Any) -> None:
#         ...
