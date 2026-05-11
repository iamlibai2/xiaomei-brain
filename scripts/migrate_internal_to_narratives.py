#!/usr/bin/env python3
"""Migrate internal memories from memories table to consciousness_narratives table.

Usage:
    python scripts/migrate_internal_to_narratives.py [--agent xiaomei]
"""

import argparse
import os
import sys
import json
import sqlite3


def migrate(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Check if consciousness_narratives table exists
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "consciousness_narratives" not in tables:
        print("ERROR: consciousness_narratives table does not exist. Run with new code first.")
        return -1

    # Use content+created_at as dedup key
    existing_keys = set()
    for r in conn.execute("SELECT content || created_at FROM consciousness_narratives").fetchall():
        existing_keys.add(r[0])

    rows = conn.execute("""
        SELECT id, content, created_at, importance, scene_tags
        FROM memories
        WHERE source = 'internal'
    """).fetchall()

    if not rows:
        print("No internal memories to migrate.")
        return 0

    migrated = 0
    for r in rows:
        memory_id = r["id"]
        content = r["content"]
        created_at = r["created_at"]
        key = f"{content}{created_at}"
        if key in existing_keys:
            continue

        tags_rows = conn.execute(
            "SELECT tag FROM memory_tags WHERE memory_id = ?", (memory_id,)
        ).fetchall()
        tags = [t["tag"] for t in tags_rows]

        if "L3" in tags or "dream" in tags or "deep_burn" in tags:
            trigger = "L3_deep"
        elif "awakening" in tags or "wake" in tags:
            trigger = "awakening"
        else:
            trigger = "L2_light"

        conn.execute(
            """INSERT INTO consciousness_narratives
               (content, trigger, created_at, conversation_summary, energy_level)
               VALUES (?, ?, ?, ?, NULL)""",
            (content, trigger, created_at, f"[migrated from memory#{memory_id}]"),
        )
        migrated += 1
        existing_keys.add(key)

    conn.commit()
    print(f"Migrated {migrated} internal memories to consciousness_narratives.")
    return migrated


def main():
    parser = argparse.ArgumentParser(description="Migrate internal memories to consciousness_narratives")
    parser.add_argument("--agent", default="xiaomei", help="Agent ID (default: xiaomei)")
    args = parser.parse_args()

    db_path = os.path.expanduser(f"~/.xiaomei-brain/agents/{args.agent}/memory/brain.db")
    if not os.path.exists(db_path):
        print(f"ERROR: Database not found: {db_path}")
        sys.exit(1)

    print(f"Database: {db_path}")
    migrated = migrate(db_path)
    print(f"Done. Migrated {migrated} rows.")


if __name__ == "__main__":
    main()
