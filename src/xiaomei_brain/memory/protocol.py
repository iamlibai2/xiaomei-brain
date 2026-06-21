"""Memory 层接口协议。

定义 Agent 需要的 Memory 接口，用于跨层依赖的类型标注。
"""

from typing import Any, Protocol


class LongTermMemoryProtocol(Protocol):
    """长期记忆接口。

    Usage:
        def some_function(memory: LongTermMemoryProtocol) -> None:
            results = memory.recall("Python", user_id="user_001")
    """

    def recall(
        self,
        query: str,
        user_id: str = "global",
        top_k: int = 5,
        sources: list[str] | None = None,
        scene: str | None = None,
        time_range: tuple[float, float] | None = None,
        context: str = "auto",
        type_weights: dict[str, float] | None = None,
        mem_type: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def store(
        self,
        content: str,
        source: str = "manual",
        tags: list[str] | None = None,
        importance: float = 0.5,
        user_id: str = "global",
        scene_tags: list[str] | None = None,
        event_time: float | None = None,
        valid_until: float | None = None,
        mem_type: str = "experience",
        confidence: float | None = None,
        skill_domain: str | None = None,
    ) -> int: ...

    def search_by_tags(
        self, tags: list[str], user_id: str = "global", match_all: bool = False,
    ) -> list[dict[str, Any]]: ...

    def count(self) -> int: ...

    def get_recent(self, limit: int = 20, user_id: str = "global") -> list[dict[str, Any]]: ...

    def soft_delete(self, memory_id: int) -> None: ...

    def is_embedder_ready(self) -> bool: ...

    def wait_embedder(self, timeout: float | None = None) -> bool: ...
