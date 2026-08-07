"""PluginLoader: 插件发现 → 验证 → 加载。

三段式启动：
  1. Discover — 扫描目录，找到 plugin.yaml，解析 manifest
  2. Validate — 环境变量检查、allow/deny 决策、重复 ID 检查
  3. Load — import 模块，调用 register(ctx)，写入 Registry
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import hashlib
import logging
import os
import sys
import threading
import types
from pathlib import Path
from typing import Any

from .manifest import PluginManifest
from .context import PluginContext
from .registry import PluginRegistry, LoadedPlugin
from ..cli.boot import boot_line

logger = logging.getLogger(__name__)

_EXTERNAL_IMPORT_LOCK = threading.RLock()


# ── WARNING 捕获 ──────────────────────────────────────────

class _WarningCapture(logging.Handler):
    """临时 handler：捕获 register() 期间的 WARNING，用于 boot 格式展示。"""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


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
        # 统一插件目录。Plugin 是代码扩展载体，各目录仅按实现类型分组。
        import xiaomei_brain.plugins as _plugins
        plugins_root = Path(_plugins.__file__).parent
        for category in ("channels", "providers", "body", "tools", "runtimes"):
            category_dir = plugins_root / category
            if category_dir.is_dir():
                dirs.append(str(category_dir))

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
            logger.debug("Entry point discovery failed, skipping third-party plugins", exc_info=True)
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
        """验证 manifest：环境变量、allow/deny、config schema、重复 ID。"""
        plugins_config = self.config.get("plugins", {})
        allow_list: list[str] = plugins_config.get("allow", [])
        deny_list: list[str] = plugins_config.get("deny", [])

        enabled: list[PluginManifest] = []
        for m in manifests:
            label = f"{m.kind}/{m.name}" if m.kind else m.name

            # allow/deny 决策
            if deny_list and m.name in deny_list:
                logger.info("[Plugin] %s 已被 disable", m.name)
                self.registry.track_plugin(LoadedPlugin(manifest=m, status="disabled"))
                boot_line(label, "WARN", "已禁用")
                continue
            if allow_list and m.name not in allow_list:
                logger.info("[Plugin] %s 不在 allow 列表中，跳过", m.name)
                self.registry.track_plugin(LoadedPlugin(manifest=m, status="disabled"))
                boot_line(label, "WARN", "未在白名单")
                continue

            # requires_env 检查
            missing = [ev for ev in m.requires_env if not os.getenv(ev)]
            if missing:
                msg = f"缺失环境变量: {', '.join(missing)}"
                logger.warning("[Plugin] %s 验证失败: %s", m.name, msg)
                self.registry.track_plugin(LoadedPlugin(manifest=m, status="error", error=msg))
                boot_line(label, "WARN", "配置缺失")
                continue

            # configSchema 校验
            schema_error = self._validate_config_schema(m)
            if schema_error:
                logger.warning("[Plugin] %s config schema 校验失败: %s", m.name, schema_error)
                self.registry.track_plugin(LoadedPlugin(manifest=m, status="error", error=schema_error))
                boot_line(label, "FAIL", "配置校验失败")
                continue

            enabled.append(m)
            logger.info("[Plugin] %s 验证通过", m.name)

        return enabled

    def _validate_config_schema(self, m: PluginManifest) -> str | None:
        """用 JSON Schema 校验插件配置。

        Returns:
            None = 通过，str = 错误消息
        """
        if not m.config_schema:
            return None  # 无 schema 则跳过

        plugins_config = self.config.get("plugins", {})
        entries_config = plugins_config.get("entries", {})
        plugin_config = entries_config.get(m.name, {})

        # 内置频道走 channels.<name>.accounts.default
        channels_raw = self.config.get("channels", {})
        channel_config = {}
        if isinstance(channels_raw, dict):
            ch = channels_raw.get(m.name, {})
            if isinstance(ch, dict):
                channel_config = ch.get("accounts", {}).get("default", {})

        try:
            import jsonschema
            jsonschema.validate(instance=plugin_config, schema=m.config_schema)
            jsonschema.validate(instance=channel_config, schema=m.config_schema)
        except ImportError:
            # jsonschema 未安装时做简单 key 检查
            if isinstance(m.config_schema, dict):
                props = m.config_schema.get("properties", {})
                if isinstance(props, dict):
                    allowed = set(props.keys())
                    unknown_plugin = set(plugin_config.keys()) - allowed
                    unknown_channel = set(channel_config.keys()) - allowed
                    if unknown_plugin or unknown_channel:
                        unknown = unknown_plugin | unknown_channel
                        return f"未知配置键: {', '.join(sorted(unknown))}（允许: {', '.join(sorted(allowed))}）"
            return None
        except Exception as e:
            return f"配置校验失败: {e}"

        return None

    # ── Load ─────────────────────────────────────────────────────

    def load(self, manifests: list[PluginManifest]) -> list[LoadedPlugin]:
        """加载插件：import 模块 → 调用 register(ctx) → 写入 Registry。"""
        results: list[LoadedPlugin] = []
        plugins_config = self.config.get("plugins", {})
        entries_config = plugins_config.get("entries", {})

        for m in manifests:
            label = f"{m.kind}/{m.name}" if m.kind else m.name
            try:
                loaded = self._load_one(m, entries_config.get(m.name, {}))
                results.append(loaded)
                if loaded.status == "loaded":
                    boot_line(label, "OK", loaded.summary)
                elif loaded.status == "warn":
                    boot_line(label, "WARN", loaded.error or "")
                else:
                    boot_line(label, "FAIL", loaded.error or "未知错误")
            except Exception as e:
                logger.error("[Plugin] %s 加载失败: %s", m.name, e, exc_info=True)
                results.append(LoadedPlugin(manifest=m, status="error", error=str(e)))
                self.registry.track_plugin(results[-1])
                boot_line(label, "FAIL", str(e)[:30])

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
        if m.dir_path and self._is_external_directory(m.dir_path):
            module_path = self._external_module_name(m.dir_path, module_rel)
        elif m.dir_path:
            # 从目录路径推导 Python 包路径
            # 例如: /path/to/xiaomei_brain/channels/cli → xiaomei_brain.channels.cli.adapter
            module_path = self._dir_to_module(m.dir_path, module_rel)
        else:
            module_path = module_rel

        logger.info("[Plugin] 加载 %s: %s → %s()", m.name, module_path, func_name)

        # import 模块
        try:
            if m.dir_path and self._is_external_directory(m.dir_path):
                module = self._load_external_module(m.dir_path, module_rel, module_path)
            else:
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

        # 捕获 register() 内的 WARNING，用于 boot_line 展示
        capture = _WarningCapture()
        ctx.logger.addHandler(capture)
        try:
            register_fn(ctx)
        finally:
            ctx.logger.removeHandler(capture)

        status = "loaded"
        warn_msg = ""
        if capture.messages:
            status = "warn"
            warn_msg = capture.messages[0]

        loaded = LoadedPlugin(manifest=m, status=status, error=warn_msg or None, summary=ctx.summary)
        self.registry.track_plugin(loaded)
        return loaded

    @staticmethod
    def _is_external_directory(dir_path: str) -> bool:
        import xiaomei_brain

        source_root = Path(xiaomei_brain.__file__).resolve().parent
        try:
            Path(dir_path).resolve().relative_to(source_root)
            return False
        except ValueError:
            return True

    @staticmethod
    def _external_module_name(dir_path: str, module_rel: str) -> str:
        digest = hashlib.sha256(str(Path(dir_path).resolve()).encode("utf-8")).hexdigest()[:16]
        suffix = ".".join(PluginLoader._external_module_parts(module_rel))
        return f"_xiaomei_capability_plugin_{digest}.{suffix}"

    @staticmethod
    def _external_module_parts(module_rel: str) -> list[str]:
        parts = module_rel.split(".")
        if not parts or any(not part.isidentifier() for part in parts):
            raise ImportError(f"外部插件入口模块无效: {module_rel}")
        return parts

    @staticmethod
    def _load_external_module(dir_path: str, module_rel: str, module_name: str):
        """Load one explicitly activated plugin under an isolated namespace.

        The synthetic package keeps relative imports such as ``from .tool``
        working without placing a capability package on global ``sys.path``.
        """
        if module_name in sys.modules:
            return sys.modules[module_name]
        plugin_dir = Path(dir_path).resolve()
        relative = Path(*PluginLoader._external_module_parts(module_rel))
        module_file = plugin_dir / relative.with_suffix(".py")
        package_init = plugin_dir / relative / "__init__.py"
        if module_file.is_file():
            source_path = module_file
            submodule_locations = None
        elif package_init.is_file():
            source_path = package_init
            submodule_locations = [str(package_init.parent)]
        else:
            raise ImportError(f"外部插件入口不存在: {module_rel}")

        namespace = module_name.split(".", 1)[0]
        if namespace not in sys.modules:
            package = types.ModuleType(namespace)
            package.__path__ = [str(plugin_dir)]
            package.__package__ = namespace
            sys.modules[namespace] = package
        spec = importlib.util.spec_from_file_location(
            module_name,
            source_path,
            submodule_search_locations=submodule_locations,
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"无法创建外部插件模块: {module_rel}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            # Capability packages are immutable. Python's normal source loader
            # would otherwise create __pycache__ inside the installed package
            # and make the next integrity check report an unexpected file.
            with _EXTERNAL_IMPORT_LOCK:
                previous = sys.dont_write_bytecode
                sys.dont_write_bytecode = True
                try:
                    spec.loader.exec_module(module)
                finally:
                    sys.dont_write_bytecode = previous
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        return module

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
