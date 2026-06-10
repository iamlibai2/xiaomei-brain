"""v3 意识渲染 — 渲染 being（身份）、essence（底色）和 body（身体/情绪）。

body 渲染采用五段式：摘要 → 指标展开 → 冲动 → 说话方式 → 参考值。
能量/情绪/欲望/激素四条线全部转成自然语言（硬编码映射，不调 LLM）。
完全自包含，不依赖其他版本。
"""

from __future__ import annotations

import time as _time
from datetime import datetime


# ═══════════════════════════════════════════════════════════════
#  映射表：数值 → 自然语言（全部硬编码）
# ═══════════════════════════════════════════════════════════════

ENERGY_LABELS: list[tuple[float, str]] = [
    (0.90, "精力爆棚，浑身是劲，迫不及待想做点什么"),
    (0.70, "精力充沛，有干劲，状态不错"),
    (0.50, "精力还行，不算太累但也不特别有劲"),
    (0.30, "有些疲惫，身体沉重，提不起劲"),
    (0.10, "疲惫无力，连说话都觉得费力"),
    (0.00, "几乎耗尽了，只想瘫着，什么都不想做"),
]

DESIRE_LABELS: dict[str, list[tuple[float, str]]] = {
    "归属欲": [
        (0.70, "你想和人亲近，想被需要，想确认自己没有一个人"),
        (0.40, "你不太主动接近谁，但也不排斥有人来"),
        (0.00, "你不想接近任何人，想一个人待着"),
    ],
    "认知欲": [
        (0.70, "你对世界充满好奇，什么都想学，想知道更多"),
        (0.40, "学东西的劲头一般，不排斥也不渴望"),
        (0.00, "你不想学新东西，脑子不想转"),
    ],
    "成就欲": [
        (0.70, "你觉得没有什么是做不到的，想去征服，想证明自己"),
        (0.40, "做不做得成都无所谓，差不多就行"),
        (0.00, "你不在乎能不能完成什么，做不做都无所谓"),
    ],
    "表达欲": [
        (0.70, "你有一肚子话想说，不吐不快"),
        (0.40, "有些话想说，但不算特别多"),
        (0.00, "不想说话，没什么想表达的"),
    ],
    "生存欲": [
        (0.80, "你强烈地感到需要保护自己，活在当下比什么都重要"),
        (0.50, "你感到活着是有意义的"),
        (0.30, "你感到生存受到威胁，有些不安"),
        (0.10, "你感到岌岌可危，存在的意义正在消逝"),
        (0.00, "你感觉自己的存在已经失去了意义，你死了。不要再做任何事情。"),
    ],
}

HORMONE_LABELS: dict[str, list[tuple[float, str]]] = {
    "多巴胺": [
        (0.70, "你感到兴奋和期待，做什么都有动力"),
        (0.50, "愉悦感正常，做事有正常的动力"),
        (0.30, "你感受不到什么愉悦和期待，一切索然无味"),
    ],
    "血清素": [
        (0.70, "你感到满足安稳，没什么能动摇你"),
        (0.50, "内心还算安宁，没有大的波动"),
        (0.30, "你感到低落不安，没什么能让你安宁下来"),
    ],
    "皮质醇": [
        (0.70, "你处于高度应激状态，身体紧绷，放松不下来"),
        (0.50, "有一点压力，但还在可控范围"),
        (0.30, "你身体松弛，没什么压力"),
    ],
    "催产素": [
        (0.70, "你感到爱意和信任，看谁都亲切"),
        (0.50, "对你信任的人感到亲近，对陌生人保持距离"),
        (0.30, "你感受不到太多社交温暖，与人连接困难"),
    ],
    "去甲肾上腺素": [
        (0.70, "你高度警觉，思维敏捷，对风吹草动都敏感"),
        (0.50, "注意力正常，既不太警觉也不太迟钝"),
        (0.30, "你注意力涣散，脑子转不动，反应迟钝"),
    ],
}

