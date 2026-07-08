"""SharedEmbedder — 全局唯一 embedding 单例。

消除多个子系统（LongTermMemory、SkillStorage、DynamicToolLoader）各自加载
SentenceTransformer 的问题。统一通过本模块获取 embedder，全局只加载一次模型。

模型选择: config.json 中 embedding.model 字段, 默认为 BAAI/bge-small-zh-v1.5
    # ~100MB, 512维, 中文优化, 10s内加载
    # 升级到高精度: "embedding": {"model": "BAAI/bge-m3", "dimension": 1024}

使用方式:
    from xiaomei_brain.base.shared_embedder import SharedEmbedder

    shared = SharedEmbedder.get_or_create()
    shared.wait_ready(timeout=30)
    vec = shared.embed("你好")
    vecs = shared.embed_batch(["hello", "world"])
"""

from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger(__name__)

# 默认模型: BAAI/bge-small-zh-v1.5 (~100MB, 512维, 中文优化)
# 在 config.json 中设置 embedding.model 可覆盖，例如: "embedding": {"model": "BAAI/bge-m3"}
# get_or_create() 首次调用时可通过 model_name 参数指定模型
DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"
FALLBACK_MODEL = "all-MiniLM-L6-v2"

_instance_lock = threading.Lock()
_instance: SharedEmbedder | None = None


