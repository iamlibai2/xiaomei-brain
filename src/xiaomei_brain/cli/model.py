"""xiaomei-brain model — 交互式配置 Provider 和模型.

Flow (mirrors Hermes's `hermes model`):
    1. 显示当前配置状态
    2. curses_radiolist → 主菜单（已有 provider / 添加 / 默认 / 退出）
    3. 选 provider → 子菜单（管理 key / 管理模型 / 删除）
    4. 添加 provider → catalog radiolist → key 输入 → model checklist
    5. 所有变更实时写入 config.json
"""

from __future__ import annotations

import os
import sys


def cmd_model(args: list[str]) -> None:
    """交互式配置 provider + API key + 模型"""
    from xiaomei_brain.cli import get_config_path
    from xiaomei_brain.base.config_provider import ConfigProvider

    config_path = get_config_path()
    provider = ConfigProvider(config_path)

    while True:
        config = provider.config
        current_providers = config.get("models", {}).get("providers", {})
        current_primary = config.get("agents", {}).get("defaults", {}).get("model", {}).get("primary", "")

        # ── 主菜单 ──
        items = list(current_providers.items())
        labels = _build_main_menu(items, current_primary)
        idx = _radiolist("模型配置", labels, selected=0, cancel_returns=len(labels) - 1)

        if idx is None or idx == len(labels) - 1:  # 退出
            break

        if idx < len(items):
            # 编辑已有 provider
            pid = items[idx][0]
            pcfg = items[idx][1]
            _edit_provider(provider, pid, pcfg)
        elif labels[idx].startswith("添加"):
            _add_provider(provider, current_providers)
        elif labels[idx].startswith("设置默认"):
            _set_default(provider, current_providers, current_primary)


def _build_main_menu(items: list, current_primary: str) -> list[str]:
    """构建主菜单标签列表"""
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


def _radiolist(title: str, items: list[str], selected: int = 0,
               cancel_returns: int | None = None) -> int | None:
    """curses 单选列表，非 TTY 时回退到数字选择"""
    from xiaomei_brain.cli.curses_ui import curses_radiolist
    return curses_radiolist(title, items, selected=selected, cancel_returns=cancel_returns)


def _checklist(title: str, items: list[str], selected: set[int]) -> set[int]:
    """curses 多选列表"""
    from xiaomei_brain.cli.curses_ui import curses_checklist
    return curses_checklist(title, items, selected)


def _set_default(provider, current_providers: dict, current_primary: str) -> None:
    """选择默认 provider + 模型（radiolist）"""
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

    idx = _radiolist("选择默认模型", labels, selected=default_idx, cancel_returns=None)
    if idx is not None:
        primary = labels[idx]
        provider.patch({"agents": {"defaults": {"model": {"primary": primary}}}})
        print(f"默认模型: {primary}")


def _add_provider(provider, current_providers: dict) -> None:
    """添加新 provider：radiolist 选 provider → 输 key → checklist 选模型"""
    from xiaomei_brain.llm.model_catalog import get_provider_models, PROVIDER_META, get_all_providers

    catalog = get_all_providers()
    available = [(pid, PROVIDER_META.get(pid, {})) for pid in catalog if pid not in current_providers]

    if not available:
        print("没有可添加的 Provider。")
        return

    labels = [f"{pid:15s}  {meta.get('base_url', '')}" for pid, meta in available]
    labels.append("返回")

    idx = _radiolist("添加 Provider", labels, selected=0, cancel_returns=len(labels) - 1)
    if idx is None or idx >= len(available):
        return

    pid, meta = available[idx]
    base_url = meta.get("base_url", "")

    # API Key
    print(f"\n\033[1m{pid}\033[0m")
    print(f"  Base URL: {base_url}")
    try:
        api_key = input("  API Key (Enter 跳过): ").strip()
    except (KeyboardInterrupt, EOFError):
        return

    # 模型选择
    models = get_provider_models(pid)
    if not models:
        print(f"  {pid} 无可用模型目录，请手动输入")
        try:
            model_id = input("  模型 ID: ").strip()
        except (KeyboardInterrupt, EOFError):
            return
        if model_id:
            current_providers[pid] = {
                "baseUrl": base_url,
                "apiKey": api_key,
                "api": "openai-completions",
                "models": [{"id": model_id, "name": model_id, "contextWindow": 128000, "maxTokens": 8192}],
            }
            provider.patch({"models": {"providers": current_providers}})
            print(f"  已添加: {pid}")
        return

    model_labels = [f"{m.id:35s} ctx={m.context_window//1000}K" + ("  reasoning" if m.reasoning else "")
                    for m in models]
    selected = set(range(len(models)))  # 默认全选
    chosen = _checklist(f"{pid} — 选择模型 (SPACE 勾选, ENTER 确认)", model_labels, selected)

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
    print(f"已添加: {pid} ({len(selected_models)} 个模型)")


def _edit_provider(provider, pid: str, pcfg: dict) -> None:
    """编辑已有 provider：子菜单"""
    from xiaomei_brain.llm.model_catalog import get_provider_models

    config = provider.config
    current_providers = config.get("models", {}).get("providers", {})

    has_key = pcfg.get("apiKey", "")
    key_display = "***" + has_key[-4:] if has_key else "(未设置)"
    models = pcfg.get("models", [])
    model_display = ", ".join(m["id"] for m in models) if models else "(无)"
    base_url = pcfg.get("baseUrl", "")

    sub_labels = [
        f"API Key: {key_display}",
        f"Base URL: {base_url}",
        f"模型 ({len(models)}): {model_display}",
        "管理模型...",
        "删除此 Provider",
        "返回",
    ]

    idx = _radiolist(f"编辑 {pid}", sub_labels, selected=0, cancel_returns=len(sub_labels) - 1)
    if idx is None or idx == len(sub_labels) - 1:
        return

    if idx == 0:  # API Key
        print(f"\n{pid} API Key: {key_display}")
        action = input("[K]保持 [R]替换 [C]清除: ").strip().lower()
        if action == "r":
            new_key = input("新 API Key: ").strip()
            if new_key:
                current_providers[pid]["apiKey"] = new_key
                provider.patch({"models": {"providers": current_providers}})
                print("API Key 已更新")
        elif action == "c":
            current_providers[pid].pop("apiKey", None)
            provider.patch({"models": {"providers": current_providers}})
            print("API Key 已清除")

    elif idx == 3:  # 管理模型
        models_catalog = get_provider_models(pid)
        if not models_catalog:
            print(f"{pid} 无模型目录")
            return

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
        provider.patch({"models": {"providers": current_providers}})
        print(f"已更新: {pid} ({len(selected_models)} 个模型)")

    elif idx == 4:  # 删除
        confirm = input(f"确认删除 {pid}? [y/N]: ").strip().lower()
        if confirm in ("y", "yes"):
            current_providers.pop(pid, None)
            provider.patch({"models": {"providers": current_providers}})
            print(f"已删除: {pid}")