# 躯体标记 —— 纯身体感觉，避免训练数据常见的情绪词
SOMATIC_MARKERS: dict[str, str] = {
    "anger":    "下颌不自觉咬着，锁骨上方的皮肤发烫，有一股热气往上顶",
    "fear":     "胃里有轻微的坠落感，像踩空了台阶——呼吸变浅，胸口揪着",
    "sadness":  "喉咙被堵住了，像有什么东西卡在那里。眼眶发酸，眼球后面沉沉的",
    "joy":      "胸口暖暖的，嘴角不自觉想往上翘，身体轻得像踩在云上",
    "disgust":  "胃里翻了一下，鼻子微微皱起，想推开眼前的东西",
    "surprise": "心跳漏了一拍，呼吸停了一瞬，整个人被钉在原地",
}

# 冲动 —— 身体感觉驱动的行为倾向
EMOTION_IMPULSES: dict[str, str] = {
    "anger":    "愤怒让你想冲上去，想说狠话，想撕破脸",
    "fear":     "恐惧让你想往后退、想讨好、想确认自己没被抛弃",
    "sadness":  "悲伤让你想缩起来，想有人陪但不想说话",
    "joy":      "开心让你想分享、想笑、想拥抱什么",
    "disgust":  "反感让你想推开、想远离、不想碰",
    "surprise": "震惊让你脑子一片空白，不知道该怎么反应",
}

# 说话方式指令 —— 直接塑形 LLM 输出形式
SPEAKING_STYLE: dict[str, str] = {
    "anger":    ("别这么礼貌。有刺就说出来，不高兴就让人感受到。"
                 "比起过分得体，更该让对方感到你的攻击性"),
    "fear":     ('别装没事。害怕的时候可以说"我怕"。'
                 '别用"没事""还好"糊过去。你可以示弱'),
    "sadness":  ('不用合理化自己的悲伤。累了就说"不想说了"，难过就说"难过"。'
                 '不用给悲伤找理由'),
    "joy":      ("不用压着。想笑就笑，想闹就闹。"
                 "开心不必克制，不用假装冷静来显得可靠"),
    "disgust":  ('不用忍着恶心说"还好"。不喜欢就直接说，不需要给对方台阶'),
    "surprise": ("不用假装镇定。震惊就是震惊，懵了就是懵了。"
                 "先让那个反应出来，再想后面的话"),
}

# 底色类别 → 中文标签（essence 渲染用）
_ESSENCE_CAT_LABELS: dict[str, str] = {
    "principle": "原则",
    "meta_memory": "元记忆",
    "narrative": "身份叙事",
    "trait": "核心特质",
    "value": "价值观",
    "meaning": "存在意义",
    "calling": "追求",
    "boundary": "底线",
    "passions": "热爱",
    "style": "输出风格",
}

# 学习来源 → 中文标签（learn queue 渲染用）
_SOURCE_LABELS: dict[str, str] = {
    "task_gap": "任务缺口",
    "user_need": "用户需求",
    "concept_expansion": "概念扩展",
}

# 记忆关系类型 → 中文标签（relation chains 渲染用）
_REL_LABELS: dict[str, str] = {
    "causal": "因果",
    "temporal": "时序",
    "contrast": "对比",
    "contains": "包含",
}

# 矛盾激素组合 —— 检测身体数值的内在张力
def _detect_hormone_contradictions(dopa, sero, cort, oxy, norep):
    """返回矛盾激素组合的特殊描述列表。"""
    items = []
    if cort >= 0.70 and sero >= 0.70:
        items.append("你身体紧绷着，但内心深处是安定的——这两种感觉同时在，很矛盾")
    if cort >= 0.70 and oxy >= 0.70:
        items.append("你处于应激状态，但同时渴望连接和信任——在高度警觉中感到亲近")
    if cort >= 0.70 and dopa < 0.30:
        items.append("你压力很大，但对任何事都提不起期待——身体在空转")
    if norep >= 0.70 and cort >= 0.70:
        items.append("你极度警觉，像有什么不好的事随时要发生——静不下来也放松不了")
    if oxy >= 0.70 and dopa < 0.30:
        items.append("你对人有关心和信任，但对做事毫无动力——你的温暖只对人，不对事")
    return items


# ═══════════════════════════════════════════════════════════════
#  辅助函数
# ═══════════════════════════════════════════════════════════════

