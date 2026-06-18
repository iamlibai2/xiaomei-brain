"""xiaomei-brain model — 交互式配置 Provider 和模型.

照 Hermes 做法：curses 只做菜单选择（radiolist/checklist），文本输入用
tty.setraw() 遮蔽输入（密码）或 input()（普通文本），不在 curses 内做文本输入。

Flow:
    1. curses_radiolist → 主菜单（已有 provider / 添加 / 默认 / 退出）
    2. 选 provider → 子菜单（管理 key / 管理模型 / 删除）
    3. 添加 provider → catalog radiolist → masked_input(key) → model checklist
    4. 所有变更实时写入 config.json
"""

from __future__ import annotations

from xiaomei_brain.cli.colors import Colors, color


# ── curses 组件封装 ──────────────────────────────────────────

def _radiolist(title: str, items: list[str], selected: int = 0,
               cancel_returns: int | None = None, description: str | None = None,
               searchable: bool = False) -> int | None:
    from xiaomei_brain.cli.curses_ui import curses_radiolist
    return curses_radiolist(title, items, selected=selected,
                            cancel_returns=cancel_returns, description=description,
                            searchable=searchable)


_CHECKLIST_CANCEL = object()

def _checklist(title: str, items: list[str], selected: set[int]) -> set[int] | None:
    from xiaomei_brain.cli.curses_ui import curses_checklist
    result = curses_checklist(title, items, selected, cancel_returns=_CHECKLIST_CANCEL)
    if result is _CHECKLIST_CANCEL:
        return None
    return result


def _prompt_input(title: str, *, password: bool = False,
                  description: str | None = None, default: str = "") -> str:
    """文本输入 — 密码用 tty.setraw() + 字符遮蔽，普通文本用 input()。

    不在 curses 内运行（照 Hermes 做法），curses 菜单退出后调用是安全的。
    """
    import sys
    from xiaomei_brain.cli.curses_ui import flush_stdin
    from xiaomei_brain.cli.colors import Colors, color

    flush_stdin()

    # 构建提示信息
    lines = [color(f"  {title}", Colors.YELLOW)]
    if description:
        for line in description.splitlines():
            lines.append(f"  {line}")
    print()
    for line in lines:
        print(line)
    print()

    if password:
        from xiaomei_brain.cli.masked_input import masked_input
        print(color("  输入后回车录入，直接回车跳过", Colors.DIM))
        value = masked_input("  > ")
        if not value and default:
            return default
        return value
    else:
        if not sys.stdin.isatty():
            return default
        try:
            print(color("  输入后回车录入，直接回车跳过", Colors.DIM))
            if default:
                value = input(f"  [{default}] > ").strip()
                return value if value else default
            else:
                return input("  > ").strip()
        except (KeyboardInterrupt, EOFError):
            return ""



# ── 主入口 ──────────────────────────────────────────────────

def cmd_model(args: list[str]) -> None:
    from xiaomei_brain.cli import get_config_path
    from xiaomei_brain.base.config_provider import ConfigProvider

    config_path = get_config_path()
    provider = ConfigProvider(config_path)

    while True:
        config = provider.config
        current_providers = config.get("models", {}).get("providers", {})
        current_primary = config.get("agents", {}).get("defaults", {}).get("model", {}).get("primary", "")

        items = list(current_providers.items())
        labels = _build_main_menu(items, current_primary)

        n_configured = len(items)
        total_models = sum(len(pcfg.get("models", [])) for _, pcfg in items)
        desc_parts = [f"已配置: {n_configured} 个 Provider, {total_models} 个模型"]
        if current_primary:
            desc_parts.append(f"默认模型: {current_primary}")
        description = "  ".join(desc_parts)

        idx = _radiolist("模型配置", labels, selected=0, cancel_returns=len(labels) - 1,
                         description=description, searchable=True)

        if idx is None or idx == len(labels) - 1:  # 退出
            break

        if idx < len(items):
            _edit_provider(provider, items[idx][0], items[idx][1])
        elif labels[idx].startswith("添加"):
            _add_provider(provider, current_providers)
        elif labels[idx].startswith("设置默认"):
            _set_default(provider, current_providers, current_primary)


