"""Config Provider - 单一配置数据源，支持 get/patch/apply/hash"""

import hashlib
import json
import os
import threading
from typing import Any, Callable


class ConflictError(Exception):
    """配置冲突：baseHash 不匹配"""
    pass


class ConfigProvider:
    """配置中心 - 单一数据源

    所有配置读写都经过此类，支持：
    - get(path): 获取配置值
    - apply(new_config, base_hash): 完整替换
    - patch(partial, base_hash): 部分更新（JSON Merge Patch）
    - hash: 当前配置的 hash
    """

    def __init__(self, config_path: str):
        self.config_path = os.path.expanduser(config_path)
        self._config: dict = {}
        self._hash: str = ""
        self._lock = threading.RLock()
        self._change_handlers: list[Callable[[dict], None]] = []
        self._load()

    @property
    def hash(self) -> str:
        """返回当前配置的 hash"""
        return self._hash

    @property
    def config(self) -> dict:
        """返回完整配置副本"""
        with self._lock:
            return json.loads(json.dumps(self._config))

    def get(self, path: str = "") -> Any:
        """获取配置，支持 dot notation 路径

        Args:
            path: 配置路径，如 "channels.feishu.enabled"
                  空字符串返回完整配置

        Returns:
            配置值，不存在返回 None
        """
        with self._lock:
            if not path:
                return json.loads(json.dumps(self._config))

            keys = path.split(".")
            value = self._config
            for key in keys:
                if isinstance(value, dict):
                    value = value.get(key)
                else:
                    return None
                if value is None:
                    return None
            return json.loads(json.dumps(value)) if isinstance(value, (dict, list)) else value

    def apply(self, new_config: dict, base_hash: str = "") -> None:
        """完整替换配置

        Args:
            new_config: 新的完整配置
            base_hash: 期望的当前 hash，用于冲突检测

        Raises:
            ConflictError: hash 不匹配（已被其他客户端修改）
        """
        with self._lock:
            if base_hash and base_hash != self._hash:
                raise ConflictError(
                    f"Config has been modified. Expected hash: {base_hash}, current: {self._hash}"
                )

            # 验证配置格式
            if not isinstance(new_config, dict):
                raise ValueError("Config must be a JSON object")

            # 写入文件
            self._write(new_config)

            # 更新内存
            self._config = json.loads(json.dumps(new_config))
            self._hash = self._compute_hash(self._config)

            # 通知变更
            self._notify()

    def patch(self, partial: dict, base_hash: str = "") -> None:
        """部分更新配置（JSON Merge Patch）

        Args:
            partial: 部分配置，会与当前配置深度合并
            base_hash: 期望的当前 hash，用于冲突检测

        Raises:
            ConflictError: hash 不匹配
        """
        with self._lock:
            if base_hash and base_hash != self._hash:
                raise ConflictError(
                    f"Config has been modified. Expected hash: {base_hash}, current: {self._hash}"
                )

            # JSON Merge Patch 语义
            merged = self._deep_merge(self._config, partial)

            # 写入文件
            self._write(merged)

            # 更新内存
            self._config = merged
            self._hash = self._compute_hash(self._config)

            # 通知变更
            self._notify()

    def subscribe(self, handler: Callable[[dict], None]) -> None:
        """订阅配置变更

        Args:
            handler: 变更回调函数，接收新配置作为参数
        """
        self._change_handlers.append(handler)

    def reload(self) -> None:
        """从文件重新加载配置"""
        with self._lock:
            old_hash = self._hash
            self._load()

            if old_hash != self._hash:
                self._notify()

    # ── 内部方法 ──────────────────────────────────────────────

    def _load(self) -> None:
        """从文件加载配置"""
        if os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                try:
                    self._config = json.load(f)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid JSON in config file: {e}")
        else:
            self._config = {}

        self._hash = self._compute_hash(self._config)

    def _write(self, config: dict) -> None:
        """写入配置到文件"""
        dir_path = os.path.dirname(self.config_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    def _compute_hash(self, config: dict) -> str:
        """计算配置的 SHA256 hash"""
        content = json.dumps(config, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _deep_merge(self, base: dict, partial: dict) -> dict:
        """深度合并两个字典（JSON Merge Patch 语义）

        - 对象递归合并
        - null 在 partial 中表示删除
        - 数组整体替换
        """
        result = json.loads(json.dumps(base))

        for key, value in partial.items():
            if value is None:
                # null 表示删除
                result.pop(key, None)
            elif key in result and isinstance(result[key], dict) and isinstance(value, dict):
                # 递归合并对象
                result[key] = self._deep_merge(result[key], value)
            else:
                # 其他情况直接赋值
                result[key] = json.loads(json.dumps(value))

        return result

    def _notify(self) -> None:
        """通知所有订阅者配置已变更"""
        config_copy = json.loads(json.dumps(self._config))
        for handler in self._change_handlers:
            try:
                handler(config_copy)
            except Exception:
                # 订阅者异常不应阻断通知
                pass


# 全局单例
_provider: ConfigProvider | None = None
_provider_lock = threading.Lock()


def get_provider(config_path: str | None = None) -> ConfigProvider:
    """获取全局 ConfigProvider 单例"""
    global _provider
    with _provider_lock:
        if _provider is None:
            if config_path is None:
                config_path = os.path.expanduser("~/.xiaomei-brain/config.json")
            _provider = ConfigProvider(config_path)
        return _provider


def reset_provider() -> None:
    """重置全局单例（用于测试）"""
    global _provider
    with _provider_lock:
        _provider = None
