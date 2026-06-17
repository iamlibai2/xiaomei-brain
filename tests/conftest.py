"""Shared fixtures for xiaomei-brain unit tests.

All fixtures here are PURE -- no network, no file I/O, no LLM calls.
"""

import pytest
import tempfile
import shutil

from xiaomei_brain.drive.config import DriveConfig


@pytest.fixture
def drive_config():
    """Drive configuration with defaults (no file I/O)."""
    return DriveConfig()


@pytest.fixture
def rootdir():
    """Temporary directory for file-based tests (auto-cleaned)."""
    path = tempfile.mkdtemp()
    yield path
    shutil.rmtree(path, ignore_errors=True)
