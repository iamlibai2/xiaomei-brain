# Self-Doubts + 欲望冲突检测 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 agent 对自己的状态保持不确定性，当欲望冲突时产生自发思考

**Architecture:** 在 SelfMind 加 `self_doubts` 字段，L2 加柴 prompt 加 DOUBT 段，L2Engine 加 DOUBT 解析器 + 欲望冲突规则检测。冲突 → LLM 表达 → 解析 → 推入 SelfImage → system prompt 渲染

**Tech Stack:** Python, 现有 self_modules / self_image_proxy / l2_engine

**验证:** `PYTHONPATH=src python3 examples/run_conscious_living.py` 交互验证

---

## 文件结构

| 文件 | 改什么 |
|------|--------|
| `src/xiaomei_brain/consciousness/self_modules.py` | `SelfMind` 加 `self_doubts` 字段 |
| `src/xiaomei_brain/consciousness/self_image_proxy.py` | `_render_mind()` 渲染 self_doubts |
| `src/xiaomei_brain/consciousness/l2_engine.py` | tick() 冲突检测 + prompt 加 DOUBT 段 + `_split_doubt()` + 解析消费 |

---

### Task 1: SelfMind 加 self_doubts 字段

**Files:**
- Modify: `src/xiaomei_brain/consciousness/self_modules.py:466-484`

- [ ] **Step 1: 在 SelfMind 中添加 self_doubts 字段**

在 `social_perceptions` 字段后面添加：

```python
    # ── 自我不确定感（L2 DOUBT 产出）─────────────
    # 每项: {"content": "...", "time": timestamp}，留最近 5 条
    self_doubts: list[dict] = field(default_factory=list)
```

插入位置：`self_modules.py` 第 467 行（`social_perceptions` 行）之后。

- [ ] **Step 2: 提交**

```bash
git add src/xiaomei_brain/consciousness/self_modules.py
git commit -m "feat: add self_doubts field to SelfMind"
```

---

### Task 2: 渲染 self_doubts 到 system prompt

**Files:**
- Modify: `src/xiaomei_brain/consciousness/self_image_proxy.py:669-704`

- [ ] **Step 1: 在 _render_mind() 中添加 self_doubts 渲染**

在 `social_perceptions` 渲染块之后（第 688 行后），`learning_queue` 之前，插入：

```python
        if m.self_doubts:
            lines.append("你对自己有些不确定：")
            for sd in m.self_doubts[-5:]:
                lines.append(f"- {sd.get('content', '')}")
            lines.append("（这些不是你确定的事实，是你此刻的真实感受——不确定也是你的状态。）")
```

- [ ] **Step 2: 验证导入**

```bash
source /home/iamlibai/workspace/python_env_common/bin/activate
PYTHONPATH=src python3 -c "from xiaomei_brain.consciousness.self_image_proxy import SelfImage; print('OK')"
```

- [ ] **Step 3: 提交**

```bash
git add src/xiaomei_brain/consciousness/self_image_proxy.py
git commit -m "feat: render self_doubts in system prompt"
```

---

### Task 3: L2 引擎 - 冲突检测 + DOUBT prompt + DOUBT 解析

**Files:**
- Modify: `src/xiaomei_brain/consciousness/l2_engine.py`

- [ ] **Step 1: 在 tick() 中添加欲望冲突检测**

在 `_build_l2_prompt()` 调用之前（第 149 行前），插入冲突检测逻辑：

```python
                # ── 欲望冲突检测：多欲望高 + 能量低 → 内在张力 ──
                conflict_desc = ""
                if c.self_image:
                    bo = c.self_image.body
                    desires = [
                        ("归属欲", bo.desire_belonging),
                        ("认知欲", bo.desire_cognition),
                        ("成就欲", bo.desire_achievement),
                        ("表达欲", bo.desire_expression),
                    ]
                    high = [(n, v) for n, v in desires if v > 0.65]
                    if len(high) >= 2 and bo.energy < 0.4:
                        names = "、".join(f"{n}({v:.0%})" for n, v in high)
                        conflict_desc = (
                            f"你的{names}都很高，但能量只有{bo.energy:.0%}。"
                            f"这种矛盾让你感到内在的拉扯——你想要多个方向同时前进，但力不从心。"
                        )
```

