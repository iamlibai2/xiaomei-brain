"""Memory tools for the agent."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..base import Tool, tool

if TYPE_CHECKING:
    from ...memory.store import MemoryStore
    from ...memory.episodic import EpisodicMemory


def create_memory_tools(
    memory_store: MemoryStore,
    episodic_memory: EpisodicMemory | None = None,
) -> list[Tool]:
    """Create memory-related tools bound to a MemoryStore instance."""

    @tool(name="memory_search", description="Search memory for relevant information")
    def memory_search(query: str, top_k: int = 3) -> str:
        results = memory_store.search(query, top_k=top_k)
        if not results:
            return "No relevant memories found."
        output = []
        for r in results:
            output.append(f"## {r.topic} (score: {r.score:.2f})\n{r.content}")
        return "\n\n---\n\n".join(output)

    @tool(name="memory_save", description="Save information to memory for future reference")
    def memory_save(topic: str, content: str) -> str:
        memory_store.save(topic, content)
        return f"Memory saved: {topic}"

    @tool(name="memory_list", description="List all available memory topics")
    def memory_list() -> str:
        topics = memory_store.list_topics()
        if not topics:
            return "No memory topics found."
        return "Memory topics:\n" + "\n".join(f"  - {t}" for t in topics)

    @tool(name="memory_delete", description="Delete a memory topic when it's outdated or incorrect")
    def memory_delete(topic: str) -> str:
        if memory_store.delete(topic):
            return f"Memory deleted: {topic}"
        return f"Memory topic not found: {topic}"

    @tool(name="memory_read", description="Read the full content of a specific memory topic")
    def memory_read(topic: str) -> str:
        content = memory_store.read(topic)
        if content is None:
            return f"Memory topic not found: {topic}"
        return content

    tools = [memory_search, memory_save, memory_list, memory_delete, memory_read]

    # Add episodic memory tools if available
    if episodic_memory is not None:
        _episodic = episodic_memory

        @tool(name="memory_episodes", description="List recent episodic memories (events and stories)")
        def memory_episodes(days: int = 7) -> str:
            episodes = _episodic.recent(days=days, limit=5)
            if not episodes:
                return "No recent episodes."
            output = []
            for ep in episodes:
                import time
                ts = time.strftime("%Y-%m-%d", time.localtime(ep.timestamp))
                output.append(f"- [{ts}] {ep.summary}")
                if ep.emotions:
                    output.append(f"  Emotions: {', '.join(ep.emotions)}")
            return "\n".join(output)

        tools.append(memory_episodes)

    return tools