class SharedEmbedder:
    """全局唯一的 embedding 提供者。

    - 优先远程服务器（EMBED_SERVER_URL 环境变量），fallback 本地 SentenceTransformer
    - 首次 get_or_create() 时启动后台 warmup 线程
    - 线程安全：单例锁 + 模型加载锁
    - GPU→CPU fallback：CUDA 错误时自动切换
    """

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self._model_name = model_name
        self._fallback_model = FALLBACK_MODEL
        self._model: Any = None
        self._model_lock = threading.Lock()
        self._ready = threading.Event()

        # WSL2 / Windows PyTorch 线程数限制，防止 segfault
        for _key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
            os.environ.setdefault(_key, "1")
        os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

        # 远程 embedding 服务
        from xiaomei_brain.base.embedding_client import RemoteEmbedder
        self._remote = RemoteEmbedder()

        # 检查环境变量决定是否加载本地模型
        self._remote_url = os.environ.get("EMBED_SERVER_URL", "")

        # 启动后台 warmup
        t = threading.Thread(target=self._warmup, daemon=True)
        t.start()

    # ── Singleton ─────────────────────────────────────────────

    @classmethod
    def get_or_create(cls, model_name: str = DEFAULT_MODEL) -> SharedEmbedder:
        """获取全局唯一实例。首次调用时创建并启动 warmup。"""
        global _instance
        if _instance is not None:
            return _instance
        with _instance_lock:
            if _instance is not None:
                return _instance
            _instance = cls(model_name=model_name)
            return _instance

    # ── Lifecycle ─────────────────────────────────────────────

    @property
    def remote(self):
        """RemoteEmbedder 实例（供外部向后兼容访问）。"""
        return self._remote

    @property
    def is_remote_available(self) -> bool:
        """远端 embedding 服务是否可用（首次调用时检测）。"""
        return self._remote.available

    def is_ready(self) -> bool:
        """Embedding 模型是否已加载完成。"""
        return self._ready.is_set()

    def wait_ready(self, timeout: float | None = None) -> bool:
        """阻塞等待 embedding 模型加载完成。返回 True 表示就绪。"""
        return self._ready.wait(timeout=timeout)

    @property
    def dim(self) -> int | None:
        """Embedding 向量维度（未就绪时返回 None）。"""
        if self._remote.available:
            return self._remote.dim
        if self._model is not None:
            try:
                return self._model.get_sentence_embedding_dimension()
            except Exception:
                pass
        return None

    # ── Warmup ────────────────────────────────────────────────

    def _warmup(self) -> None:
        """后台线程：预加载 embedding 模型，避免首次 embed() 时延迟。"""
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

        # 配置了远程 URL：只尝试远程
        if self._remote_url:
            if self._remote.available:
                logger.info("Remote embedding server available, using remote (skip local load)")
            else:
                logger.info("EMBED_SERVER_URL configured but remote not reachable, "
                            "will retry on first use")
            self._ready.set()
            return

        # 后台预加载本地模型
        try:
            logger.info("Embedding warmup: loading %s in background...", self._model_name)
            import pyarrow  # 必须在 sentence_transformers 之前导入，避免 pyarrow C 扩展 DLL 首次加载冲突  # noqa: F811
            self._get_model()
            logger.info("Embedding warmup: %s loaded", self._model_name)
        except Exception:
            logger.warning("Embedding warmup failed, will retry on first use", exc_info=True)
        finally:
            self._ready.set()

    # ── Model Loading ─────────────────────────────────────────

    def _load_model(self) -> Any:
        """加载本地 SentenceTransformer 模型（线程安全）。"""
        if self._model is not None:
            return self._model

        with self._model_lock:
            if self._model is not None:
                return self._model

            os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

            # 模型已缓存 → 禁止联网检查，加快加载（必须在 import 之前设置）
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            os.environ["HF_HUB_OFFLINE"] = "1"

            from xiaomei_brain.memory.search import _resolve_model_path
            model_path = _resolve_model_path(self._model_name)

            from contextlib import redirect_stderr
            from io import StringIO
            import pyarrow  # 必须在 sentence_transformers 之前，防止 Windows DLL 冲突  # noqa: F811
            from sentence_transformers import SentenceTransformer

            try:
                logger.info("Loading embedding model: %s", model_path)
                with redirect_stderr(StringIO()):
                    self._model = SentenceTransformer(model_path)
                logger.info("Embedding model loaded: %s", model_path)
            except Exception as e:
                if self._model_name != self._fallback_model:
                    logger.warning(
                        "Failed to load %s, falling back to %s: %s",
                        model_path, self._fallback_model, e,
                    )
                    self._model_name = self._fallback_model
                    self._model = SentenceTransformer(self._fallback_model)
                else:
                    raise

            self._ready.set()
            return self._model

    def _get_model(self) -> Any:
        """获取本地模型实例，未加载则同步加载。"""
        if self._model is not None:
            return self._model
        return self._load_model()

    # ── Embedding ─────────────────────────────────────────────

    def embed(self, text: str) -> list[float]:
        """Embed 单个文本。远程优先，本地 fallback。"""
        if self._remote.available:
            try:
                return self._remote.embed(text)
            except Exception as e:
                logger.warning("[Embed] Remote failed, falling back to local: %s", e)

        model = self._get_model()
        return self._safe_encode(model, text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed 多个文本。远程优先，本地 fallback。"""
        if self._remote.available:
            try:
                return self._remote.embed_batch(texts)
            except Exception as e:
                logger.warning("[Embed] Remote batch failed, falling back to local: %s", e)

        model = self._get_model()
        return self._safe_encode(model, texts, batch=True)

    def _safe_encode(self, model: Any, texts, batch: bool = False) -> list:
        """本地 encode，GPU 优先，CUDA 错误时自动切 CPU 并记住该状态。"""
        try:
            text_count = len(texts) if isinstance(texts, list) else 1
            logger.warning("[Embed] encoding %d text(s)...", text_count)
            vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            logger.warning("[Embed] encoding done")
            return vectors.tolist()
        except RuntimeError as e:
            if "CUDA" not in str(e):
                raise
            from sentence_transformers import SentenceTransformer
            if str(model.device) == "cpu":
                raise
            logger.warning("[Embed] CUDA error, switching to CPU: %s", e)
            self._model = model.to("cpu")
            vectors = self._model.encode(
                texts, normalize_embeddings=True, show_progress_bar=False,
            )
            return vectors.tolist()
