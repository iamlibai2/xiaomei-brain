"""PluginManifest: plugin.yaml 解析与数据结构。

参考 Hermes Agent 的 plugin.yaml 格式，简化且 Pythonic。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

VALID_KINDS = frozenset({"channel", "provider", "tool", "speech", "memory", "hook", "bundle"})


@dataclass
class PluginManifest:
    """插件元数据，从 plugin.yaml 解析。"""

    name: str
    version: str
    description: str
    kind: str                          # channel | provider | tool | speech | memory | hook | bundle
    channel: str | None = None         # 频道标识（kind=channel 时）
    requires_env: list[str] = field(default_factory=list)
    provides_tools: list[str] = field(default_factory=list)
    provides_hooks: list[str] = field(default_factory=list)
    entry: str = "adapter:register"    # 入口函数路径（模块路径省略前缀部分）
    config_schema: dict | None = None   # JSON Schema for plugin config（可选）

    # 插件所在目录（不来自 yaml，由 loader 填充）
    dir_path: str = ""

    @classmethod
    def from_yaml(cls, path: Path) -> PluginManifest | None:
        """从 plugin.yaml 文件解析 PluginManifest。

        Args:
            path: plugin.yaml 文件的完整路径

        Returns:
            PluginManifest 或 None（解析失败时）
        """
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                logger.warning("[Plugin] %s 格式无效：不是字典", path)
                return None
        except yaml.YAMLError as e:
            logger.warning("[Plugin] %s YAML 解析失败: %s", path, e)
            return None
        except Exception as e:
            logger.warning("[Plugin] %s 读取失败: %s", path, e)
            return None

        # 必填字段校验
        name = data.get("name", "")
        if not name:
            logger.warning("[Plugin] %s 缺少必填字段 'name'", path)
            return None

        kind = data.get("kind", "")
        if kind not in VALID_KINDS:
            logger.warning("[Plugin] %s kind=%s 无效，有效值: %s", path, kind, sorted(VALID_KINDS))
            return None

        config_schema = data.get("configSchema")
        if config_schema is not None and not isinstance(config_schema, dict):
            logger.warning("[Plugin] %s configSchema 不是 dict，忽略", path)
            config_schema = None

        return cls(
            name=name,
            version=str(data.get("version", "0.0.0")),
            description=data.get("description", ""),
            kind=kind,
            channel=data.get("channel"),
            requires_env=data.get("requires_env", []) or [],
            provides_tools=data.get("provides_tools", []) or [],
            provides_hooks=data.get("provides_hooks", []) or [],
            entry=data.get("entry", "adapter:register"),
            config_schema=config_schema,
            dir_path=str(path.parent),
        )

    @classmethod
    def from_directory(cls, dir_path: Path) -> PluginManifest | None:
        """从目录中查找并解析 plugin.yaml。"""
        yaml_path = dir_path / "plugin.yaml"
        if not yaml_path.is_file():
            return None
        manifest = cls.from_yaml(yaml_path)
        if manifest:
            manifest.dir_path = str(dir_path)
        return manifest