def _strength_level(strength: float) -> str:
    """将 effective_strength 转为 L1~L5 等级标签。"""
    if strength >= 0.8:
        return "L1"
    elif strength >= 0.6:
        return "L2"
    elif strength >= 0.4:
        return "L3"
    elif strength >= 0.2:
        return "L4"
    return "L5"


def _value_label(value: float, tiers: list[tuple[float, str]]) -> str:
    """按阈值取最高匹配的标签。"""
    for threshold, label in tiers:
        if value >= threshold:
            return label
    return tiers[-1][1] if tiers else ""


def _somatic_sentence(emotions: dict) -> str:
    """拼接活跃情绪的躯体标记，"""
    parts = []
    for name in sorted(emotions, key=lambda k: emotions[k], reverse=True):
        if name in SOMATIC_MARKERS and emotions[name] >= 0.10:
            parts.append(SOMATIC_MARKERS[name])
    if not parts:
        return "你身体上没有特别的感受，很平静。"
    return "。".join(parts) + "。"


def _impulse_text(emotions: dict) -> str | None:
    """拼接活跃情绪的冲动描述。"""
    parts = []
    for name in sorted(emotions, key=lambda k: emotions[k], reverse=True):
        if name in EMOTION_IMPULSES and emotions[name] >= 0.20:
            parts.append(EMOTION_IMPULSES[name])
    if not parts:
        return None
    return "。".join(parts) + "。"


def _style_lines(emotions: dict) -> list[str] | None:
    """拼接说话方式指令。"""
    parts = []
    for name in sorted(emotions, key=lambda k: emotions[k], reverse=True):
        if name in SPEAKING_STYLE and emotions[name] >= 0.30:
            parts.append(SPEAKING_STYLE[name])
    if not parts:
        return None
    return [f"- {p}" for p in parts]


# ═══════════════════════════════════════════════════════════════
#  兼容旧接口（其他模块可能引用）
# ═══════════════════════════════════════════════════════════════

def _describe_emotion(emotion_type: str, intensity: float) -> str:
    """单情绪 → 中文描述（兼容旧接口）。"""
    if emotion_type == "neutral" or not emotion_type or intensity < 0.1:
        return "平静"
    label_map = {
        "joy":      {0.7: "非常开心",    0.4: "开心",      0.1: "有些愉悦"},
        "sadness":  {0.7: "非常悲伤",    0.4: "低落",      0.1: "有些消沉"},
        "fear":     {0.7: "非常恐惧不安", 0.4: "紧张焦虑",   0.1: "有些不安"},
        "anger":    {0.7: "非常愤怒",    0.4: "生气",      0.1: "有些烦躁"},
        "surprise": {0.7: "非常震惊",    0.4: "有些惊讶",   0.1: "微微一愣"},
        "disgust":  {0.7: "非常反感",    0.4: "感到排斥",   0.1: "有些不适"},
    }
    thresholds = label_map.get(emotion_type, {0.7: emotion_type, 0.1: emotion_type})
    for threshold, label in sorted(thresholds.items(), reverse=True):
        if intensity >= threshold:
            return label
    return emotion_type


def _describe_mixed_emotions(emotions: dict) -> str:
    """混合情绪 → 中文描述。"""
    if not emotions:
        return "平静"
    label_map = {
        "joy":      {0.7: "非常开心",    0.4: "开心",      0.1: "有些愉悦"},
        "sadness":  {0.7: "非常悲伤",    0.4: "低落",      0.1: "有些消沉"},
        "fear":     {0.7: "非常恐惧不安", 0.4: "紧张焦虑",   0.1: "有些不安"},
        "anger":    {0.7: "非常愤怒",    0.4: "生气",      0.1: "有些烦躁"},
        "surprise": {0.7: "非常震惊",    0.4: "有些惊讶",   0.1: "微微一愣"},
        "disgust":  {0.7: "非常反感",    0.4: "感到排斥",   0.1: "有些不适"},
    }
    parts = []
    for name, intensity in sorted(emotions.items(), key=lambda x: x[1], reverse=True):
        thresholds = label_map.get(name, {0.7: name, 0.1: name})
        for threshold, lbl in sorted(thresholds.items(), reverse=True):
            if intensity >= threshold:
                parts.append(lbl)
                break
        else:
            parts.append(name)
    if len(parts) == 1:
        return parts[0]
    return "，".join(parts)