def _build_main_menu(items: list, current_primary: str) -> list[str]:
    labels = []
    for pid, pcfg in items:
        models = pcfg.get("models", [])
        n_models = len(models)
        has_key = "✓" if pcfg.get("apiKey") else "✗"
        model_hint = ", ".join(m["id"] for m in models[:3])
        if n_models > 3:
            model_hint += f" ... +{n_models - 3}"
        if not model_hint:
            model_hint = "(无模型)"
        labels.append(f"{pid:12s}  key:{has_key}  {model_hint}")

    labels.append("添加 Provider...")
    if current_primary:
        labels.append(f"设置默认模型 (当前: {current_primary})")
    else:
        labels.append("设置默认模型 (未设置)")
    labels.append("退出")
    return labels


def _set_default(provider, current_providers: dict, current_primary: str) -> None:
    labels = []
    for pid, pcfg in current_providers.items():
        for m in pcfg.get("models", []):
            labels.append(f"{pid}/{m['id']}")

    if not labels:
        print(color("请先添加 Provider 和模型。", Colors.YELLOW))
        return

    default_idx = 0
    for i, label in enumerate(labels):
        if label == current_primary:
            default_idx = i
            break

    labels.append("返回")
    idx = _radiolist("选择默认模型", labels, selected=default_idx, cancel_returns=len(labels) - 1, searchable=True)
    if idx is not None:
        primary = labels[idx]
        provider.patch({"agents": {"defaults": {"model": {"primary": primary}}}})
        print(color(f"  ✓ 默认模型: {primary}", Colors.GREEN))


