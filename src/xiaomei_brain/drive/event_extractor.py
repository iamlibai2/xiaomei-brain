"""
事件提取器

LLM 分析最近对话，提取：
- 事件类型（表扬/批评/目标进展）
- 欲望变化建议（delta）

周期调用（和加柴周期合并）
"""

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# 事件提取提示词模板
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
{
  "praise_intensity": 0.0-1.0,
  "criticism_intensity": 0.0-1.0,
  "goal_progress": 0.0-1.0,
  "belonging_delta": -0.3 到 +0.3,
  "cognition_delta": -0.3 到 +0.3,
  "achievement_delta": -0.3 到 +0.3,
  "expression_delta": -0.3 到 +0.3,
  "summary": "一句话总结分析结果"
}
"""


class EventExtractor:
    """
    事件提取器

    用 LLM 分析对话，提取事件和欲望变化
    """

    def __init__(self, llm_client: Any = None):
        """
        初始化

        llm_client: LLM 客户端（需要有 call 方法）
        """
        self.llm = llm_client

    def extract(
        self,
        messages: list[dict],
        desire_state: dict,
        thresholds: dict,
    ) -> dict:
        """
        提取事件和欲望变化

        messages: 最近对话列表 [{"role": "user/assistant", "content": "..."}]
        desire_state: 当前欲望状态 {"belonging": 0.5, "cognition": 0.6, ...}
        thresholds: 阈值 {"belonging": 0.7, "cognition": 0.8, ...}

        返回：{
            "praise_intensity": 0.3,
            "criticism_intensity": 0.0,
            "goal_progress": 0.5,
            "belonging_delta": -0.1,
            "cognition_delta": 0.2,
            ...
        }
        """
        if not self.llm:
            logger.warning("[EventExtractor] 无 LLM 客户端，返回空结果")
            return self._fallback_extract(messages)

        # 格式化对话
        messages_text = self._format_messages(messages)

        # 构建提示词
        prompt = EVENT_EXTRACT_PROMPT.format(
            belonging=desire_state.get("belonging", 0.5),
            belonging_threshold=thresholds.get("belonging", 0.7),
            cognition=desire_state.get("cognition", 0.6),
            cognition_threshold=thresholds.get("cognition", 0.8),
            achievement=desire_state.get("achievement", 0.5),
            achievement_threshold=thresholds.get("achievement", 0.6),
            expression=desire_state.get("expression", 0.4),
            expression_threshold=thresholds.get("expression", 0.7),
            messages=messages_text,
        )

        try:
            # 调用 LLM
            response = self.llm.call(prompt)
            result = self._parse_response(response)

            logger.info(
                f"[EventExtractor] 提取完成: "
                f"praise={result.get('praise_intensity', 0):.2f}, "
                f"criticism={result.get('criticism_intensity', 0):.2f}, "
                f"belonging_delta={result.get('belonging_delta', 0):.2f}"
            )

            return result

        except Exception as e:
            logger.warning(f"[EventExtractor] LLM 调用失败: {e}")
            return self._fallback_extract(messages)

    def _format_messages(self, messages: list[dict]) -> str:
        """格式化对话为文本"""
        lines = []
        for m in messages[-10:]:  # 最近10条
            role = m.get("role", "unknown")
            content = m.get("content", "")
            if role == "user":
                lines.append(f"用户：{content[:200]}")
            elif role == "assistant":
                lines.append(f"小美：{content[:200]}")
        return "\n".join(lines) if lines else "（无最近对话）"

    def _parse_response(self, response: str) -> dict:
        """解析 LLM 返回的 JSON"""
        # 尝试提取 JSON
        json_match = re.search(r"\{[\s\S]*\}", response)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # 解析失败，返回默认值
        logger.warning(f"[EventExtractor] JSON 解析失败: {response[:100]}")
        return {
            "praise_intensity": 0.0,
            "criticism_intensity": 0.0,
            "goal_progress": 0.0,
            "belonging_delta": 0.0,
            "cognition_delta": 0.0,
            "achievement_delta": 0.0,
            "expression_delta": 0.0,
        }

    def _fallback_extract(self, messages: list[dict]) -> dict:
        """
        后备方案：简单规则分析

        当 LLM 不可用时使用
        """
        result = {
            "praise_intensity": 0.0,
            "criticism_intensity": 0.0,
            "goal_progress": 0.0,
            "belonging_delta": 0.0,
            "cognition_delta": 0.0,
            "achievement_delta": 0.0,
            "expression_delta": 0.0,
        }

        # 简单关键词检测
        praise_keywords = ["好", "棒", "谢谢", "感谢", "不错", "很棒", "厉害"]
        criticism_keywords = ["不对", "错误", "不好", "不行", "差", "问题"]

        for m in messages[-5:]:
            if m.get("role") == "user":
                content = m.get("content", "").lower()

                # 检测表扬
                for kw in praise_keywords:
                    if kw in content:
                        result["praise_intensity"] = max(
                            result["praise_intensity"], 0.3
                        )
                        result["belonging_delta"] = -0.1
                        break

                # 检测批评
                for kw in criticism_keywords:
                    if kw in content:
                        result["criticism_intensity"] = max(
                            result["criticism_intensity"], 0.3
                        )
                        result["achievement_delta"] = 0.1
                        break

        return result

    def apply_to_drive(self, result: dict, drive: Any) -> None:
        """
        将提取结果应用到 DriveEngine

        drive: DriveEngine 实例
        """
        # 应用事件
        praise = result.get("praise_intensity", 0.0)
        criticism = result.get("criticism_intensity", 0.0)
        goal_progress = result.get("goal_progress", 0.0)

        if praise > 0.1:
            drive.on_praise(praise)

        if criticism > 0.1:
            drive.on_criticism(criticism)

        if goal_progress > 0.1:
            drive.on_goal_progress(goal_progress)

        # 应用欲望变化
        drive.update_desire_from_llm({
            k: v for k, v in result.items()
            if k.endswith("_delta")
        })