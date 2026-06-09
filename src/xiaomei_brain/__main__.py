"""Xiaomei Brain — entry point for `python -m xiaomei_brain`.

Usage:
    python -m xiaomei_brain agent create <name> [--copy-from <existing>]
    python -m xiaomei_brain config get <path>
    python -m xiaomei_brain config set <path> <value>
    python -m xiaomei_brain config validate
    python -m xiaomei_brain config file
    python -m xiaomei_brain plugins list
    python -m xiaomei_brain plugins enable <name>
    python -m xiaomei_brain plugins disable <name>
"""

from xiaomei_brain.cli import main

if __name__ == "__main__":
    main()
