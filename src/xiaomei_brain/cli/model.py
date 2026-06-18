"""xiaomei-brain model — 交互式配置 Provider 和模型."""

from __future__ import annotations

import sys


def cmd_model(args: list[str]) -> None:
    """交互式配置 provider + API key + 模型，写入 config.json"""
    from xiaomei_brain.cli import get_config_path
    from xiaomei_brain.base.config_provider import ConfigProvider
    from xiaomei_brain.llm.model_catalog import get_all_providers, get_provider_models, PROVIDER_META

    config_path = get_config_path()
    provider = ConfigProvider(config_path)
    config = provider.config

    current_providers = config.get("models", {}).get("providers", {})
    current_primary = config.get("agents", {}).get("defaults", {}).get("model", {}).get("primary", "")

    catalog = get_all_providers()

    while True:
        _show_status(current_providers, current_primary, catalog)

        choice = input("\n选择: ").strip().lower()

        if choice == "0" or choice == "q":
            break
        elif choice == "d":
            _set_default(provider, current_providers, current_primary)
        elif choice == "+":
            _add_provider(provider, current_providers, catalog)
        else:
            items = list(current_providers.items())
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(items):
                    _edit_provider(provider, items[idx][0], items[idx][1], catalog)
            except ValueError:
                pass


def _show_status(current_providers, current_primary, catalog):
    """显示当前配置状态"""
    print(f"\n\033[1m当前配置\033[0m (默认: {current_primary or '未设置'}):")
    items = list(current_providers.items())
    for i, (pid, pcfg) in enumerate(items, 1):
        models = [m["id"] for m in pcfg.get("models", [])]
        model_str = ", ".join(models[:5])
        if len(models) > 5:
            model_str += f" ... (+{len(models)-5})"
        has_key = "***" if pcfg.get("apiKey") else "(无 key)"
        print(f"  [{i}] {pid:12s} → {model_str}  密钥: {has_key}")

    available = [pid for pid in catalog if pid not in current_providers]
    if available:
        print(f"  [+] 添加 Provider ({len(available)} 可用)")
    print(f"  [D] 设置默认模型")
    print(f"  [Q] 完成退出")


def _set_default(provider, current_providers, current_primary):
    """选择默认 provider + 模型"""
    from xiaomei_brain.cli.curses_ui import curses_radiolist

    labels = []
    for pid, pcfg in current_providers.items():
        for m in pcfg.get("models", []):
            labels.append(f"{pid}/{m['id']}")

    if not labels:
        print("请先添加 Provider 和模型。")
        return

    default_idx = 0
    for i, label in enumerate(labels):
        if label == current_primary:
            default_idx = i
            break

    idx = curses_radiolist("选择默认模型", labels, selected=default_idx, cancel_returns=None)
    if idx is not None:
        primary = labels[idx]
        provider.patch({"agents": {"defaults": {"model": {"primary": primary}}}})
        current_primary = primary
        print(f"默认模型: {primary}")


def _add_provider(provider, current_providers, catalog):
    """从 catalog 添加 provider"""
    from xiaomei_brain.cli.curses_ui import curses_radiolist, curses_checklist
    from xiaomei_brain.llm.model_catalog import get_provider_models, PROVIDER_META

    available = [(pid, PROVIDER_META.get(pid, {})) for pid in catalog if pid not in current_providers]
    if not available:
        print("没有可添加的 Provider。")
        return

    labels = [f"{pid:15s} ({meta.get('base_url', '')})" for pid, meta in available]
    idx = curses_radiolist("添加 Provider", labels, selected=0, cancel_returns=None)
    if idx is None:
        return

    pid, meta = available[idx]
    base_url = meta.get("base_url", "")

    print(f"\n添加 Provider: {pid}")
    print(f"  Base URL: {base_url}")
    api_key = input(f"  API Key (或 Enter 跳过): ").strip()

    models = get_provider_models(pid)
    if not models:
        print(f"  {pid} 没有可用模型目录，请手动输入模型 ID")
        model_id = input("  模型 ID: ").strip()
        if model_id:
            current_providers[pid] = {
                "baseUrl": base_url,
                "apiKey": api_key,
                "api": "openai-completions",
                "models": [{"id": model_id, "name": model_id, "contextWindow": 128000, "maxTokens": 8192}],
            }
            provider.patch({"models": {"providers": current_providers}})
            print(f"已添加: {pid}")
        return

    model_labels = [f"{m.id:30s} ctx={m.context_window//1000}K" for m in models]
    selected = set(range(len(models)))
    chosen = curses_checklist(f"选择 {pid} 的模型 (SPACE 勾选, ENTER 确认)", model_labels, selected)

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
    print(f"已添加: {pid} ({len(selected_models)} 个模型)")


def _edit_provider(provider, pid, pcfg, catalog):
    """编辑已有 provider：改 key、改模型列表"""
    from xiaomei_brain.cli.curses_ui import curses_checklist
    from xiaomei_brain.llm.model_catalog import get_provider_models
    from xiaomei_brain.cli import get_config_path
    from xiaomei_brain.base.config_provider import ConfigProvider

    config_provider = ConfigProvider(get_config_path())
    config = config_provider.config
    current_providers = config.get("models", {}).get("providers", {})

    has_key = pcfg.get("apiKey", "")
    key_display = "***" + has_key[-4:] if has_key else "(未设置)"

    print(f"\n{pid}:")
    print(f"  API Key: {key_display}")
    action = input("  [K]保持 [R]替换 [C]清除 [M]管理模型 [B]返回: ").strip().lower()

    if action == "r":
        new_key = input("  新 API Key: ").strip()
        if new_key:
            current_providers[pid]["apiKey"] = new_key
            config_provider.patch({"models": {"providers": current_providers}})
            print(f"  API Key 已更新")
    elif action == "c":
        current_providers[pid].pop("apiKey", None)
        config_provider.patch({"models": {"providers": current_providers}})
        print(f"  API Key 已清除")
    elif action == "m":
        models = get_provider_models(pid)
        existing_ids = {m["id"] for m in pcfg.get("models", [])}
        model_labels = []
        preselected = set()
        for i, m in enumerate(models):
            model_labels.append(f"{m.id:30s} ctx={m.context_window//1000}K")
            if m.id in existing_ids:
                preselected.add(i)
        chosen = curses_checklist(f"选择 {pid} 的模型 (SPACE 勾选, ENTER 确认)", model_labels, preselected)
        selected_models = []
        for i in sorted(chosen):
            m = models[i]
            selected_models.append({
                "id": m.id, "name": m.name,
                "contextWindow": m.context_window,
                "maxTokens": m.max_output or 8192,
                "reasoning": m.reasoning,
            })
        current_providers[pid]["models"] = selected_models
        config_provider.patch({"models": {"providers": current_providers}})
        print(f"已更新: {pid} ({len(selected_models)} 个模型)")