def _add_provider(provider, current_providers: dict) -> None:
    from xiaomei_brain.llm.model_catalog import get_provider_models, PROVIDER_META

    available = [(pid, PROVIDER_META[pid]) for pid in PROVIDER_META if pid not in current_providers]

    if not available:
        print(color("没有可添加的 Provider。", Colors.YELLOW))
        return

    labels = [f"{pid:15s}  {meta.get('base_url', '')}" for pid, meta in available]
    custom_label_idx = len(labels)       # "+ 自定义（OpenAI 兼容）" 的位置
    labels.append("+ 自定义（OpenAI 兼容）...")
    labels.append("返回")

    idx = _radiolist("添加 Provider", labels, selected=0, cancel_returns=len(labels) - 1, searchable=True)
    if idx is None or idx >= len(labels) - 1:
        return

    # 自定义 provider：手动输入所有信息
    if idx == custom_label_idx:
        pid = _prompt_input("Provider ID", description="小写字母+数字，如 ollama、vllm")
        if not pid:
            return
        base_url = _prompt_input(f"{pid} — Base URL", description="OpenAI 兼容的 API 地址")
        if not base_url:
            return
        api_key = _prompt_input(f"输入 {pid} API Key", password=True, description=f"Base URL: {base_url}")
        model_id = _prompt_input(f"{pid} — 模型 ID", description=f"Base URL: {base_url}")
        if not model_id:
            return
        current_providers[pid] = {
            "baseUrl": base_url,
            "apiKey": api_key,
            "api": "openai-completions",
            "models": [{"id": model_id, "name": model_id, "contextWindow": 128000, "maxTokens": 8192}],
        }
        provider.patch({"models": {"providers": current_providers}})
        print(color(f"  ✓ 已添加: {pid}", Colors.GREEN))
        return

    pid, meta = available[idx]
    base_url = meta.get("base_url", "")

    # Base URL — 可覆盖
    custom_url = _prompt_input(
        f"{pid} — Base URL",
        description=f"默认: {base_url}",
        default=base_url,
    )
    base_url = custom_url

    # API Key — masked_input 在 curses 结束后安全运行
    api_key = _prompt_input(
        f"输入 {pid} API Key",
        password=True,
        description=f"Base URL: {base_url}",
    )

    # 模型选择
    models = get_provider_models(pid)
    if not models:
        model_id = _prompt_input(
            f"{pid} — 手动输入模型 ID",
            description=f"Base URL: {base_url}",
        )
        if model_id:
            current_providers[pid] = {
                "baseUrl": base_url,
                "apiKey": api_key,
                "api": "openai-completions",
                "models": [{"id": model_id, "name": model_id, "contextWindow": 128000, "maxTokens": 8192}],
            }
            provider.patch({"models": {"providers": current_providers}})
            print(color(f"  ✓ 已添加: {pid}", Colors.GREEN))
        return

    model_labels = [f"{m.id:35s} ctx={m.context_window//1000}K" + ("  reasoning" if m.reasoning else "")
                    for m in models]
    model_labels.append("+ 手动输入模型名...")
    custom_idx = len(models)  # the "+ 手动输入" row
    back_idx = len(models) + 1
    model_labels.append("返回")
    chosen = _checklist(f"{pid} — 选择模型 (SPACE 勾选, ENTER 确认)", model_labels, set(range(len(models))))
    if chosen is None or back_idx in chosen:
        return

    # 处理"手动输入模型名"
    custom_models = []
    if custom_idx in chosen:
        chosen.discard(custom_idx)
        custom_id = _prompt_input(
            f"{pid} — 手动输入模型 ID",
            description=f"Base URL: {base_url}",
        )
        if custom_id:
            custom_models.append({
                "id": custom_id, "name": custom_id,
                "contextWindow": 128000, "maxTokens": 8192,
            })

    if not chosen and not custom_models:
        return

    selected_models = []
    for i in sorted(chosen):
        m = models[i]
        selected_models.append({
            "id": m.id,
            "name": m.name,
            "contextWindow": m.context_window,
            "maxTokens": m.max_output or 8192,
            "reasoning": m.reasoning,
        })
    selected_models.extend(custom_models)

    current_providers[pid] = {
        "baseUrl": base_url,
        "apiKey": api_key,
        "api": "openai-completions",
        "models": selected_models,
    }

    provider.patch({"models": {"providers": current_providers}})
    print(color(f"  ✓ 已添加: {pid} ({len(selected_models)} 个模型)", Colors.GREEN))