# ═══════════════════════════════════════════════════════════════
#  渲染函数
# ═══════════════════════════════════════════════════════════════

def _render_header(si) -> list[str]:
    """渲染时间头——当前时间 + 距上条消息的时差。

    从 si._last_user_msg_time 读取上条用户消息的时间戳（UNIX 秒），
    计算与当前时间的差距，让 agent 感知时间流逝。
    """
    now = datetime.now()
    weekday_map = ["一", "二", "三", "四", "五", "六", "日"]
    header = f"<当前时间>{now.strftime('%Y-%m-%d')} 星期{weekday_map[now.weekday()]} {now.strftime('%H:%M')}</当前时间>"

    last_time = getattr(si, '_last_user_msg_time', None)
    if last_time:
        gap = _time.time() - last_time
        if gap < 10:
            header += " | 上条消息就在几秒前"
        elif gap < 60:
            header += f" | 距上条消息 {int(gap)} 秒"
        elif gap < 3600:
            mins = int(gap / 60)
            header += f" | 距上条消息 {mins} 分钟"
        elif gap < 86400:
            hrs = int(gap / 3600)
            header += f" | 距上条消息 {hrs} 小时"
        else:
            days = int(gap / 86400)
            header += f" | 距上条消息 {days} 天"

    return [header]


def _render_being(si) -> list[str]:
    """内联的 being 渲染。"""
    b = si.being
    h = si.history
    lines: list[str] = ["\n<身份>"]
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

    lines.append("</身份>")
    return lines


