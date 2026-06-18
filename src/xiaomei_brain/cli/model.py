"""xiaomei-brain model — 交互式配置 Provider 和模型.

All user interaction stays inside curses — no plain input() / print() mid-flow:
    curses_radiolist → curses_input → curses_checklist → curses_radiolist → ...

Flow:
    1. curses_radiolist → 主菜单（已有 provider / 添加 / 默认 / 退出）
    2. 选 provider → 子菜单（管理 key / 管理模型 / 删除）
    3. 添加 provider → catalog radiolist → curses_input(key) → model checklist
    4. 所有变更实时写入 config.json
"""

from __future__ import annotations

from xiaomei_brain.cli.colors import Colors, color


# ── curses 组件封装 ──────────────────────────────────────────

def _radiolist(title: str, items: list[str], selected: int = 0,
               cancel_returns: int | None = None, description: str | None = None) -> int | None:
    from xiaomei_brain.cli.curses_ui import curses_radiolist
    return curses_radiolist(title, items, selected=selected,
                            cancel_returns=cancel_returns, description=description)


def _checklist(title: str, items: list[str], selected: set[int]) -> set[int]:
    from xiaomei_brain.cli.curses_ui import curses_checklist
    return curses_checklist(title, items, selected)


def _curses_input(title: str, *, password: bool = False,
                  description: str | None = None, default: str = "",
                  cancel_returns: str | None = None) -> str | None:
    """curses 文本输入 — 不跳出 curses UI"""
    from xiaomei_brain.cli.curses_ui import curses_input
    return curses_input(title, password=password, description=description,
                        default=default, cancel_returns=cancel_returns)


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
        idx = _radiolist("模型配置", labels, selected=0, cancel_returns=len(labels) - 1)

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

    idx = _radiolist("选择默认模型", labels, selected=default_idx, cancel_returns=None)
    if idx is not None:
        primary = labels[idx]
        provider.patch({"agents": {"defaults": {"model": {"primary": primary}}}})
        print(color(f"  ✓ 默认模型: {primary}", Colors.GREEN))


def _add_provider(provider, current_providers: dict) -> None:
    from xiaomei_brain.llm.model_catalog import get_provider_models, PROVIDER_META, get_all_providers

    catalog = get_all_providers()
    available = [(pid, PROVIDER_META.get(pid, {})) for pid in catalog if pid not in current_providers]

    if not available:
        print(color("没有可添加的 Provider。", Colors.YELLOW))
        return

    labels = [f"{pid:15s}  {meta.get('base_url', '')}" for pid, meta in available]
    labels.append("返回")

    idx = _radiolist("添加 Provider", labels, selected=0, cancel_returns=len(labels) - 1)
    if idx is None or idx >= len(available):
        return

    pid, meta = available[idx]
    base_url = meta.get("base_url", "")

    # API Key — curses_input 保持在 curses 内
    api_key = _curses_input(
        f"输入 {pid} API Key",
        password=True,
        description=f"Base URL: {base_url}\n\n按 Enter 跳过（稍后可配置）",
        cancel_returns="",
    )
    if api_key is None:
        return  # ESC 取消

    # 模型选择
    models = get_provider_models(pid)
    if not models:
        model_id = _curses_input(
            f"{pid} — 手动输入模型 ID",
            description=f"Base URL: {base_url}\n\n该 provider 无模型目录，请手动输入",
            cancel_returns="",
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
    chosen = _checklist(f"{pid} — 选择模型 (SPACE 勾选, ENTER 确认)", model_labels, set(range(len(models))))

    if not chosen:
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

        idx = _radiolist(f"{pid}", sub_labels, selected=0, cancel_returns=len(sub_labels) - 1)
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
                new_key = _curses_input(
                    f"{pid} — 新 API Key",
                    password=True,
                    description=f"Base URL: {base_url}",
                    cancel_returns="",
                )
                if new_key is None:
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
                print(color(f"{pid} 无模型目录", Colors.YELLOW))
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

            chosen = _checklist(f"{pid} — 选择模型 (SPACE 勾选, ENTER 确认)", model_labels, preselected)

            selected_models = []
            for i in sorted(chosen):
                m = models_catalog[i]
                selected_models.append({
                    "id": m.id, "name": m.name,
                    "contextWindow": m.context_window,
                    "maxTokens": m.max_output or 8192,
                    "reasoning": m.reasoning,
                })
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
                current_providers.pop(pid, None)
                provider.patch({"models": {"providers": current_providers}})
                print(color(f"  ✓ 已删除: {pid}", Colors.GREEN))
                return  # 返回主菜单
