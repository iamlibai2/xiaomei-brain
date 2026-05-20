"""Plugin bootstrap: 一行调用启动所有插件。

封装配置读取、插件映射、加载、日志上报。
调用方只需传入 agent_id，拿到填充好的 PluginRegistry。
"""

from __future__ import annotations

import logging

from .loader import PluginLoader
from .registry import PluginRegistry

logger = logging.getLogger(__name__)


def boot_plugins(agent_id: str = "", extra_dirs: list[str] | None = None) -> PluginRegistry:
    """一键启动插件系统。

    从统一 config.json 读取配置 → 映射到插件 entries → Discover → Validate → Load。

    Args:
        agent_id: 当前 agent 标识
        extra_dirs: 额外的插件扫描目录（None = 使用默认来源）

    Returns:
        填充好的 PluginRegistry
    """
    registry = PluginRegistry()

    # 从统一配置中提取插件配置
    plugins_config = _extract_plugins_config()

    loader = PluginLoader(
        registry=registry,
        config={"plugins": plugins_config},
        agent_id=agent_id,
    )
    loaded = loader.boot(plugin_dirs=extra_dirs)
    for plugin in loaded:
        if plugin.status == "error":
            logger.error("[Plugin] %s 加载失败: %s", plugin.manifest.name, plugin.error)
        elif plugin.status == "disabled":
            logger.info("[Plugin] %s 已禁用", plugin.manifest.name)
        else:
            logger.info("[Plugin] %s 已加载 (v%s)", plugin.manifest.name, plugin.manifest.version)

    return registry


def _extract_plugins_config() -> dict:
    """从统一 config.json 提取插件配置。

    映射规则：
      - plugins.allow / plugins.deny → 启用/禁用特定插件
      - channels.<name>.accounts.default → 频道插件配置（原样传递）
    """
    entries: dict[str, dict] = {}
    allow: list[str] = []
    deny: list[str] = []

    try:
        raw = _read_raw_config()

        # ── plugins.allow / plugins.deny ──────────
        plugins_cfg = raw.get("plugins", {}) if raw else {}
        allow = list(plugins_cfg.get("allow", []))
        deny = list(plugins_cfg.get("deny", []))

        # ── 频道 → 插件映射（通用，不需要逐频道硬编码）──
        _map_channel_configs(raw, entries)

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
            except Exception:
                pass
    return None


def _map_channel_configs(raw: dict | None, entries: dict) -> None:
    """将 config.json channels 节映射到插件 entries（通用，不逐 channel 硬编码）。

    约定：
      config.json:
        "channels": {
          "<name>": {
            "enabled": true,
            "accounts": { "default": { ... } }
          }
        }

      → entries["<name>"] = accounts.default（原样传递，插件自行解析 key 名）
    """
    if not raw:
        return

    channels = raw.get("channels", {})
    if not isinstance(channels, dict):
        return

    for name, channel_cfg in channels.items():
        if not isinstance(channel_cfg, dict):
            continue
        if not channel_cfg.get("enabled", True):
            continue

        accounts = channel_cfg.get("accounts", {})
        if not isinstance(accounts, dict):
            continue

        default_account = accounts.get("default", {})
        if default_account:
            entries[name] = dict(default_account)
