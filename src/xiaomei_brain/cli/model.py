"""xiaomei-brain model — 交互式配置 Provider 和模型.

Flow (mirrors Hermes's `hermes model`):
    1. 显示当前配置状态
    2. curses_radiolist → 主菜单（已有 provider / 添加 / 默认 / 退出）
    3. 选 provider → 子菜单（管理 key / 管理模型 / 删除）
    4. 添加 provider → catalog radiolist → key 输入 → model checklist
    5. 所有变更实时写入 config.json
"""

from __future__ import annotations

import getpass
import sys

from xiaomei_brain.cli.colors import Colors, color


# ── 统一 styled prompt（Hermes 风格）────────────────────────

def _print_header(text: str) -> None:
    """绿色标题，仅在 TTY 时着色"""
    print(color(f"\n─── {text} ───", Colors.GREEN))


def _styled_input(prompt: str, default: str = "", password: bool = False) -> str:
    """统一输入提示 — 黄色问题 + 可选 getpass 遮蔽"""
    display = f"  {prompt}: "
    try:
        if password:
            value = getpass.getpass(color(display, Colors.YELLOW))
        else:
            value = input(color(display, Colors.YELLOW))
        return value.strip() or default
    except (KeyboardInterrupt, EOFError):
        print()
        return default


# ── curses 包装（非 TTY 自动回退）───────────────────────────

def _radiolist(title: str, items: list[str], selected: int = 0,
               cancel_returns: int | None = None, description: str | None = None) -> int | None:
    from xiaomei_brain.cli.curses_ui import curses_radiolist
    return curses_radiolist(title, items, selected=selected,
                            cancel_returns=cancel_returns, description=description)


def _checklist(title: str, items: list[str], selected: set[int]) -> set[int]:
    from xiaomei_brain.cli.curses_ui import curses_checklist
    return curses_checklist(title, items, selected)


# ── 主入口 ──────────────────────────────────────────────────

def cmd_model(args: list[str]) -> None:
    """交互式配置 provider + API key + 模型"""
    from xiaomei_brain.cli import get_config_path
    from xiaomei_brain.base.config_provider import ConfigProvider

    config_path = get_config_path()
    provider = ConfigProvider(config_path)
    new_provider = args[0] if args else None  # --add 快捷方式

    # 如果指定了 provider，直接跳到添加流程
    if new_provider and new_provider not in ("--help", "-h"):
        _print_header(f"快速添加 {new_provider}")
        config = provider.config
        current_providers = config.get("models", {}).get("providers", {})
        _add_provider(provider, current_providers, preselect=new_provider)
        return

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
            labels.append(f"{pid}{'/' + m['id']:40s}")

    if not labels:
        _print_header("请先添加 Provider 和模型")
        return

    default_idx = 0
    for i, label in enumerate(labels):
        if label.strip() == current_primary:
            default_idx = i
            break

    idx = _radiolist("选择默认模型", labels, selected=default_idx, cancel_returns=None)
    if idx is not None:
        primary = labels[idx].strip()
        provider.patch({"agents": {"defaults": {"model": {"primary": primary}}}})
        print(color(f"  ✓ 默认模型: {primary}", Colors.GREEN))


def _add_provider(provider, current_providers: dict, preselect: str | None = None) -> None:
    from xiaomei_brain.llm.model_catalog import get_provider_models, PROVIDER_META, get_all_providers

    catalog = get_all_providers()
    available = [(pid, PROVIDER_META.get(pid, {})) for pid in catalog if pid not in current_providers]

    if not available:
        _print_header("没有可添加的 Provider")
        return

    labels = [f"{pid:15s}  {meta.get('base_url', '')}" for pid, meta in available]
    labels.append("返回")

    # 如果指定了 preselect，直接跳到该 provider
    selected = 0
    if preselect:
        for i, (pid, _) in enumerate(available):
            if pid == preselect:
                selected = i
                break

    idx = _radiolist("添加 Provider", labels, selected=selected, cancel_returns=len(labels) - 1)
    if idx is None or idx >= len(available):
        return

    pid, meta = available[idx]
    base_url = meta.get("base_url", "")

    # API Key — 统一 styled prompt + getpass
    _print_header(f"添加 Provider: {pid}")
    print(f"  Base URL: {base_url}")
    api_key = _styled_input("API Key (Enter 跳过)", password=True)

    # 模型选择
    models = get_provider_models(pid)
    if not models:
        _print_header(f"{pid} 无可用模型目录")
        model_id = _styled_input("手动输入模型 ID")
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
    selected_indices = set(range(len(models)))
    chosen = _checklist(f"{pid} — 选择模型 (SPACE 勾选, ENTER 确认)", model_labels, selected_indices)

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
            # 用 curses radiolist 选择操作，不用 input()
            key_actions = ["替换 API Key", "清除 API Key", "返回"]
            key_idx = _radiolist(
                f"{pid} — API Key: {key_display}",
                key_actions,
                selected=0,
                cancel_returns=2,
                description=f"Base URL: {base_url}",
            )
            if key_idx == 0:
                new_key = _styled_input(f"{pid} — 新 API Key", password=True)
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
                _print_header(f"{pid} 无模型目录")
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
            confirm_actions = [f"确认删除 {pid}", "取消"]
            confirm_idx = _radiolist(
                f"删除 {pid}?",
                confirm_actions,
                selected=1,
                cancel_returns=1,
                description=f"此操作将从 config.json 中移除 {pid} 的所有配置",
            )
            if confirm_idx == 0:
                current_providers.pop(pid, None)
                provider.patch({"models": {"providers": current_providers}})
                print(color(f"  ✓ 已删除: {pid}", Colors.GREEN))
                return  # 返回主菜单
