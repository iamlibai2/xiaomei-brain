"""模型目录 — models.dev 集成。

数据源：https://models.dev/api.json（社区维护）
缓存：~/.xiaomei-brain/models_dev_cache.json（程序内部，用户不可见）

与 Hermes 一致：代码内 PROVIDER_META 是兜底，models.dev 提供实时数据。
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)

MODELS_DEV_URL = "https://models.dev/api.json"
CACHE_TTL = 3600  # 内存缓存 1 小时


# ── Provider 元信息 ──

PROVIDER_META: dict[str, dict] = {
    "deepseek":  {"base_url": "https://api.deepseek.com/v1",   "env_vars": ["DEEPSEEK_API_KEY"]},
    "zhipu":     {"base_url": "https://open.bigmodel.cn/api/paas/v4", "env_vars": ["ZHIPU_API_KEY", "GLM_API_KEY"]},
    "openai":    {"base_url": "https://api.openai.com/v1",     "env_vars": ["OPENAI_API_KEY"]},
    "minimax":   {"base_url": "https://api.minimaxi.com/v1",   "env_vars": ["MINIMAX_API_KEY"]},
    "aliyun":    {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "env_vars": ["DASHSCOPE_API_KEY"]},
    "moonshot":  {"base_url": "https://api.moonshot.cn/v1",    "env_vars": ["MOONSHOT_API_KEY"]},
    "kimi":      {"base_url": "https://api.moonshot.cn/v1",    "env_vars": ["KIMI_API_KEY"]},
    "stepfun":   {"base_url": "https://api.stepfun.com/v1",    "env_vars": ["STEPFUN_API_KEY"]},
    "xiaomi":    {"base_url": "https://api.xiaomimimo.com/v1",  "env_vars": ["XIAOMI_API_KEY"]},
    "anthropic": {"base_url": "https://api.anthropic.com",     "env_vars": ["ANTHROPIC_API_KEY"]},
    "google":    {"base_url": "https://generativelanguage.googleapis.com/v1beta", "env_vars": ["GOOGLE_API_KEY"]},
    "xai":       {"base_url": "https://api.x.ai/v1",           "env_vars": ["XAI_API_KEY"]},
}

# 我们的 provider ID → models.dev provider ID
PROVIDER_TO_MODELS_DEV: dict[str, str] = {
    "deepseek": "deepseek",
    "zhipu": "zai",
    "openai": "openai",
    "minimax": "minimax",
    "aliyun": "alibaba",
    "moonshot": "kimi-for-coding",
    "kimi": "kimi-for-coding",
    "stepfun": "stepfun",
    "xiaomi": "xiaomi",
    "anthropic": "anthropic",
    "google": "google",
    "xai": "xai",
}


@dataclass
class ModelInfo:
    """模型元数据。"""
    id: str
    name: str
    provider_id: str
    context_window: int = 0
    max_output: int = 0
    reasoning: bool = False
    tool_call: bool = False
    input_modalities: tuple[str, ...] = ()
    cost_input: float = 0.0
    cost_output: float = 0.0


# ── 缓存管理 ──

_cache: dict[str, Any] | None = None
_cache_time: float = 0


def _cache_path() -> str:
    return os.path.expanduser("~/.xiaomei-brain/models_dev_cache.json")


def _load_disk_cache() -> dict | None:
    path = _cache_path()
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def _save_disk_cache(data: dict) -> None:
    path = _cache_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


# ── 数据获取 ──

def _fetch() -> dict:
    """获取 models.dev 数据（内存 → 磁盘 → 网络）。"""
    global _cache, _cache_time

    # 1. 内存缓存
    if _cache is not None and (time.time() - _cache_time) < CACHE_TTL:
        return _cache

    # 2. 磁盘缓存
    disk = _load_disk_cache()
    if disk:
        _cache = disk
        _cache_time = time.time()
        logger.debug("models.dev: loaded from disk cache")
        return _cache

    # 3. 网络
    try:
        resp = requests.get(MODELS_DEV_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        _cache = data
        _cache_time = time.time()
        _save_disk_cache(data)
        logger.debug("models.dev: fetched %d providers", len(data))
        return data
    except Exception as e:
        logger.warning("models.dev: fetch failed: %s", e)
        # 最后一次尝试磁盘
        if disk:
            _cache = disk
            _cache_time = time.time()
            return disk
        return {}


def refresh() -> None:
    """强制刷新缓存（后台任务调用）。"""
    global _cache, _cache_time
    try:
        resp = requests.get(MODELS_DEV_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        _cache = data
        _cache_time = time.time()
        _save_disk_cache(data)
        logger.debug("models.dev: refreshed %d providers", len(data))
    except Exception as e:
        logger.warning("models.dev: refresh failed: %s", e)


# ── 查询接口 ──

def get_provider_models(provider_id: str) -> list[ModelInfo]:
    """获取某 provider 的模型列表（从 models.dev）。"""
    mdev_id = PROVIDER_TO_MODELS_DEV.get(provider_id)
    if not mdev_id:
        return []

    data = _fetch()
    prov = data.get(mdev_id)
    if not prov:
        return []

    models = prov.get("models", {})
    result = []
    for mid, m in models.items():
        limit = m.get("limit", {})
        cost = m.get("cost", {})
        result.append(ModelInfo(
            id=m.get("id", mid),
            name=m.get("name", mid),
            provider_id=provider_id,
            context_window=limit.get("context", 0),
            max_output=limit.get("output", 0),
            reasoning=m.get("reasoning", False),
            tool_call=m.get("tool_call", False),
            input_modalities=tuple(m.get("modalities", {}).get("input", ["text"])),
            cost_input=cost.get("input", 0.0),
            cost_output=cost.get("output", 0.0),
        ))
    return result


def get_all_providers() -> dict[str, list[ModelInfo]]:
    """返回所有已知 provider 及其模型。"""
    result = {}
    data = _fetch()
    for our_id, mdev_id in PROVIDER_TO_MODELS_DEV.items():
        prov = data.get(mdev_id)
        if not prov:
            continue
        models = prov.get("models", {})
        if not models:
            continue
        result[our_id] = get_provider_models(our_id)
    return result


def list_provider_ids() -> list[str]:
    """列出所有已知 provider ID。"""
    data = _fetch()
    ids = []
    for our_id, mdev_id in PROVIDER_TO_MODELS_DEV.items():
        if mdev_id in data:
            ids.append(our_id)
    return ids