def _edit_provider(provider, pid: str, pcfg: dict) -> None:
    from xiaomei_brain.llm.model_catalog import get_provider_models

    config = provider.config
    current_providers = config.get("models", {}).get("providers", {})

    while True:
        has_key = pcfg.get("apiKey", "")
        key_display = "***" + has_key[-4:] if has_key else "(未设置)"
        models = pcfg.get("models", [])
        model_display = ", ".join(m["id"] for m in models[:3]) if models else "(无)"
        if len(models) > 3:
            model_display += f" ... +{len(models) - 3}"
        base_url = pcfg.get("baseUrl", "")

        sub_labels = [
            f"API Key: {key_display}",
            f"Base URL: {base_url}",
            f"模型 ({len(models)}): {model_display}",
            "选择模型...",
            "删除此 Provider",
            "返回",
        ]

        idx = _radiolist(f"{pid}", sub_labels, selected=0, cancel_returns=len(sub_labels) - 1, searchable=True)
        if idx is None or idx == len(sub_labels) - 1:
            return

        if idx == 0:  # API Key
            key_actions = ["替换 API Key", "清除 API Key", "返回"]
            key_idx = _radiolist(
                f"{pid} — API Key: {key_display}",
                key_actions,
                selected=0,
                cancel_returns=2,
                description=f"Base URL: {base_url}",
            )
            if key_idx == 0:
                new_key = _prompt_input(
                    f"{pid} — 新 API Key",
                    password=True,
                    description=f"Base URL: {base_url}",
                )
                if not new_key:
                    continue
                if new_key:
                    current_providers[pid]["apiKey"] = new_key
                    pcfg["apiKey"] = new_key
                    provider.patch({"models": {"providers": current_providers}})
                    print(color(f"  ✓ API Key 已更新", Colors.GREEN))
            elif key_idx == 1:
                current_providers[pid].pop("apiKey", None)
                pcfg.pop("apiKey", None)
                provider.patch({"models": {"providers": current_providers}})
                print(color(f"  ✓ API Key 已清除", Colors.GREEN))

        elif idx == 3:  # 选择模型
            models_catalog = get_provider_models(pid)
            if not models_catalog:
                # 无目录时仍然允许手动输入
                custom_id = _prompt_input(
                    f"{pid} — 手动输入模型 ID",
                    description=f"Base URL: {base_url}",
                )
                if custom_id:
                    current_providers[pid]["models"] = [
                        {"id": custom_id, "name": custom_id, "contextWindow": 128000, "maxTokens": 8192},
                    ]
                    pcfg["models"] = current_providers[pid]["models"]
                    provider.patch({"models": {"providers": current_providers}})
                    print(color(f"  ✓ 已添加模型: {custom_id}", Colors.GREEN))
                continue

            existing_ids = {m["id"] for m in models}
            model_labels = []
            preselected = set()
            for i, m in enumerate(models_catalog):
                ctx_k = f"ctx={m.context_window // 1000}K" if m.context_window else ""
                reason = "reasoning" if m.reasoning else ""
                extras = "  ".join(filter(None, [ctx_k, reason]))
                label = f"{m.id:35s}"
                if extras:
                    label += f"  {extras}"
                model_labels.append(label)
                if m.id in existing_ids:
                    preselected.add(i)

            model_labels.append("+ 手动输入模型名...")
            custom_idx = len(models_catalog)
            back_idx = len(models_catalog) + 1
            model_labels.append("返回")

            chosen = _checklist(f"{pid} — 选择模型 (SPACE 勾选, ENTER 确认)", model_labels, preselected)
            if chosen is None or back_idx in chosen:
                continue

            # 处理"手动输入模型名"
            custom_models = []
            if custom_idx in chosen:
                chosen.discard(custom_idx)
                custom_id = _prompt_input(
                    f"{pid} — 手动输入模型 ID",
                    description=f"Base URL: {base_url}",
                )
                if custom_id:
                    custom_models.append({
                        "id": custom_id, "name": custom_id,
                        "contextWindow": 128000, "maxTokens": 8192,
                    })

            selected_models = []
            for i in sorted(chosen):
                m = models_catalog[i]
                selected_models.append({
                    "id": m.id, "name": m.name,
                    "contextWindow": m.context_window,
                    "maxTokens": m.max_output or 8192,
                    "reasoning": m.reasoning,
                })
            selected_models.extend(custom_models)
            current_providers[pid]["models"] = selected_models
            pcfg["models"] = selected_models
            provider.patch({"models": {"providers": current_providers}})
            print(color(f"  ✓ 已更新: {pid} ({len(selected_models)} 个模型)", Colors.GREEN))

        elif idx == 4:  # 删除
            confirm_idx = _radiolist(
                f"删除 {pid}?",
                [f"确认删除 {pid}", "取消"],
                selected=1,
                cancel_returns=1,
                description=f"此操作将从 config.json 中移除 {pid} 的所有配置\n\nBase URL: {pcfg.get('baseUrl', '')}",
            )
            if confirm_idx == 0:
                # None = delete (JSON Merge Patch 语义), 不能 pop()
                # 因为 _deep_merge 只处理 partial 中存在的 key
                current_providers[pid] = None
                provider.patch({"models": {"providers": current_providers}})
                print(color(f"  ✓ 已删除: {pid}", Colors.GREEN))
                return  # 返回主菜单