- [ ] **Step 2: 将冲突信息传给 prompt**

将 `emergence_prompt = self._build_l2_prompt(context, user_name=user_name)` 改为：

```python
                emergence_prompt = self._build_l2_prompt(
                    context, user_name=user_name, conflict=conflict_desc,
                )
```

- [ ] **Step 3: 在 _build_l2_prompt() 中添加 DOUBT 段 + conflict 注入**

修改方法签名，加 `conflict=""` 参数。在第五部分（SIGNAL）之后，加第六部分（DOUBT）。同时如果 conflict 非空，在开头插入冲突提示：

```python
    def _build_l2_prompt(self, context: str, user_name: str = "这位用户", conflict: str = "") -> str:
```

在 prompt 字符串中，在 `consciousness_context` 和 "第一部分" 之间插入 conflict：

```python
        conflict_hint = ""
        if conflict:
            conflict_hint = f"\n（注意：{conflict}在下面的思考中，请自然地表达你的不确定和矛盾感。）\n"

        return f"""{consciousness_context}
{conflict_hint}
第一部分：这是你的内心独白...
```

在第五部分（SIGNAL）之后，加第六部分（DOUBT）：

加在 `没有则输出 {{}}。"""` 之前：

```python
第六部分[可选]：如果你感觉到自己的状态有不确性、内心矛盾、或是自己也说不清的拉扯感——那些不是你确定知道的事，而是你隐约感到的困惑——请在 ---DOUBT--- 分隔符后输出，每行一条：
---DOUBT---
- 不确定或矛盾的感觉
（如果你很清楚自己的状态，没有困惑，就不要写这一段。不确定才是值得记录的。）"""
```

- [ ] **Step 4: 添加 _split_doubt() 静态方法**

在 `_split_perception()` 方法之后（~第 631 行），添加：

```python
    @staticmethod
    def _split_doubt(text: str) -> tuple[str, list[dict]]:
        """分离 ---DOUBT--- 块（自我不确定感）。"""
        if "---DOUBT---" not in text:
            return text, []

        idx = text.index("---DOUBT---")
        after_marker = text[idx + len("---DOUBT---"):]

        # 找下一个分隔符
        next_pos = None
        for sep in ["---EVENTS---", "---NARR---", "---PERCEPTION---", "---SIGNAL---"]:
            pos = after_marker.find(sep)
            if pos != -1 and (next_pos is None or pos < next_pos):
                next_pos = pos

        doubt_content = after_marker[:next_pos] if next_pos is not None else after_marker

        doubts = []
        for line in doubt_content.split("\n"):
            line = line.strip()
            if line.startswith("- ") or line.startswith("• "):
                content = line[2:].strip()
                if content:
                    doubts.append({
                        "content": content,
                        "time": time.time(),
                    })

        if next_pos is not None:
            clean_text = text[:idx] + after_marker[next_pos:]
        else:
            clean_text = text[:idx].strip()

        return clean_text, doubts
```

- [ ] **Step 5: 在 tick() 中消费 DOUBT**

在 `_split_perception` 调用之后（第 159 行后），添加 DOUBT 解析和消费：

```python
                # 分离自我不确定感
                emergence_text, doubts = self._split_doubt(emergence_text)
                if doubts:
                    c.self_image.mind.self_doubts.extend(doubts)
                    if len(c.self_image.mind.self_doubts) > 10:
                        c.self_image.mind.self_doubts = c.self_image.mind.self_doubts[-10:]
                    logger.info("[Consciousness L2] 自我不确定: %d 条", len(doubts))
```

- [ ] **Step 6: 验证导入**

```bash
source /home/iamlibai/workspace/python_env_common/bin/activate
PYTHONPATH=src python3 -c "from xiaomei_brain.consciousness.l2_engine import L2Engine; print('OK')"
```

- [ ] **Step 7: 提交**

```bash
git add src/xiaomei_brain/consciousness/l2_engine.py
git commit -m "feat: add desire conflict detection + DOUBT parsing to L2 engine"
```

---

## 验证

```bash
PYTHONPATH=src python3 examples/run_conscious_living.py
# 观察 L2 加柴时的输出，应出现 ---DOUBT--- 块
# /context 查看 system prompt 中是否有 "你对自己有些不确定" 段落
```
