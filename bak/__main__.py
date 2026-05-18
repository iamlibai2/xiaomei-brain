"""xiaomei-brain CLI entry point.

Usage:
    # 意识系统（推荐）
    PYTHONPATH=src python3 examples/run_conscious_living.py --name xiaomei

    # 无意识系统（植物人状态）
    PYTHONPATH=src python3 examples/run_unconscious.py --name xiaomei
"""

from __future__ import annotations


def main():
    print("xiaomei-brain: multi-agent AI brain framework")
    print()
    print("启动方式:")
    print("  意识系统:   PYTHONPATH=src python3 examples/run_conscious_living.py --name xiaomei")
    print("  无意识系统: PYTHONPATH=src python3 examples/run_unconscious.py --name xiaomei")


if __name__ == "__main__":
    main()