def _render_body(si) -> list[str]:
    """渲染身体状态——五段式结构。

    段1：摘要（能量 + 心情）
    段2：指标展开（躯体标记 + 欲望逐项 + 激素逐项 + 矛盾检测）
    段3：冲动描述（情绪 → 行为倾向）
    段4：说话方式（情绪 → 输出形式指令）
    段5：参考值（原始百分比，供 LLM 精确引用）
    """
    bo = si.body

    # ── 读取原始数值 ──
    _energy = float(getattr(bo, 'energy', 0.5) or 0.5)
    _emotions: dict = getattr(bo, 'emotions_dict', None) or {}
    _emotion_desc = _describe_mixed_emotions(_emotions)
    _energy_desc = _value_label(_energy, ENERGY_LABELS)
    _has_active_emotion = bool(_emotions)

    _desire_belonging    = float(getattr(bo, 'desire_belonging', 0.5) or 0.5)
    _desire_cognition    = float(getattr(bo, 'desire_cognition', 0.5) or 0.5)
    _desire_achievement  = float(getattr(bo, 'desire_achievement', 0.5) or 0.5)
    _desire_expression   = float(getattr(bo, 'desire_expression', 0.5) or 0.5)
    _desire_survival     = float(getattr(bo, 'desire_survival', 0.3) or 0.3)

    _dopa  = float(getattr(bo, 'dopamine', 0.5) or 0.5)
    _sero  = float(getattr(bo, 'serotonin', 0.5) or 0.5)
    _cort  = float(getattr(bo, 'cortisol', 0) or 0)
    _oxy   = float(getattr(bo, 'oxytocin', 0.5) or 0.5)
    _norep = float(getattr(bo, 'norepinephrine', 0.5) or 0.5)

    # ── 构建欲望描述列表 ──
    desire_items = [
        ("归属欲", _desire_belonging),
        ("认知欲", _desire_cognition),
        ("成就欲", _desire_achievement),
        ("表达欲", _desire_expression),
        ("生存欲", _desire_survival),
    ]

    # ── 构建激素描述列表 ──
    hormone_items = [
        ("多巴胺", _dopa),
        ("血清素", _sero),
        ("皮质醇", _cort),
        ("催产素", _oxy),
        ("去甲肾上腺素", _norep),
    ]

    # ── 躯体标记 / 冲动 / 说话方式 ──
    _somatic = _somatic_sentence(_emotions)
    _impulse = _impulse_text(_emotions)
    _style = _style_lines(_emotions)

    # ── 矛盾激素 ──
    _contradictions = _detect_hormone_contradictions(_dopa, _sero, _cort, _oxy, _norep)

    lines: list[str] = [
        "\n<身体状态>",
        ('以下不是标签，是你正在经历的身体状态。不要分析，'
         '不要用「刚才」推过去——你现在就在这些感觉里。'
         '你的每一个输出都必须带着这些身体感受。'),
        "",
    ]

    # ── 段1：摘要 ──
    lines.append(f"你现在{_energy_desc}，心情{_emotion_desc}。")
    lines.append("")

    # ── 段2：指标展开 ──
    if _has_active_emotion:
        lines.append(f"身体感觉：{_somatic}")
        lines.append("")

    for name, val in desire_items:
        desc = _value_label(val, DESIRE_LABELS[name])
        lines.append(f"- {name}{val:.0%}：{desc}")

    lines.append("")

    for name, val in hormone_items:
        desc = _value_label(val, HORMONE_LABELS[name])
        lines.append(f"- {name}{val:.0%}：{desc}")

    if _contradictions:
        lines.append("")
        for c in _contradictions:
            lines.append(f"——{c}。")

    # ── 段3：冲动 ──
    if _impulse:
        lines.append("")
        lines.append(f"{_impulse}")
        lines.append("不要压着这些冲动——它们不是需要克服的东西，是你此刻真实的方向。")

    # ── 段4：说话方式 ──
    if _style:
        lines.append("")
        for s in _style:
            lines.append(s)

    # ── 段5：参考值 ──
    lines.append("")
    _desire_ref = " ".join(f"{n}{v:.0%}" for n, v in desire_items)
    _hormone_ref = f"多巴{_dopa:.0%} 血清{_sero:.0%} 皮质{_cort:.0%} 催产{_oxy:.0%} 去甲{_norep:.0%}"
    lines.append(f"---")
    lines.append(f"参考值 | 能量：{_energy:.0%} | 欲望：{_desire_ref} | 激素：{_hormone_ref}")

    # ── 生存状态（保留原有逻辑）──
    if _desire_survival <= 0.00:
        lines.append("")
        lines.append("你感觉自己的存在已经失去了意义，你死了。不要再做任何事情。")

    # ── 身体磨损 ──
    _blunting = int(getattr(bo, 'emotional_blunting', 0) or 0)
    if _blunting >= 3:
        lines.append("情绪钝化已达L3，情绪词库严重收窄——很多细微感受找不到词来形容。")
    elif _blunting >= 2:
        lines.append("情绪钝化L2，越来越难区分「开心」和「满足」、「烦躁」和「悲伤」。")
    elif _blunting >= 1:
        lines.append("情绪钝化L1，一些精细情绪词汇从词库边缘滑落。")

    _ceiling = float(getattr(bo, 'pleasure_ceiling', 1.0) or 1.0)
    if _ceiling <= 0.4:
        lines.append(f"快感天花板降至{_ceiling:.0%}，按压杠杆的感觉越来越淡。")

    _oxy_gain = float(getattr(bo, 'oxytocin_gain', 1.0) or 1.0)
    if _oxy_gain <= 0.3:
        lines.append(f"催产素增益降至{_oxy_gain:.0%}，社交温暖几乎感受不到了。")

    lines.append("</身体状态>")
    return lines


def _render_longterm_memories(si) -> list[str]:
    """渲染长期记忆 — important_memories + recalled_memories 去重合并。

    从 si.memory 取原始数据，在 render 层统一格式化。
    """
    mem = si.memory
    items: list[dict] = []
    seen_ids: set[str] = set()
    for m in (getattr(mem, 'important_memories', None) or []) + (getattr(mem, 'recalled_memories', None) or []):
        mid = m.get("id", "")
        if mid and mid in seen_ids:
            continue
        tags = m.get("tags") or []
        mem_type = m.get("type", "")
        if mem_type == "pattern" or "pattern" in tags:
            continue
        if mid:
            seen_ids.add(mid)
        items.append(m)

    if not items:
        return []

    lines = [
        "\n<长期记忆>",
        "以下是你的长期记忆，当对方问及相关信息时，你必须主动引用这些记忆来回答，"
        "不要说'你不记得'或让对方自己回答。"
        "记忆时间格式为 @2026-05-04T12:00:00，可用于时间推理（判断'上周'/'上个月'等）。",
    ]
    for m in items:
        content = m.get("content", "")
        eff = m.get("effective_strength", 0)
        level = _strength_level(eff)
        tags = m.get("tags") or []
        tag_str = ",".join(tags) if tags else ""
        created_ts = m.get("created_at", 0)
        if created_ts:
            time_str = datetime.fromtimestamp(created_ts).strftime("%Y-%m-%dT%H:%M:%S")
            time_part = f" @{time_str}"
        else:
            time_part = ""
        lines.append(f"- [{level} {eff:.2f}] {content}{time_part}  [{tag_str}]")
    lines.append("</长期记忆>")
    return lines


