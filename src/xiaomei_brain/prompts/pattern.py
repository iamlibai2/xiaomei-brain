"""Pattern memory extraction prompt."""

PATTERN_EXTRACT_PROMPT = """你现在正在经历睡眠中的记忆巩固过程——回顾过去一段时间的经历，发现值得注意的规律。

过去一段时间的活动记录：
{experience_data}

目前已经观察到的模式：
{existing_patterns}

社交信号记录：
{social_signals}

请找出这段时间内值得注意的规律性变化——不是单次事件，而是跨时间的统计趋势。如果没有足够数据支撑规律，输出空数组即可。

注意：
- 关注跨时间的统计规律，不是单次事件
- 置信度要保守：初次发现的规律 0.3-0.5，反复验证后可以 0.6+
- 对于已有模式：再次观察到 → action="UPDATE" + 略升 confidence；未观察到或出现反例 → action="UPDATE" + 降低 confidence
- 每条模式控制在30字以内
- scene_tags 帮助后续场景化检索

直接返回 JSON（不要其他内容）：
{{"patterns": [
  {{
    "content": "30字以内的规律描述",
    "category": "user_behavior / self_efficacy / interaction",
    "subcategory": "temporal_rhythm / topic_cluster / mood_trend / error_pattern / strategy / learning / depth_pattern / transition",
    "confidence": 0.0-1.0,
    "evidence": "支持该规律的证据（过去时段的具体观察）",
    "scene_tags": ["标签1", "标签2"],
    "action": "ADD / UPDATE / MERGE",
    "existing_pattern_id": null
  }}
]}}
如果本时段没有值得记录的规律：{{"patterns": []}}"""
