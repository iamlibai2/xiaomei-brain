"""Smoke test — verify package is installed and core systems work.

No LLM calls, no network, no interactive input. Runs in < 10 seconds.
"""

import subprocess
import sys


def test_cli_agent_list():
    """`xiaomei-brain agent list` should exit cleanly."""
    result = subprocess.run(
        [sys.executable, "-m", "xiaomei_brain", "agent", "list"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"


def test_cli_unknown_command():
    """Unknown command should exit with code 1."""
    result = subprocess.run(
        [sys.executable, "-m", "xiaomei_brain", "__nonexistent_cmd__"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 1
    assert "Unknown command" in result.stdout


def test_agent_manager_list():
    """AgentManager.list() should not crash."""
    from xiaomei_brain.agent.agent_manager import AgentManager
    manager = AgentManager()
    agents = manager.list()
    assert isinstance(agents, list)


def test_import_core_modules():
    """All core modules should be importable."""
    import xiaomei_brain.agent.core
    import xiaomei_brain.memory.longterm
    import xiaomei_brain.memory.conversation_db
    import xiaomei_brain.memory.dag
    import xiaomei_brain.memory.extractor
    import xiaomei_brain.drive
    import xiaomei_brain.purpose
    import xiaomei_brain.consciousness.core
    import xiaomei_brain.llm.client
    import xiaomei_brain.config
    import xiaomei_brain.cli.setup
    import xiaomei_brain.cli.run
    import xiaomei_brain.cli.boot
    import xiaomei_brain.cli.install
    import xiaomei_brain.cli.memory
    import xiaomei_brain.cli.channel
    import xiaomei_brain.cli.lifecycle
    # If we got here, all imports succeeded
    assert True


def test_cli_memory_help():
    """`xiaomei-brain memory` without args should show usage error (not crash)."""
    result = subprocess.run(
        [sys.executable, "-m", "xiaomei_brain", "memory"],
        capture_output=True, text=True, timeout=10,
    )
    # argparse exits with 2 for missing required args
    assert result.returncode == 2


def test_cli_channel_list():
    """`xiaomei-brain channel list` should exit cleanly."""
    result = subprocess.run(
        [sys.executable, "-m", "xiaomei_brain", "channel", "list"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"


def test_cli_status():
    """`xiaomei-brain status` should exit cleanly (even without running agent)."""
    result = subprocess.run(
        [sys.executable, "-m", "xiaomei_brain", "status", "xiaomei"],
        capture_output=True, text=True, timeout=10,
    )
    # status exits 0 whether agent is running or not
    assert result.returncode == 0, f"stderr: {result.stderr}"


def test_longterm_memory_instantiation():
    """LongTermMemory can be instantiated with a temp db."""
    import tempfile, os
    from xiaomei_brain.memory.longterm import LongTermMemory

    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        ltm = LongTermMemory(db_path)
        assert ltm.is_embedder_ready() is not None  # Event exists
        assert ltm.wait_embedder(timeout=0.1) is not None  # Method works
