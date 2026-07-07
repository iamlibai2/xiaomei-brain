"""Plugin bootstrap: 一行调用启动所有插件。

封装配置读取、插件映射、加载、日志上报。
调用方只需传入 agent_id，拿到填充好的 PluginRegistry。
"""

from __future__ import annotations

import logging

from .loader import PluginLoader
from .registry import PluginRegistry

logger = logging.getLogger(__name__)

# ── 缓存：避免重复加载插件（build_agent 和 ConsciousLiving 都会调用）──
_cache: dict[str, PluginRegistry] = {}


def boot_plugins(agent_id: str = "", extra_dirs: list[str] | None = None) -> PluginRegistry:
    """一键启动插件系统。

    从统一 config.json 读取配置 → 映射到插件 entries → Discover → Validate → Load。
    同一 agent_id 只加载一次，后续调用返回缓存。

    Args:
        agent_id: 当前 agent 标识
        extra_dirs: 额外的插件扫描目录（None = 使用默认来源）

    Returns:
        填充好的 PluginRegistry
    """
    cache_key = agent_id or "__default__"
    if cache_key in _cache:
        return _cache[cache_key]

    from ..cli.boot import boot_section
    boot_section("插件系统")

    registry = PluginRegistry()

    # 从统一配置中提取插件配置
    plugins_config = _extract_plugins_config(agent_id)

    loader = PluginLoader(
        registry=registry,
        config={"plugins": plugins_config},
        agent_id=agent_id,
    )

    # 抑制 stderr handler 的 WARNING 输出，保持 boot 画面干净
    from ..cli.boot import boot_muted
    with boot_muted():
        loaded = loader.boot(plugin_dirs=extra_dirs)
    for plugin in loaded:
        if plugin.status == "error":
            logger.error("[Plugin] %s 加载失败: %s", plugin.manifest.name, plugin.error)
        elif plugin.status == "disabled":
            logger.info("[Plugin] %s 已禁用", plugin.manifest.name)
        else:
            logger.info("[Plugin] %s 已加载 (v%s)", plugin.manifest.name, plugin.manifest.version)

    _cache[cache_key] = registry
    return registry


def _extract_plugins_config(agent_id: str = "") -> dict:
    """从统一 config.json 提取插件配置。

    映射规则：
      - plugins.allow / plugins.deny → 启用/禁用特定插件
      - channels.<name>.accounts.<accountId> → 频道插件配置
      - bindings → 按 agent_id 过滤 channels（无 bindings 时全加载）

    Agent config.json 中的 channels / bindings / plugins 会覆盖全局配置。
    """
    entries: dict[str, dict] = {}
    allow: list[str] = []
    deny: list[str] = []

    try:
        raw = _read_merged_config(agent_id)

        # ── plugins.allow / plugins.deny ──────────
        plugins_cfg = raw.get("plugins", {}) if raw else {}
        allow = list(plugins_cfg.get("allow", []))
        deny = list(plugins_cfg.get("deny", []))

        # ── 频道 → 插件映射（通用，不需要逐频道硬编码）──
        _map_channel_configs(raw, entries, agent_id)

    except Exception as e:
        logger.warning("[Plugin] 读取统一配置失败: %s", e)

    return {
        "allow": allow,
        "deny": deny,
        "entries": entries,
    }


def _read_raw_config() -> dict | None:
    """读取原始 config.json（绕过 Config 类型的解析限制）。"""
    import json
    from pathlib import Path

    search_paths = [
        Path("config.json"),
        Path.home() / ".xiaomei-brain" / "config.json",
    ]
    for p in search_paths:
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                logger.debug("failed to load config from %s, trying next path: %s", p, e)
    return None


def _read_merged_config(agent_id: str = "") -> dict | None:
    """浅合并 agent config.json 与全局 config.json。

    agent 的 channels / bindings / plugins 覆盖全局同名 key。
    """
    import json
    from pathlib import Path

    global_data = _read_raw_config()

    if not agent_id:
        return global_data

    agent_config_path = Path.home() / ".xiaomei-brain" / agent_id / "config.json"
    if not agent_config_path.is_file():
        return global_data

    try:
        agent_data = json.loads(agent_config_path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to read agent config: %s", agent_config_path, exc_info=True)
        return global_data

    if global_data:
        merged = dict(global_data)
    else:
        merged = {}

    # Agent 的 channels / bindings / plugins 覆盖全局
    for key in ("channels", "bindings", "plugins"):
        if key in agent_data:
            merged[key] = agent_data[key]

    return merged


def _map_channel_configs(raw: dict | None, entries: dict, agent_id: str = "") -> None:
    """将 config.json channels 节映射到插件 entries（通用，不逐 channel 硬编码）。

    映射规则：
      1. 如果 config.json 有 bindings → 只加载绑定了当前 agent 的 channel，
         使用 binding 中的 accountId 选取对应 account 配置
      2. 如果 bindings 为空 → 全加载所有 enabled channel（向后兼容），
         使用 accounts.default

    config.json 格式：
      {
        "channels": {
          "<name>": {
            "enabled": true,
            "accounts": { "default": { ... }, "<accountId>": { ... } }
          }
        },
        "bindings": [
          { "agentId": "xiaomei", "match": { "channel": "feishu", "accountId": "xiaomei" } }
        ]
      }
    """
    if not raw:
        return

    channels = raw.get("channels", {})
    if not isinstance(channels, dict):
        return

    bindings: list[dict] = raw.get("bindings", [])
    _use_bindings = bool(bindings) and bool(agent_id)

    for name, channel_cfg in channels.items():
        if not isinstance(channel_cfg, dict):
            continue
        if not channel_cfg.get("enabled", True):
            continue

        accounts = channel_cfg.get("accounts", {})
        if not isinstance(accounts, dict):
            continue

        if _use_bindings:
            # 按 bindings 过滤：找到当前 agent 在这个 channel 上的绑定
            account_id = _resolve_binding_account(bindings, agent_id, name)
            if account_id is None:
                logger.info(
                    "[Plugin] 跳过 %s（agent %s 无绑定）", name, agent_id,
                )
                continue
            account_cfg = accounts.get(account_id, {})
            if account_cfg:
                entries[name] = dict(account_cfg)
                logger.info(
                    "[Plugin] %s → account=%s (binding)", name, account_id,
                )
        else:
            # 无 bindings：全加载，使用 default account
            default_account = accounts.get("default", {})
            if default_account:
                entries[name] = dict(default_account)


def _resolve_binding_account(bindings: list[dict], agent_id: str, channel: str) -> str | None:
    """从 bindings 中查找 agent 在指定 channel 上绑定的 accountId。

    Returns:
        accountId 字符串，无匹配返回 None
    """
    for b in bindings:
        if not isinstance(b, dict):
            continue
        if b.get("agentId") != agent_id:
            continue
        match = b.get("match", {})
        if not isinstance(match, dict):
            continue
        if match.get("channel") != channel:
            continue
        # accountId 省略时视为 "default"
        return match.get("accountId", "default")
    return None
