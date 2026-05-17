#!/usr/bin/env python3
"""Migrate historical data from old tables into experience_stream.

Usage:
    PYTHONPATH=src python3 scripts/migrate_to_experience_stream.py [--agent-id xiaomei]

This script is idempotent — it skips migration if experience_stream already
has data (checked per-source to allow partial recovery).
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from xiaomei_brain.memory.experience_stream import ExperienceStream

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Migrate to experience_stream")
    parser.add_argument("--agent-id", default="xiaomei", help="Agent ID (default: xiaomei)")
    parser.add_argument("--db-path", default=None, help="Direct path to brain.db (overrides --agent-id)")
    args = parser.parse_args()

    if args.db_path:
        db_path = Path(args.db_path)
    else:
        db_path = Path.home() / ".xiaomei-brain" / "agents" / args.agent_id / "memory" / "brain.db"

    if not db_path.exists():
        logger.error("brain.db not found: %s", db_path)
        sys.exit(1)

    logger.info("Opening brain.db: %s", db_path)
    es = ExperienceStream(db_path)

    # Check current state
    total_before = es.count()
    logger.info("experience_stream 当前记录数: %d", total_before)

    # Migrate from messages table
    msg_count = es.migrate_messages(db_path)
    logger.info("messages → experience_stream: %d 条", msg_count)

    # Migrate from consciousness_narratives
    narr_count = es.migrate_consciousness_narratives()
    logger.info("consciousness_narratives → experience_stream: %d 条", narr_count)

    # Migrate from tool_history
    tool_count = es.migrate_tool_history()
    logger.info("tool_history → experience_stream: %d 条", tool_count)

    # Summary
    total_after = es.count()
    new_count = total_after - total_before
    logger.info("=" * 50)
    logger.info("迁移完成: 新增 %d 条记录", new_count)
    logger.info("experience_stream 总记录数: %d", total_after)

    # Show sample
    recent = es.get_recent(limit=5)
    if recent:
        logger.info("最近 5 条:")
        for r in recent:
            logger.info("  [%s] %s", r["type"], r["content"][:80])

    es.close()


if __name__ == "__main__":
    main()