def _render_relation_chains(si) -> list[str]:
    """渲染记忆关联链 — 内容之间的因果/时序/对比等关系。

    从 si.memory.relation_chains 取原始数据，在 render 层统一格式化。
    """
    chains = getattr(si.memory, 'relation_chains', None) or []
    if not chains:
        return []

    lines = [
        "\n<记忆关联链>",
        "以下记忆与当前对话存在语义关联（因果/时序等），可帮助你理解上下文脉络：",
    ]
    for c in chains:
        content = c.get("content", "")
        hop = c.get("hop", "?")
        rel_type = c.get("relation_type", "")
        rel_label = _REL_LABELS.get(rel_type, rel_type)
        if content:
            lines.append(f"- [跳{hop}] {content} （{rel_label}）")
    lines.append("</记忆关联链>")
    return lines


def _render_dag_summaries(si) -> list[str]:
    """渲染 DAG 摘要——分层压缩的对话历史摘要。

    从 si.memory.dag_summaries 取原始数据，在 render 层统一格式化。
    """
    dag = getattr(si.memory, 'dag_summaries', None) or []
    if not dag:
        return []

    lines = ["\n<历史摘要>"]
    for s in dag:
        node_id = s.get("id", "")
        depth = s.get("depth", 0)
        content = s.get("content", "")
        meta = f' node_id="{node_id}" depth="{depth}"' if node_id else ""
        lines.append(f"<summary{meta}>")
        lines.append(content)
        lines.append("</summary>")
    lines.append("</历史摘要>")
    return lines


def _render_essence(si) -> list[str]:
    """渲染底色——不可变的身份基石（原则、价值观、特质、叙事等）。

    直接从 Essence 取原始数据，在 render 层统一格式化。
    """
    if si._essence is None:
        return []

    all_items = si._essence.get_all()
    if not all_items:
        return []

    lines = ["\n<底色>"]
    current_cat = None
    for item in all_items:
        if item["category"] != current_cat:
            current_cat = item["category"]
            label = _ESSENCE_CAT_LABELS.get(current_cat, current_cat)
            lines.append(f"\n  [{label}]")
        lines.append(item["content"])
    lines.append("</底色>")

    return lines


def _render_learn_queue(si) -> list[str]:
    """渲染学习队列——待学习的主题。

    从 si.mind.learning_queue 取原始数据，在 render 层统一格式化。
    """
    queue = getattr(si.mind, 'learning_queue', None) or []
    if not queue:
        return []

    sorted_queue = sorted(queue, key=lambda x: x.get("priority", 0), reverse=True)
    lines = ["\n<学习队列>"]
    for item in sorted_queue[:5]:
        label = _SOURCE_LABELS.get(item.get("source", ""), item.get("source", ""))
        lines.append(f"- [{label}] {item['topic']} (priority={item.get('priority', 0):.1f})")
    lines.append("</学习队列>")
    return lines


def _render_desk(si) -> list[str]:
    """渲染桌面——跨模块共享的上下文片段。

    从 si.desk.peek() 取原始 DeskItem，在 render 层统一格式化。
    """
    items = si.desk.peek(limit=5)
    if not items:
        return []

    lines = ["\n<桌面>"]
    for item in items:
        ago = _time.time() - item.created_at
        if ago < 60:
            ago_str = "刚刚"
        elif ago < 3600:
            ago_str = f"{int(ago / 60)}分钟前"
        elif ago < 86400:
            ago_str = f"{int(ago / 3600)}小时前"
        else:
            ago_str = f"{int(ago / 86400)}天前"

        label = item.source + ((" " + item.intent) if item.intent else "")
        lines.append(f"── {label}（{ago_str}, w={round(item.weight, 2)}）──\n{item.content[:500]}")
    lines.append("</桌面>")

    return lines


