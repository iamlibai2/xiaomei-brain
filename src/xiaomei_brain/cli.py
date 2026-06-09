"""CLI 命令接口

用法：
    python -m xiaomei_brain agent create <name> [--copy-from <existing>]
    python -m xiaomei_brain config get <path>
    python -m xiaomei_brain config set <path> <value>
    python -m xiaomei_brain config validate
    python -m xiaomei_brain config file
    python -m xiaomei_brain plugins list
    python -m xiaomei_brain plugins enable <name>
    python -m xiaomei_brain plugins disable <name>
"""

import json
import os
import shutil
import sys


def get_config_path() -> str:
    """获取配置文件路径"""
    from pathlib import Path
    search_paths = [
        Path("config.json"),
        Path.home() / ".xiaomei-brain" / "config.json",
    ]
    for p in search_paths:
        if p.exists():
            return str(p)
    return str(Path.home() / ".xiaomei-brain" / "config.json")


def cmd_get(path: str = "") -> None:
    """获取配置值"""
    from xiaomei_brain.base.config_provider import ConfigProvider

    config_path = get_config_path()
    provider = ConfigProvider(config_path)
    value = provider.get(path)
    print(json.dumps({"value": value, "hash": provider.hash}, indent=2, ensure_ascii=False))


def cmd_set(path: str, value: str) -> None:
    """设置配置值

    Args:
        path: 配置路径，如 "xiaomei_brain.tts.enabled"
        value: JSON 字符串或普通字符串
    """
    from xiaomei_brain.base.config_provider import ConfigProvider

    # 尝试解析 JSON
    try:
        parsed_value = json.loads(value)
    except json.JSONDecodeError:
        parsed_value = value

    config_path = get_config_path()
    provider = ConfigProvider(config_path)

    # 构建 nested path
    keys = path.split(".")
    partial = parsed_value
    for key in reversed(keys):
        partial = {key: partial}

    provider.patch(partial)
    print(json.dumps({"success": True, "hash": provider.hash}, indent=2, ensure_ascii=False))


def cmd_validate() -> None:
    """验证配置格式"""
    from xiaomei_brain.base.config_provider import ConfigProvider

    config_path = get_config_path()
    errors = []

    try:
        provider = ConfigProvider(config_path)
        config = provider.config

        if not isinstance(config, dict):
            errors.append("Config must be a JSON object")

    except Exception as e:
        errors.append(f"Config error: {e}")

    result = {"valid": len(errors) == 0, "errors": errors}
    print(json.dumps(result, indent=2, ensure_ascii=False))

    if not result["valid"]:
        sys.exit(1)


def cmd_file() -> None:
    """打印配置文件路径"""
    print(get_config_path())


# ── plugins 命令 ────────────────────────────────────────────────

def cmd_plugins_list() -> None:
    """列出所有已发现的插件及状态。"""
    from .plugin import PluginLoader, PluginRegistry
    from .plugin.bootstrap import _read_raw_config

    registry = PluginRegistry()
    raw_config = _read_raw_config() or {}
    plugins_cfg = raw_config.get("plugins", {})
    allow_list = plugins_cfg.get("allow", [])
    deny_list = plugins_cfg.get("deny", [])

    loader = PluginLoader(registry=registry, config={"plugins": plugins_cfg})
    manifests = loader.discover()

    if not manifests:
        print("No plugins discovered.")
        return

    print(f"{'Name':<20} {'Kind':<10} {'Version':<10} {'Status':<12} {'Info'}")
    print("-" * 80)

    for m in sorted(manifests, key=lambda x: x.name):
        # 判断状态
        if deny_list and m.name in deny_list:
            status = "disabled"
        elif allow_list and m.name not in allow_list:
            status = "disabled"
        else:
            # requires_env
            missing = [ev for ev in m.requires_env if not os.getenv(ev)]
            status = "error" if missing else "ok"

        info_parts = []
        if m.channel:
            info_parts.append(f"channel={m.channel}")
        if m.requires_env:
            ok_env = [ev for ev in m.requires_env if os.getenv(ev)]
            missing_env = [ev for ev in m.requires_env if not os.getenv(ev)]
            if ok_env:
                info_parts.append(f"env OK: {', '.join(ok_env)}")
            if missing_env:
                info_parts.append(f"env MISS: {', '.join(missing_env)}")
        if m.config_schema:
            info_parts.append("has configSchema")
        info = ", ".join(info_parts) if info_parts else m.description[:50]

        print(f"{m.name:<20} {m.kind:<10} {m.version:<10} {status:<12} {info}")

    # 统计
    ok = sum(1 for m in manifests
             if not (deny_list and m.name in deny_list)
             and not (allow_list and m.name not in allow_list)
             and all(os.getenv(ev) for ev in m.requires_env))
    print(f"\n{ok}/{len(manifests)} plugins ready")


