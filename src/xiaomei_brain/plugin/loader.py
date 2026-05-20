"""PluginLoader: 插件发现 → 验证 → 加载。

三段式启动：
  1. Discover — 扫描目录，找到 plugin.yaml，解析 manifest
  2. Validate — 环境变量检查、allow/deny 决策、重复 ID 检查
  3. Load — import 模块，调用 register(ctx)，写入 Registry
"""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
import os
import sys
from pathlib import Path
from typing import Any

from .manifest import PluginManifest
from .context import PluginContext
from .registry import PluginRegistry, LoadedPlugin

logger = logging.getLogger(__name__)


class PluginLoader:
    """插件加载器。

    从多个来源发现并加载插件：内置/用户/项目/Pip entry-points。
    """

    def __init__(self, registry: PluginRegistry, config: dict | None = None, agent_id: str = "") -> None:
        self.registry = registry
        self.config = config or {}
        self.agent_id = agent_id

    # ── Boot ─────────────────────────────────────────────────────

    def boot(self, plugin_dirs: list[str] | None = None) -> list[LoadedPlugin]:
        """一键：discover → validate → load。

        Args:
            plugin_dirs: 要扫描的目录列表。None = 使用默认来源。
        """
        if plugin_dirs is None:
            plugin_dirs = self._default_dirs()
        return self.load(self.validate(self.discover(plugin_dirs)))

    def _default_dirs(self) -> list[str]:
        """默认插件扫描目录。"""
        dirs: list[str] = []
        # 内置频道（channels/ 现有目录）
        import xiaomei_brain.channels as _channels
        channels_root = Path(_channels.__file__).parent
        dirs.append(str(channels_root))

        # 用户插件
        user_plugins = Path.home() / ".xiaomei-brain" / "plugins"
        dirs.append(str(user_plugins))

        # 项目插件
        project_plugins = Path(".xiaomei-brain") / "plugins"
        if project_plugins.is_dir():
            dirs.append(str(project_plugins.resolve()))

        return dirs

    # ── Discover ──────────────────────────────────────────────────

    def discover(self, plugin_dirs: list[str] | None = None) -> list[PluginManifest]:
        """扫描目录，发现所有 plugin.yaml。不执行插件代码。

        Args:
            plugin_dirs: 要扫描的目录列表。None = 使用默认来源。
        """
        if plugin_dirs is None:
            plugin_dirs = self._default_dirs()

        manifests: list[PluginManifest] = []
        seen: set[str] = set()

        for dir_path in plugin_dirs:
            root = Path(dir_path).expanduser().resolve()
            if not root.is_dir():
                continue
            for child in sorted(root.iterdir()):
                if not child.is_dir():
                    continue
                if child.name.startswith("_") or child.name.startswith("."):
                    continue
                manifest = PluginManifest.from_directory(child)
                if manifest is None:
                    continue
                if manifest.name in seen:
                    logger.warning("[Plugin] 重复插件 ID '%s'（%s），跳过", manifest.name, child)
                    continue
                seen.add(manifest.name)
                manifests.append(manifest)
                logger.info("[Plugin] 发现: %s (%s) v%s — %s", manifest.name, manifest.kind, manifest.version, child)

        # Pip entry-points
        manifests.extend(self._discover_entry_points(seen))

        return manifests

    def _discover_entry_points(self, seen: set[str]) -> list[PluginManifest]:
        """从 entry_points 发现第三方插件。"""
        result: list[PluginManifest] = []
        try:
            eps = importlib.metadata.entry_points(group="xiaomei_brain.plugins")
        except Exception:
            return result

        for ep in eps:
            if ep.name in seen:
                continue
            # 从 entry_point 构造最小的 manifest
            manifest = PluginManifest(
                name=ep.name,
                version="0.0.0",
                description=f"第三方插件: {ep.name}",
                kind="bundle",
                entry=ep.value,  # "module:register" 格式
            )
            seen.add(ep.name)
            result.append(manifest)
            logger.info("[Plugin] 发现 entry_point: %s → %s", ep.name, ep.value)

        return result

    # ── Validate ──────────────────────────────────────────────────

    def validate(self, manifests: list[PluginManifest]) -> list[PluginManifest]:
        """验证 manifest：环境变量、allow/deny、重复 ID。"""
        plugins_config = self.config.get("plugins", {})
        allow_list: list[str] = plugins_config.get("allow", [])
        deny_list: list[str] = plugins_config.get("deny", [])

        enabled: list[PluginManifest] = []
        for m in manifests:
            # allow/deny 决策
            if deny_list and m.name in deny_list:
                logger.info("[Plugin] %s 已被 disable", m.name)
                self.registry.track_plugin(LoadedPlugin(manifest=m, status="disabled"))
                continue
            if allow_list and m.name not in allow_list:
                logger.info("[Plugin] %s 不在 allow 列表中，跳过", m.name)
                self.registry.track_plugin(LoadedPlugin(manifest=m, status="disabled"))
                continue

            # requires_env 检查
            missing = [ev for ev in m.requires_env if not os.getenv(ev)]
            if missing:
                msg = f"缺失环境变量: {', '.join(missing)}"
                logger.warning("[Plugin] %s 验证失败: %s", m.name, msg)
                self.registry.track_plugin(LoadedPlugin(manifest=m, status="error", error=msg))
                continue

            enabled.append(m)
            logger.info("[Plugin] %s 验证通过", m.name)

        return enabled

    # ── Load ─────────────────────────────────────────────────────

    def load(self, manifests: list[PluginManifest]) -> list[LoadedPlugin]:
        """加载插件：import 模块 → 调用 register(ctx) → 写入 Registry。"""
        results: list[LoadedPlugin] = []
        plugins_config = self.config.get("plugins", {})
        entries_config = plugins_config.get("entries", {})

        for m in manifests:
            try:
                loaded = self._load_one(m, entries_config.get(m.name, {}))
                results.append(loaded)
            except Exception as e:
                logger.error("[Plugin] %s 加载失败: %s", m.name, e, exc_info=True)
                results.append(LoadedPlugin(manifest=m, status="error", error=str(e)))
                self.registry.track_plugin(results[-1])

        return results

    def _load_one(self, m: PluginManifest, plugin_config: dict) -> LoadedPlugin:
        """加载单个插件。"""
        # 解析 entry_point: "adapter:register" → 找到模块和函数
        entry = m.entry
        if ":" in entry:
            module_rel, func_name = entry.split(":", 1)
        else:
            module_rel = "adapter"
            func_name = "register"

        # 构建完整的模块路径
        if m.dir_path:
            # 从目录路径推导 Python 包路径
            # 例如: /path/to/xiaomei_brain/channels/cli → xiaomei_brain.channels.cli.adapter
            module_path = self._dir_to_module(m.dir_path, module_rel)
        else:
            module_path = module_rel

        logger.info("[Plugin] 加载 %s: %s → %s()", m.name, module_path, func_name)

        # import 模块
        try:
            module = importlib.import_module(module_path)
        except ImportError as e:
            return LoadedPlugin(manifest=m, status="error", error=f"导入失败: {e}")

        # 查找 register 函数
        register_fn = getattr(module, func_name, None)
        if register_fn is None:
            return LoadedPlugin(manifest=m, status="error", error=f"未找到 {func_name}() 函数")

        # 创建 PluginContext，调用 register(ctx)
        ctx = PluginContext(
            config=plugin_config,
            plugin_name=m.name,
            agent_id=self.agent_id,
            registry=self.registry,
        )
        register_fn(ctx)

        loaded = LoadedPlugin(manifest=m, status="loaded")
        self.registry.track_plugin(loaded)
        return loaded

    def _dir_to_module(self, dir_path: str, module_rel: str) -> str:
        """从文件系统路径推导 Python 包路径。

        例如:
          /home/.../src/xiaomei_brain/channels/cli + adapter
          → xiaomei_brain.channels.cli.adapter

        通过向上遍历 __init__.py，自动识别包边界。
        """
        p = Path(dir_path).resolve()
        parts: list[str] = []

        current = p
        while current.name:
            init = current / "__init__.py"
            if not init.is_file():
                break
            parts.insert(0, current.name)
            current = current.parent

        if not parts:
            # 目录本身不是包 → 使用 module_rel 作为顶级路径
            return module_rel

        # 丢弃 "src" 前缀（如果存在）
        if parts[0] == "src":
            parts.pop(0)

        if not parts:
            return module_rel

        package = ".".join(parts)
        return f"{package}.{module_rel.replace('/', '.')}"