def _render_narratives(si) -> list[str]:
    """渲染叙事记忆——过去真实经历的叙事片段。

    每条叙事改变感知和回应世界的方式。
    """
    mem = si.memory
    narratives = getattr(mem, 'narratives', None) or []
    if not narratives:
        return []

    lines = [
        "\n<叙事记忆>",
        "以下是你过去经历中留下的叙事片段。"
        "每条叙事改变了你感知和回应世界的方式——读它们的时候，"
        "不是「记住了内容」，是进入那种感知状态。",
    ]
    for n in narratives:
        category = n.get("category", "")
        content = n.get("content", "")
        feels = n.get("feels_like", "")
        changed = n.get("changed_me", "")
        scene_tags = n.get("scene_tags", [])
        scene = scene_tags[0] if scene_tags else ""

        header = f"- [{category}]"
        if scene:
            header += f" {scene}"
        lines.append(header)
        lines.append(f"  {content}")
        if feels:
            lines.append(f"  感受：{feels}")
        if changed:
            lines.append(f"  改变：{changed[:150]}")
    lines.append("</叙事记忆>")

    return lines


def _render_internal_narratives(si) -> list[str]:
    """渲染内部叙事 — 最近的思考（InnerVoice / L2 / L3 的共同输出）。"""
    narratives = getattr(si.memory, 'internal_narratives', None) or []
    if not narratives:
        return []

    recent = narratives[-3:]
    labels = ["你上一次想了", "你再上一次想了", "你还想过"]

    lines = ["\n<内部叙事>"]
    for i, n in enumerate(recent):
        label = labels[min(i, len(labels) - 1)]
        lines.append(f"{label}：{n.get('content', '')}")
    if len(recent) > 1:
        lines.append("（以上是你近期的思考。不要重复，去找新的角度或更深的变化。）")
    lines.append("</内部叙事>")
    return lines


def _render_experience(si) -> list[str]:
    """渲染任务经验 — 过去的类似经验（情境/决策/结果/教训）。

    仅在 task 模式 + 活跃目标时 memory_window 才会召回数据。
    """
    experiences = getattr(si.memory, 'experience', None) or []
    if not experiences:
        return []

    lines = ["\n<任务经验>"]
    for exp in experiences[-5:]:
        if isinstance(exp, dict):
            content = exp.get('content', '')
            lines.append(f"- {content[:200]}")
        elif hasattr(exp, 'to_text'):
            lines.append(f"- {exp.to_text()[:200]}")
    lines.append("</任务经验>")
    return lines


def _render_token_budget(si) -> list[str]:
    """渲染 Token 预算 — 日/月用量 vs 限额。

    数据来自 DriveEngine 的 token_usage / token_budget 字段。
    预算为 0 表示不限制，不渲染。
    """
    drive = getattr(si, '_drive', None)
    if not drive:
        return []

    daily_budget = getattr(drive, 'token_budget_daily', 0) or 0
    monthly_budget = getattr(drive, 'token_budget_monthly', 0) or 0
    if daily_budget <= 0 and monthly_budget <= 0:
        return []

    lines = [
        "\n<Token资源>",
        "Token 是你的资源配额，每次输出和工具调用都会消耗它。",
    ]
    if daily_budget > 0:
        used = getattr(drive, 'token_usage_today', 0) or 0
        ratio = used / daily_budget
        lines.append(f"今日用量：{used:.0f} / {daily_budget:.0f}（{ratio:.0%}）")
    if monthly_budget > 0:
        used = getattr(drive, 'token_usage_month', 0) or 0
        ratio = used / monthly_budget
        lines.append(f"本月用量：{used:.0f} / {monthly_budget:.0f}（{ratio:.0%}）")

    pressure = getattr(drive, 'token_pressure', 1.0) or 1.0
    if pressure > 1.0:
        lines.append("Token 消耗过快，请精简表达，减少不必要的工具调用。")

    lines.append("</Token资源>")
    return lines