def cmd_plugins_enable(name: str) -> None:
    """启用插件（添加到 plugins.allow）。"""
    _toggle_plugin(name, enable=True)


def cmd_plugins_disable(name: str) -> None:
    """禁用插件（添加到 plugins.deny 或从 allow 中移除）。"""
    _toggle_plugin(name, enable=False)


def _toggle_plugin(name: str, enable: bool) -> None:
    """切换插件启用/禁用状态。"""
    from pathlib import Path
    import json as _json

    config_path = Path(get_config_path())
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        sys.exit(1)

    data = _json.loads(config_path.read_text(encoding="utf-8"))

    # 确保 plugins 段存在
    if "plugins" not in data:
        data["plugins"] = {}
    plugins = data["plugins"]

    if enable:
        allow = plugins.setdefault("allow", [])
        deny = plugins.setdefault("deny", [])
        if name not in allow:
            allow.append(name)
        if name in deny:
            deny.remove(name)
        print(f"Plugin '{name}' enabled (added to plugins.allow)")
    else:
        allow = plugins.setdefault("allow", [])
        deny = plugins.setdefault("deny", [])
        if name in allow:
            allow.remove(name)
        if name not in deny:
            deny.append(name)
        print(f"Plugin '{name}' disabled (added to plugins.deny)")

    config_path.write_text(_json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ── agent 命令 ──────────────────────────────────────────────────

# 默认 identity.md 模板
_IDENTITY_TEMPLATE = """# {name}

你是{name}，一个AI助手。

## 身份
- 角色：AI助手
- 风格：简洁、温暖

## 追求
- 帮助用户高效完成任务

## 热爱
- 学习新知识
- 与人交流

## 底线
- 诚实
"""

# 默认 config.yaml（精简版，与 xiaomei 一致的结构）
_CONFIG_YAML_TEMPLATE = """\
# ============================================================
#  xiaomei-brain 进程配置
#
#  位置: ~/.xiaomei-brain/{agent_id}/config.yaml
#  首次启动时自动生成，可手动编辑。修改后重启生效。
# ============================================================

# ── Drive 层 — 边缘系统 ────────────────────────────────────
drive:
  hormone:
    initial:
      dopamine:    0.5
      serotonin:   0.5
      cortisol:    0.3
      oxytocin:    0.5
      norepinephrine: 0.5
    decay_rates:
      dopamine:    0.95
      serotonin:   0.98
      cortisol:    0.9
      oxytocin:    0.95
      norepinephrine: 0.95
  desire:
    initial:
      survival:    0.3
      achievement: 0.5
      belonging:   0.5
      cognition:   0.6
      expression:  0.4
    thresholds:
      belonging:   0.7
      cognition:   0.8
      achievement: 0.6
      expression:  0.7
      survival_threatened: 0.3
      survival_dying:      0.1
      survival_dead:       0.0
    recovery_rate: 0.5
  emotion:
    decay_rate:       0.95
    min_intensity:    0.1
    default_duration: 60.0
    switch_inertia:   0.7
    durations:
      joy:     600
      sadness: 1800
      fear:    300
      anger:   600
  motivation:
    rpe_coefficient:         0.5
    expected_update_weight:  0.2
  energy:
    initial: 0.8

# ── Consciousness 层 — 意识系统 ─────────────────────────────
consciousness:
  l0_interval:          1.0
  l1_threshold:         60
  l1_anomaly_enabled:   false
  l2_check_interval:    10.0
  l2_idle_trigger:      60.0
  l2_changes_trigger:   10
  l2_cooldown:          300.0
  l2_periodic_interval: 1800.0
  sleep_to_dream_threshold:    300.0
  l3_cooldown:          1800.0
  energy_low_threshold: 0.1
  energy_silent_threshold: 0.15
  living:
    tick_interval:      1.0
    surge_interval:     60.0
    idle_short:         60.0
    idle_threshold:     10800.0
    dream_interval:     3000.0
    max_context_tokens: 50000
    comms_port:         0
    ws_port:            -1
  action:
    intent_greet_cooldown:    3600.0
    intent_care_cooldown:     1800.0
    intent_reflect_cooldown:  7200.0
    intent_act_cooldown:      3600.0
    intent_work_cooldown:     60.0
    intent_learn_cooldown:    7200.0
    intent_express_cooldown:  1800.0
    intent_progress_cooldown: 3600.0
    idle_trigger_seconds:     1800.0
    idle_greet_cooldown:      1800.0
    desire_greet_cooldown:    3600.0
    desire_learn_cooldown:    7200.0
    desire_achievement_cooldown: 3600.0
    desire_express_cooldown:  3600.0
    desire_talk_to_agent_cooldown: 60.0
  context:
    fresh_tail_count:      40
    flow_tail_count:       4
    reflect_tail_count:    12
    messages_per_compact:  8
    reserved_fresh_count:  10
    compact_token_ratio:   0.5
    compact_time_window:   7200.0
    daily_max_memories:    12
    reflect_max_memories:  15
    daily_min_strength:    0.6
    reflect_min_strength:  0.4
    short_input_threshold: 15
  keywords:
    reflect_keywords: [答对了吗, 做错了, 纠正, 不对, 反省, 反思, 我错了吗]
    past_keywords: [昨天, 之前, 上次, 以前, 记得, 刚才, 那一次]
    opinion_keywords: [你觉得, 你怎么看, 建议, 推荐, 你更喜欢, 你觉得我]
    personal_keywords: [我心情, 我好开心, 我很难过, 你能不能, 我想要, 我感觉]
    simple_patterns: [算, 计算, 翻译, 几点, 什么意思, ？, 吗, 帮我]
    continue_patterns: [继续, 接着做, 还做, 再做, 延续, 持续]
"""


def cmd_agent_create(name: str, copy_from: str = "") -> None:
    """创建新 agent。

    Args:
        name: agent ID
        copy_from: 从哪个已有 agent 复制 LLM 配置
    """
    base_dir = os.path.expanduser("~/.xiaomei-brain")
    agent_dir = os.path.join(base_dir, name)

    # 检查是否已存在
    if os.path.exists(agent_dir):
        print(f"\033[31m[错误] agent '{name}' 已存在: {agent_dir}\033[0m")
        sys.exit(1)

    # ── 读取 config.json ──────────────────────────────────
    config_path = os.path.join(base_dir, "config.json")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
    else:
        config_data = {}

    # ── 确定 LLM model 配置 ──────────────────────────────
    model_config = {"primary": "deepseek/deepseek-v4-flash"}
    if copy_from:
        # 从指定 agent 复制
        agents_list = config_data.get("agents", {}).get("list", [])
        source = next((a for a in agents_list if a.get("id") == copy_from), None)
        if source and source.get("model"):
            model_config = source["model"]
        else:
            print(f"\033[33m[警告] agent '{copy_from}' 未找到或无 model 配置，使用默认\033[0m")
    else:
        # 自动找第一个已有 agent 复制
        agents_list = config_data.get("agents", {}).get("list", [])
        for a in agents_list:
            if a.get("model") and a.get("id") != name:
                model_config = a["model"]
                copy_from = a["id"]
                break

    # ── 创建目录结构 ──────────────────────────────────────
    dirs = [
        agent_dir,
        os.path.join(agent_dir, "consciousness"),
        os.path.join(agent_dir, "contacts"),
        os.path.join(agent_dir, "logs"),
        os.path.join(agent_dir, "debug"),
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)

    # ── 写入 identity.md ─────────────────────────────────
    identity_path = os.path.join(agent_dir, "consciousness", "identity.md")
    identity_content = _IDENTITY_TEMPLATE.format(name=name)
    with open(identity_path, "w", encoding="utf-8") as f:
        f.write(identity_content)

    # ── 写入 config.yaml ─────────────────────────────────
    config_yaml_path = os.path.join(agent_dir, "config.yaml")
    with open(config_yaml_path, "w", encoding="utf-8") as f:
        f.write(_CONFIG_YAML_TEMPLATE.format(agent_id=name))

    # ── 写入 contacts/identities.yaml ────────────────────
    identities_path = os.path.join(agent_dir, "contacts", "identities.yaml")
    with open(identities_path, "w", encoding="utf-8") as f:
        f.write("people: []\n")

    # ── 注册到 config.json ──────────────────────────────
    if "agents" not in config_data:
        config_data["agents"] = {}
    if "list" not in config_data["agents"]:
        config_data["agents"]["list"] = []

    # 检查是否已注册
    existing = [a for a in config_data["agents"]["list"] if a.get("id") == name]
    if not existing:
        entry = {
            "id": name,
            "name": name,
            "description": "",
            "enabled": True,
            "model": model_config,
            "tools": {"profile": "assistant"},
            "identity": "",
        }
        config_data["agents"]["list"].append(entry)

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)

    # ── 输出结果 ─────────────────────────────────────────
    print(f"\033[32mAgent '{name}' 创建成功!\033[0m")
    print(f"  目录: {agent_dir}")
    print(f"  identity: {identity_path}")
    print(f"  config: {config_yaml_path}")
    print(f"  contacts: {identities_path}")
    if copy_from:
        print(f"  LLM model: {model_config.get('primary', model_config)} (来自 {copy_from})")
    else:
        print(f"  LLM model: {model_config.get('primary', model_config)} (默认)")
    print()
    print(f"启动: PYTHONPATH=src python3 examples/run_conscious_living.py --name {name}")


