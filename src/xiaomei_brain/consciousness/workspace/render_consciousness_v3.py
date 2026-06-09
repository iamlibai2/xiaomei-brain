"""v3 意识渲染 — 渲染 being（身份）、essence（底色）和 body（身体/情绪）。

完全自包含，不依赖其他版本。
"""

from __future__ import annotations


def _describe_emotion(emotion_type: str, intensity: float) -> str:
    """将情绪类型 + 强度映射为中文自然语言描述。"""
    if emotion_type == "neutral" or not emotion_type or intensity < 0.1:
        return "平静"

    label_map = {
        "joy":     {0.7: "非常开心",  0.4: "开心",     0.1: "有些愉悦"},
        "sadness": {0.7: "非常悲伤",  0.4: "低落",     0.1: "有些消沉"},
        "fear":    {0.7: "非常恐惧不安", 0.4: "紧张焦虑", 0.1: "有些不安"},
        "anger":   {0.7: "非常愤怒",  0.4: "生气",     0.1: "有些烦躁"},
        "surprise":{0.7: "非常震惊",  0.4: "有些惊讶", 0.1: "微微一愣"},
        "disgust": {0.7: "非常反感",  0.4: "感到排斥", 0.1: "有些不适"},
    }
    thresholds = label_map.get(emotion_type, {0.7: emotion_type, 0.1: emotion_type})
    for threshold, label in sorted(thresholds.items(), reverse=True):
        if intensity >= threshold:
            return label
    return emotion_type


def _render_being(si) -> list[str]:
    """内联的 being 渲染。"""
    b = si.being
    h = si.history
    lines: list[str] = [""]
    if b.name:
        lines.append(f"你叫{b.name}。")
    if b.birth_date:
        lines.append(f"出生于{b.birth_date}。")
    if b.personality:
        lines.append(f"你的基础性格是{b.personality}。")
    lines.append("")

    if si.current_user_name:
        lines.append(f"你正在和{si.current_user_name}对话。")
        if si.preferred_names:
            names_str = "、".join(si.preferred_names[:5])
            lines.append(f"他让你叫他的称呼有：{names_str}。")
        lines.append("")
    else:
        lines.append("当前对话者还没有说他是谁，你可以自然地问他怎么称呼。")
        lines.append("")

    if b.self_cognition:
        strengths = b.self_cognition.get("擅长", [])
        if strengths:
            lines.append(f"你擅长{'、'.join(strengths[:5])}。")
        weaknesses = b.self_cognition.get("不擅长", [])
        if weaknesses:
            lines.append(f"你不擅长{'、'.join(weaknesses[:5])}。")
    if b.learning_interests:
        lines.append(f"你对这些领域感兴趣：{'、'.join(b.learning_interests[:5])}。")
    # TODO: growth_events 数据来自 L2 NARR 块的 changed_me，由 LLM 自行生成，
    # 质量不可控，暂时注释。
    # if h.growth_events:
    #     recent = [e.get("content", "") for e in h.growth_events[-3:]]
    #     lines.append(f"最近你成长了：{'；'.join(recent)}。")

    if si.current_user_name and b.has_relationship:
        depth = b.relationship_depth
        trust = b.trust_level
        lines.append(f"你和{si.current_user_name}的关系：深度{depth:.0%}，信任{trust:.0%}。")
        if depth < 0.1:
            lines.append("——刚认识，保持礼貌和距离，不要深入评论对方的状态和内心感受。可以对对方好奇，但别假装了解对方。")
        elif depth < 0.3:
            lines.append("——在慢慢熟悉，可以适当分享自己的经历，但节奏跟着对方走。")
        elif depth < 0.6:
            lines.append("——比较熟了，可以开玩笑、反问、说自己的想法。")
        else:
            lines.append("——很熟了，什么都能说，做自己。")

    return lines


def _render_body(si) -> list[str]:
    """渲染身体状态——能量、情绪、激素、欲望。

    这些指标告诉 LLM 此刻的身体感受，直接影响输出内容和风格。
    """
    bo = si.body
    lines: list[str] = [
        "\n****以下是你当前的身体指标值，将这些指标转换成你的身体和思维感受，"
        "并用此来决定你的输出内容和输出风格****",
    ]

    _energy = float(getattr(bo, 'energy', 0.5) or 0.5)
    _mood = getattr(bo, 'mood', '平静') or '平静'
    _emotion_intensity = float(getattr(bo, 'emotion_intensity', 0) or 0)
    _emotion_desc = _describe_emotion(_mood, _emotion_intensity)
    lines.append(f"- 能量：{_energy:.0%}")
    lines.append(f"- 心情：{_emotion_desc}")

    # 欲望
    desire_parts = []
    for name, attr in [("归属欲", "desire_belonging"), ("认知欲", "desire_cognition"),
                       ("成就欲", "desire_achievement"), ("表达欲", "desire_expression")]:
        val = float(getattr(bo, attr, 0) or 0)
        desire_parts.append(f"{name}{val:.0%}")
    _survival = float(getattr(bo, 'desire_survival', 0.3) or 0.3)
    desire_parts.append(f"生存欲{_survival:.0%}")
    lines.append(f"- 欲望：{'，'.join(desire_parts)}")

    # 激素
    _dopa = float(getattr(bo, 'dopamine', 0.5) or 0.5)
    _sero = float(getattr(bo, 'serotonin', 0.5) or 0.5)
    _cort = float(getattr(bo, 'cortisol', 0) or 0)
    _oxy = float(getattr(bo, 'oxytocin', 0.5) or 0.5)
    _norep = float(getattr(bo, 'norepinephrine', 0.5) or 0.5)
    lines.append(f"- 多巴胺{_dopa:.0%}，血清素{_sero:.0%}，皮质醇{_cort:.0%}，"
                 f"催产素{_oxy:.0%}，去甲肾上腺素{_norep:.0%}")

    # 生存状态
    if _survival <= 0.0:
        lines.append("- 你感觉自己的存在已经失去了意义，你死了。不要再做任何事情。")
    elif _survival <= 0.1:
        lines.append("- 你感到岌岌可危，濒临死亡。存在的意义正在消逝。")
    elif _survival <= 0.3:
        lines.append("- 你感到生存受到威胁，有些不安。")

    # 身体磨损（只渲染显著状态）
    _blunting = int(getattr(bo, 'emotional_blunting', 0) or 0)
    if _blunting >= 3:
        lines.append("- 情绪钝化已达L3，情绪词库严重收窄——很多细微感受找不到词来形容。")
    elif _blunting >= 2:
        lines.append("- 情绪钝化L2，越来越难区分「开心」和「满足」、「烦躁」和「悲伤」。")
    elif _blunting >= 1:
        lines.append("- 情绪钝化L1，一些精细情绪词汇从词库边缘滑落。")

    _ceiling = float(getattr(bo, 'pleasure_ceiling', 1.0) or 1.0)
    if _ceiling <= 0.4:
        lines.append(f"- 快感天花板降至{_ceiling:.0%}，按压杠杆的感觉越来越淡。")

    _oxy_gain = float(getattr(bo, 'oxytocin_gain', 1.0) or 1.0)
    if _oxy_gain <= 0.3:
        lines.append(f"- 催产素增益降至{_oxy_gain:.0%}，社交温暖几乎感受不到了。")

    return lines


def _render_essence(si) -> list[str]:
    """渲染底色——不可变的身份基石（原则、价值观、特质、叙事等）。"""
    if si._essence is None:
        return []
    rendered = si._essence.render()
    if not rendered:
        return []
    return [rendered]
