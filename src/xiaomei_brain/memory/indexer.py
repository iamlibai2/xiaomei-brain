"""Memory index management (MEMORY.md + topic files)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class IndexEntry:
    """A single entry in the memory index."""

    topic: str
    summary: str = ""
    keywords: list[str] = field(default_factory=list)


class MemoryIndexer:
    """Manage the MEMORY.md index file that lists all topics."""

    def __init__(self, memory_dir: str) -> None:
        self.memory_dir = memory_dir
        self.index_path = os.path.join(memory_dir, "MEMORY.md")
        self.topics_dir = os.path.join(memory_dir, "topics")

    def read_index(self) -> list[IndexEntry]:
        """Read the MEMORY.md index file and parse entries."""
        if not os.path.exists(self.index_path):
            logger.debug("Index file not found: %s", self.index_path)
            return []
        logger.info("Reading index from: %s", self.index_path)

        entries = []
        with open(self.index_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line.startswith("## "):
                    continue
                # Parse: ## topic-name | summary | 关键词: k1, k2
                content = line[3:].strip()
                parts = content.split("|")
                topic = parts[0].strip()
                summary = parts[1].strip() if len(parts) > 1 else ""
                keywords = []
                if len(parts) > 2:
                    kw_str = parts[2].strip()
                    if kw_str.startswith("关键词:"):
                        kw_str = kw_str[len("关键词:"):].strip()
                    keywords = [k.strip() for k in kw_str.split(",") if k.strip()]
                entries.append(IndexEntry(topic=topic, summary=summary, keywords=keywords))
        logger.info("Read %d index entries", len(entries))
        return entries

    def write_index(self, entries: list[IndexEntry]) -> None:
        """Write entries to the MEMORY.md index file."""
        logger.info("Writing %d entries to index: %s", len(entries), self.index_path)
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        lines = ["# Memory Index\n"]
        for entry in entries:
            kw_str = ", ".join(entry.keywords) if entry.keywords else ""
            parts = [entry.topic]
            if entry.summary:
                parts.append(entry.summary)
            if kw_str:
                parts.append(f"关键词: {kw_str}")
            lines.append("## " + " | ".join(parts) + "\n")
        with open(self.index_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

    def add_entry(self, entry: IndexEntry) -> None:
        """Add or update a single entry in the index."""
        entries = self.read_index()
        # Update existing or append new
        for i, existing in enumerate(entries):
            if existing.topic == entry.topic:
                entries[i] = entry
                self.write_index(entries)
                return
        entries.append(entry)
        self.write_index(entries)

    def rebuild_index(self) -> list[IndexEntry]:
        """Scan topic files and rebuild the index."""
        os.makedirs(self.topics_dir, exist_ok=True)
        entries = []
        for fname in sorted(os.listdir(self.topics_dir)):
            if not fname.endswith(".md"):
                continue
            topic = fname[:-3]  # Remove .md
            # Read first line as summary
            filepath = os.path.join(self.topics_dir, fname)
            with open(filepath, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
                # Remove leading # if present
                summary = first_line.lstrip("#").strip() if first_line else ""
            entries.append(IndexEntry(topic=topic, summary=summary))
        self.write_index(entries)
        return entries