def main() -> None:
    """CLI 入口"""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python -m xiaomei_brain agent create <name> [--copy-from <existing>]")
        print("  python -m xiaomei_brain config get <path>")
        print("  python -m xiaomei_brain config set <path> <value>")
        print("  python -m xiaomei_brain config validate")
        print("  python -m xiaomei_brain config file")
        print("  python -m xiaomei_brain plugins list")
        print("  python -m xiaomei_brain plugins enable <name>")
        print("  python -m xiaomei_brain plugins disable <name>")
        sys.exit(1)

    args = sys.argv[1:]

    if args[0] == "agent":
        action_args = args[1:]

        if len(action_args) == 0:
            print("Usage: python -m xiaomei_brain agent create <name> [--copy-from <existing>]")
            sys.exit(1)

        action = action_args[0]
        rest = action_args[1:]

        if action == "create":
            if not rest:
                print("Usage: python -m xiaomei_brain agent create <name> [--copy-from <existing>]")
                sys.exit(1)
            name = rest[0]
            copy_from = ""
            if "--copy-from" in rest:
                idx = rest.index("--copy-from")
                if idx + 1 < len(rest):
                    copy_from = rest[idx + 1]
            cmd_agent_create(name, copy_from)
        else:
            print(f"Unknown action: {action}")
            print("Usage: python -m xiaomei_brain agent create <name> [--copy-from <existing>]")
            sys.exit(1)

    elif args[0] == "config":
        action_args = args[1:]

        if len(action_args) == 0:
            print("Usage: python -m xiaomei_brain.cli config <get|set|validate|file> ...")
            sys.exit(1)

        action = action_args[0]
        rest = action_args[1:]

        if action == "get":
            path = rest[0] if rest else ""
            cmd_get(path)
        elif action == "set":
            if len(rest) < 2:
                print("Usage: python -m xiaomei_brain.cli config set <path> <value>")
                sys.exit(1)
            cmd_set(rest[0], rest[1])
        elif action == "validate":
            cmd_validate()
        elif action == "file":
            cmd_file()
        else:
            print(f"Unknown action: {action}")
            sys.exit(1)

    elif args[0] == "plugins":
        action_args = args[1:]

        if len(action_args) == 0:
            print("Usage: python -m xiaomei_brain.cli plugins <list|enable|disable> ...")
            sys.exit(1)

        action = action_args[0]
        rest = action_args[1:]

        if action == "list":
            cmd_plugins_list()
        elif action == "enable":
            if not rest:
                print("Usage: python -m xiaomei_brain.cli plugins enable <name>")
                sys.exit(1)
            cmd_plugins_enable(rest[0])
        elif action == "disable":
            if not rest:
                print("Usage: python -m xiaomei_brain.cli plugins disable <name>")
                sys.exit(1)
            cmd_plugins_disable(rest[0])
        else:
            print(f"Unknown action: {action}")
            sys.exit(1)

    else:
        print(f"Unknown command: {args[0]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
