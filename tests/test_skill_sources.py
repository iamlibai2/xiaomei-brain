"""Skill source adapter and CLI tests.

Tests for:
- Source adapter resolution (can_handle, resolve)
- GitHub URL building and mirror fallback
- CLI arg parsing
- Install flow with mocked network requests
- Error handling
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, Mock

import pytest

# ── Fixtures ───────────────────────────────────────────────────


@pytest.fixture
def tmp_agent_dir():
    """Create a temporary agent directory with brain.db."""
    d = tempfile.mkdtemp()
    agent_dir = os.path.join(d, "testbot")
    os.makedirs(agent_dir)
    # Create empty brain.db
    import sqlite3
    conn = sqlite3.connect(os.path.join(agent_dir, "brain.db"))
    conn.close()
    yield agent_dir
    import shutil
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def mock_requests():
    """Mock requests.get to return a fake SKILL.md."""
    with patch("requests.get") as mock_get:
        yield mock_get


# ── SourceBundle ───────────────────────────────────────────────

class TestSourceBundle:
    def test_creation(self):
        from xiaomei_brain.skills.sources.base import SourceBundle
        bundle = SourceBundle(
            content="---\nname: test\n---\n# Hello",
            source="url",
            identifier="https://example.com/SKILL.md",
            resolved_url="https://example.com/SKILL.md",
        )
        assert bundle.content
        assert bundle.source == "url"
        assert bundle.metadata == {}

    def test_creation_with_metadata(self):
        from xiaomei_brain.skills.sources.base import SourceBundle
        bundle = SourceBundle(
            content="test",
            source="github",
            identifier="owner/repo",
            resolved_url="https://raw.githubusercontent.com/owner/repo/main/SKILL.md",
            metadata={"repo_owner": "owner", "repo_name": "repo"},
        )
        assert bundle.metadata["repo_owner"] == "owner"


# ── URL Adapter ────────────────────────────────────────────────

class TestURLSourceAdapter:
    def test_can_handle_https(self):
        from xiaomei_brain.skills.sources.url import URLSourceAdapter
        adapter = URLSourceAdapter()
        assert adapter.can_handle("https://example.com/SKILL.md")
        assert adapter.can_handle("http://example.com/SKILL.md")

    def test_can_handle_rejects_plain_text(self):
        from xiaomei_brain.skills.sources.url import URLSourceAdapter
        adapter = URLSourceAdapter()
        assert not adapter.can_handle("owner/repo")
        assert not adapter.can_handle("not-a-url")

    def test_resolve_is_identity(self):
        from xiaomei_brain.skills.sources.url import URLSourceAdapter
        adapter = URLSourceAdapter()
        url = "https://example.com/SKILL.md"
        assert adapter.resolve(url) == url

    def test_fetch_returns_bundle(self, mock_requests):
        from xiaomei_brain.skills.sources.url import URLSourceAdapter
        from xiaomei_brain.skills.sources.base import SourceBundle

        mock_resp = Mock()
        mock_resp.text = "---\nname: test-skill\n---\n# My Skill"
        mock_resp.headers = {"content-type": "text/plain"}
        mock_resp.raise_for_status = Mock()
        mock_requests.return_value = mock_resp

        adapter = URLSourceAdapter()
        bundle = adapter.fetch("https://example.com/SKILL.md")
        assert bundle.content == "---\nname: test-skill\n---\n# My Skill"
        assert bundle.source == "url"
        assert bundle.resolved_url == "https://example.com/SKILL.md"

    def test_fetch_html_error_blob_url(self, mock_requests):
        from xiaomei_brain.skills.sources.url import URLSourceAdapter

        mock_resp = Mock()
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.raise_for_status = Mock()
        mock_requests.return_value = mock_resp

        adapter = URLSourceAdapter()
        with pytest.raises(ValueError, match="raw"):
            adapter.fetch("https://github.com/owner/repo/blob/main/SKILL.md")

    def test_fetch_html_error_generic(self, mock_requests):
        from xiaomei_brain.skills.sources.url import URLSourceAdapter

        mock_resp = Mock()
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.raise_for_status = Mock()
        mock_requests.return_value = mock_resp

        adapter = URLSourceAdapter()
        with pytest.raises(ValueError, match="HTML"):
            adapter.fetch("https://example.com/page")


# ── GitHub Adapter ─────────────────────────────────────────────

class TestGitHubSourceAdapter:
    def test_can_handle_owner_repo(self):
        from xiaomei_brain.skills.sources.github import GitHubSourceAdapter
        adapter = GitHubSourceAdapter()
        assert adapter.can_handle("owner/repo")
        assert adapter.can_handle("owner-name/repo-name")
        assert adapter.can_handle("owner/repo/path")

    def test_can_handle_rejects_url(self):
        from xiaomei_brain.skills.sources.github import GitHubSourceAdapter
        adapter = GitHubSourceAdapter()
        assert not adapter.can_handle("https://github.com/owner/repo")
        assert not adapter.can_handle("http://example.com")
        assert not adapter.can_handle("not-repo")

    def test_can_handle_rejects_single_word(self):
        from xiaomei_brain.skills.sources.github import GitHubSourceAdapter
        adapter = GitHubSourceAdapter()
        assert not adapter.can_handle("just-a-word")

    def test_can_handle_with_ref(self):
        from xiaomei_brain.skills.sources.github import GitHubSourceAdapter
        adapter = GitHubSourceAdapter()
        assert adapter.can_handle("owner/repo:main")

    def test_can_handle_with_path_and_ref(self):
        from xiaomei_brain.skills.sources.github import GitHubSourceAdapter
        adapter = GitHubSourceAdapter()
        assert adapter.can_handle("owner/repo/path/to/skill:dev")

    def test_resolve_simple(self):
        from xiaomei_brain.skills.sources.github import GitHubSourceAdapter
        adapter = GitHubSourceAdapter()
        url = adapter.resolve("owner/repo")
        assert url == "https://raw.githubusercontent.com/owner/repo/main/SKILL.md"

    def test_resolve_with_path(self):
        from xiaomei_brain.skills.sources.github import GitHubSourceAdapter
        adapter = GitHubSourceAdapter()
        url = adapter.resolve("owner/repo/subdir/skill")
        assert url == "https://raw.githubusercontent.com/owner/repo/main/subdir/skill/SKILL.md"

    def test_resolve_with_ref(self):
        from xiaomei_brain.skills.sources.github import GitHubSourceAdapter
        adapter = GitHubSourceAdapter()
        url = adapter.resolve("owner/repo:dev")
        assert url == "https://raw.githubusercontent.com/owner/repo/dev/SKILL.md"

    def test_resolve_with_path_and_ref(self):
        from xiaomei_brain.skills.sources.github import GitHubSourceAdapter
        adapter = GitHubSourceAdapter()
        url = adapter.resolve("owner/repo/path:dev")
        assert url == "https://raw.githubusercontent.com/owner/repo/dev/path/SKILL.md"

    def test_resolve_invalid(self):
        from xiaomei_brain.skills.sources.github import GitHubSourceAdapter
        adapter = GitHubSourceAdapter()
        with pytest.raises(ValueError, match="无效"):
            adapter.resolve("not-a-valid-identifier")

    def test_build_url_with_custom_base(self):
        from xiaomei_brain.skills.sources.github import GitHubSourceAdapter
        adapter = GitHubSourceAdapter()
        url = adapter._build_url("owner/repo", "https://custom.mirror.com")
        assert url == "https://custom.mirror.com/owner/repo/main/SKILL.md"

    def test_fetch_success(self, mock_requests):
        from xiaomei_brain.skills.sources.github import GitHubSourceAdapter

        mock_resp = Mock()
        mock_resp.text = "---\nname: test\n---\n# My Skill"
        mock_resp.status_code = 200
        mock_resp.raise_for_status = Mock()
        mock_requests.return_value = mock_resp

        adapter = GitHubSourceAdapter()
        bundle = adapter.fetch("owner/repo")
        assert bundle.content == "---\nname: test\n---\n# My Skill"
        assert bundle.source == "github"
        assert bundle.metadata["repo_owner"] == "owner"
        assert bundle.metadata["repo_name"] == "repo"
        assert bundle.metadata["ref"] == "main"

    def test_fetch_404(self, mock_requests):
        from xiaomei_brain.skills.sources.github import GitHubSourceAdapter

        mock_resp = Mock()
        mock_resp.status_code = 404
        mock_requests.return_value = mock_resp

        adapter = GitHubSourceAdapter()
        with pytest.raises(FileNotFoundError, match="未找到"):
            adapter.fetch("owner/nonexistent")

    def test_fetch_mirror_fallback(self, mock_requests):
        """When first URL fails with ConnectionError, try mirrors."""
        from xiaomei_brain.skills.sources.github import GitHubSourceAdapter
        import requests as requests_lib
        from xiaomei_brain.skills.sources import github as github_mod

        # First call: connection failure. Second call: success.
        mock_resp_fail = Mock()
        mock_resp_success = Mock()
        mock_resp_success.text = "---\nname: test\n---\n# Content"
        mock_resp_success.status_code = 200
        mock_resp_success.raise_for_status = Mock()

        mock_requests.side_effect = [
            requests_lib.ConnectionError("timeout"),  # direct
            mock_resp_success,                          # mirror
        ]

        # Ensure mirrors are initialized
        github_mod._MIRRORS.clear()

        adapter = GitHubSourceAdapter()
        bundle = adapter.fetch("owner/repo")
        assert bundle.content == "---\nname: test\n---\n# Content"
        # Should have used the mirror URL
        assert "raw.githubusercontent.com" not in bundle.resolved_url

    def test_fetch_all_fail(self, mock_requests):
        """When all URLs fail, raise RuntimeError."""
        from xiaomei_brain.skills.sources.github import GitHubSourceAdapter
        import requests as requests_lib
        from xiaomei_brain.skills.sources import github as github_mod

        mock_requests.side_effect = requests_lib.ConnectionError("timeout")

        github_mod._MIRRORS.clear()

        adapter = GitHubSourceAdapter()
        with pytest.raises(RuntimeError, match="所有 GitHub 源均不可达"):
            adapter.fetch("owner/repo")


# ── Adapter Registry ───────────────────────────────────────────

class TestResolveSource:
    def test_url_identifier(self):
        from xiaomei_brain.skills.sources import resolve_source
        from xiaomei_brain.skills.sources.url import URLSourceAdapter
        adapter = resolve_source("https://example.com/SKILL.md")
        assert isinstance(adapter, URLSourceAdapter)

    def test_github_identifier(self):
        from xiaomei_brain.skills.sources import resolve_source
        from xiaomei_brain.skills.sources.github import GitHubSourceAdapter
        adapter = resolve_source("owner/repo")
        assert isinstance(adapter, GitHubSourceAdapter)

    def test_github_url_prefers_url_adapter(self):
        """GitHub URLs should be handled by URL adapter, not GitHub adapter."""
        from xiaomei_brain.skills.sources import resolve_source
        from xiaomei_brain.skills.sources.url import URLSourceAdapter
        adapter = resolve_source("https://github.com/owner/repo/blob/main/SKILL.md")
        assert isinstance(adapter, URLSourceAdapter)

    def test_unknown_identifier(self):
        from xiaomei_brain.skills.sources import resolve_source
        with pytest.raises(ValueError, match="无法识别"):
            resolve_source("not-a-valid-format-at-all")

    def test_register_adapter(self):
        from xiaomei_brain.skills.sources import register_adapter, resolve_source
        from xiaomei_brain.skills.sources.base import BaseSourceAdapter, SourceBundle

        class MockAdapter(BaseSourceAdapter):
            def can_handle(self, identifier):
                return identifier == "custom:test"
            def resolve(self, identifier):
                return f"https://custom/{identifier}"
            def fetch(self, identifier):
                return SourceBundle("content", "custom", identifier, self.resolve(identifier))

        register_adapter(MockAdapter())
        adapter = resolve_source("custom:test")
        assert isinstance(adapter, MockAdapter)


# ── CLI Helpers ────────────────────────────────────────────────

class TestParseFrontmatter:
    def test_valid_frontmatter(self):
        from xiaomei_brain.cli.skill import _parse_frontmatter
        content = "---\nname: my-skill\ndescription: A test skill\n---\n# Body content"
        fm, body = _parse_frontmatter(content)
        assert fm["name"] == "my-skill"
        assert fm["description"] == "A test skill"
        assert body == "# Body content"

    def test_no_frontmatter(self):
        from xiaomei_brain.cli.skill import _parse_frontmatter
        content = "# Just a markdown file"
        fm, body = _parse_frontmatter(content)
        assert fm == {}
        assert body == "# Just a markdown file"

    def test_malformed_yaml(self):
        from xiaomei_brain.cli.skill import _parse_frontmatter
        content = "---\nname: [invalid: yaml: value\n---\n# Body"
        fm, body = _parse_frontmatter(content)
        # Malformed YAML is skipped gracefully
        assert body == "# Body"


class TestDeriveName:
    def test_from_frontmatter(self):
        from xiaomei_brain.cli.skill import _derive_name
        fm = {"name": "my-skill"}
        name = _derive_name("https://example.com/SKILL.md", fm)
        assert name == "my-skill"

    def test_from_override(self):
        from xiaomei_brain.cli.skill import _derive_name
        fm = {"name": "frontmatter-name"}
        name = _derive_name("https://example.com/SKILL.md", fm, name_override="overridden")
        assert name == "overridden"

    def test_from_url_fallback(self):
        from xiaomei_brain.cli.skill import _derive_name
        name = _derive_name("https://example.com/path/to/skill-name.md", {})
        assert name == "skill-name"

    def test_from_github_fallback(self):
        from xiaomei_brain.cli.skill import _derive_name
        name = _derive_name("owner/repo/skill-dir", {})
        assert name == "skill-dir"

    def test_sanitize_name(self):
        from xiaomei_brain.cli.skill import _derive_name
        name = _derive_name("https://example.com/My Skill & Special!.md", {})
        assert name == "my-skill---special"

    def test_empty_name(self):
        from xiaomei_brain.cli.skill import _derive_name
        name = _derive_name("!!!", {})
        assert name == ""


# ── CLI Install (integration with mock network) ────────────────

class TestCmdInstall:
    def test_install_from_url(self, tmp_agent_dir, mock_requests):
        """Install a skill from a URL into a temp agent."""
        from xiaomei_brain.cli.skill import _cmd_install

        mock_resp = Mock()
        mock_resp.text = (
            "---\n"
            "name: test-skill\n"
            "description: A test skill from URL\n"
            "tags: [test, example]\n"
            "---\n"
            "# Test Skill\n\nThis is the content."
        )
        mock_resp.headers = {"content-type": "text/plain"}
        mock_resp.raise_for_status = Mock()
        mock_requests.return_value = mock_resp

        # Patch Skills dir and brain db to use tmp_agent_dir
        with patch("xiaomei_brain.cli.skill._skills_dir", return_value=os.path.join(tmp_agent_dir, "skills")):
            with patch("xiaomei_brain.cli.skill._brain_db_path", return_value=os.path.join(tmp_agent_dir, "brain.db")):
                with patch.object(
                    __import__("xiaomei_brain.skills.storage", fromlist=["SkillStorage"]).SkillStorage,
                    "_get_lance_table",
                    return_value=None,
                ):
                    with patch.object(
                        __import__("xiaomei_brain.skills.storage", fromlist=["SkillStorage"]).SkillStorage,
                        "_upsert_lance",
                        return_value=None,
                    ):
                        _cmd_install("https://example.com/SKILL.md", "testbot", None)

        # Verify file was written
        skill_path = os.path.join(tmp_agent_dir, "skills", "test-skill", "SKILL.md")
        assert os.path.exists(skill_path)
        content = open(skill_path).read()
        assert "tags: [test, example]" in content

        # Verify index
        import sqlite3
        conn = sqlite3.connect(os.path.join(tmp_agent_dir, "brain.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM skills WHERE name = ?", ("test-skill",)).fetchone()
        assert row is not None
        assert row["description"] == "A test skill from URL"
        assert row["source"] == "imported"

    def test_install_from_github(self, tmp_agent_dir, mock_requests):
        """Install a skill from GitHub shorthand."""
        from xiaomei_brain.cli.skill import _cmd_install

        mock_resp = Mock()
        mock_resp.text = (
            "---\n"
            "name: github-skill\n"
            "description: From GitHub\n"
            "---\n"
            "# GitHub Skill"
        )
        mock_resp.status_code = 200
        mock_resp.raise_for_status = Mock()
        mock_requests.return_value = mock_resp

        with patch("xiaomei_brain.cli.skill._skills_dir", return_value=os.path.join(tmp_agent_dir, "skills")):
            with patch("xiaomei_brain.cli.skill._brain_db_path", return_value=os.path.join(tmp_agent_dir, "brain.db")):
                with patch.object(
                    __import__("xiaomei_brain.skills.storage", fromlist=["SkillStorage"]).SkillStorage,
                    "_get_lance_table",
                    return_value=None,
                ):
                    with patch.object(
                        __import__("xiaomei_brain.skills.storage", fromlist=["SkillStorage"]).SkillStorage,
                        "_upsert_lance",
                        return_value=None,
                    ):
                        _cmd_install("owner/repo", "testbot", None)

        skill_path = os.path.join(tmp_agent_dir, "skills", "github-skill", "SKILL.md")
        assert os.path.exists(skill_path)

    def test_install_with_name_override(self, tmp_agent_dir, mock_requests):
        """Install with --name override."""
        from xiaomei_brain.cli.skill import _cmd_install

        mock_resp = Mock()
        mock_resp.text = "---\nname: original-name\n---\n# Content"
        mock_resp.headers = {"content-type": "text/plain"}
        mock_resp.raise_for_status = Mock()
        mock_requests.return_value = mock_resp

        with patch("xiaomei_brain.cli.skill._skills_dir", return_value=os.path.join(tmp_agent_dir, "skills")):
            with patch("xiaomei_brain.cli.skill._brain_db_path", return_value=os.path.join(tmp_agent_dir, "brain.db")):
                with patch.object(
                    __import__("xiaomei_brain.skills.storage", fromlist=["SkillStorage"]).SkillStorage,
                    "_get_lance_table",
                    return_value=None,
                ):
                    with patch.object(
                        __import__("xiaomei_brain.skills.storage", fromlist=["SkillStorage"]).SkillStorage,
                        "_upsert_lance",
                        return_value=None,
                    ):
                        _cmd_install("https://example.com/SKILL.md", "testbot", "my-custom-name")

        skill_path = os.path.join(tmp_agent_dir, "skills", "my-custom-name", "SKILL.md")
        assert os.path.exists(skill_path)

    def test_install_error_no_adapter(self, tmp_agent_dir):
        from xiaomei_brain.cli.skill import _cmd_install
        with pytest.raises(SystemExit):
            _cmd_install("not-a-valid-format", "testbot", None)

    def test_install_error_404(self, tmp_agent_dir, mock_requests):
        from xiaomei_brain.cli.skill import _cmd_install

        mock_resp = Mock()
        mock_resp.status_code = 404
        mock_requests.return_value = mock_resp

        with patch("xiaomei_brain.cli.skill._skills_dir", return_value=os.path.join(tmp_agent_dir, "skills")):
            with patch("xiaomei_brain.cli.skill._brain_db_path", return_value=os.path.join(tmp_agent_dir, "brain.db")):
                with pytest.raises(SystemExit):
                    _cmd_install("owner/nonexistent", "testbot", None)


# ── CLI List & Remove ──────────────────────────────────────────

class TestCmdList:
    def test_list_empty(self, tmp_agent_dir):
        from xiaomei_brain.cli.skill import _cmd_list
        with patch("xiaomei_brain.cli.skill._brain_db_path", return_value=os.path.join(tmp_agent_dir, "brain.db")):
            # brain.db exists but skills table is empty
            _cmd_list("testbot", None)

    def test_list_with_results(self, tmp_agent_dir):
        from xiaomei_brain.cli.skill import _cmd_list
        # Add a skill to the database
        from xiaomei_brain.skills.storage import SkillStorage
        with patch.object(SkillStorage, "_get_lance_table", return_value=None), \
             patch.object(SkillStorage, "_upsert_lance", return_value=None):
            storage = SkillStorage(db_path=os.path.join(tmp_agent_dir, "brain.db"))
            storage._upsert_skill(
                name="test-skill",
                description="A test skill",
                version="1.0.0",
                tags=["test"],
                content="# Test",
                source="imported",
            )

        with patch("xiaomei_brain.cli.skill._brain_db_path", return_value=os.path.join(tmp_agent_dir, "brain.db")):
            with patch.object(SkillStorage, "_get_lance_table", return_value=None):
                _cmd_list("testbot", None)


class TestCmdRemove:
    def test_remove_existing(self, tmp_agent_dir):
        from xiaomei_brain.cli.skill import _cmd_remove
        # Add a skill to the database
        from xiaomei_brain.skills.storage import SkillStorage
        with patch.object(SkillStorage, "_get_lance_table", return_value=None), \
             patch.object(SkillStorage, "_upsert_lance", return_value=None):
            storage = SkillStorage(db_path=os.path.join(tmp_agent_dir, "brain.db"))
            storage._upsert_skill(
                name="test-skill",
                description="A test skill",
                version="1.0.0",
                tags=["test"],
                content="# Test",
                source="imported",
            )

        # Create the directory too
        skill_dir = os.path.join(tmp_agent_dir, "skills", "test-skill")
        os.makedirs(skill_dir)

        with patch("xiaomei_brain.cli.skill._skills_dir", return_value=os.path.join(tmp_agent_dir, "skills")):
            with patch("xiaomei_brain.cli.skill._brain_db_path", return_value=os.path.join(tmp_agent_dir, "brain.db")):
                with patch.object(SkillStorage, "_get_lance_table", return_value=None):
                    _cmd_remove("test-skill", "testbot")

        # Verify directory removed
        assert not os.path.exists(skill_dir)

    def test_remove_nonexistent(self, tmp_agent_dir):
        from xiaomei_brain.cli.skill import _cmd_remove
        with patch("xiaomei_brain.cli.skill._skills_dir", return_value=os.path.join(tmp_agent_dir, "skills")):
            with patch("xiaomei_brain.cli.skill._brain_db_path", return_value=os.path.join(tmp_agent_dir, "brain.db")):
                from xiaomei_brain.skills.storage import SkillStorage
                with patch.object(SkillStorage, "_get_lance_table", return_value=None):
                    with pytest.raises(SystemExit):
                        _cmd_remove("nonexistent", "testbot")


# ── CLI Arg Parsing ───────────────────────────────────────────

class TestCmdSkillArgParse:
    def test_no_args(self):
        from xiaomei_brain.cli.skill import cmd_skill
        with pytest.raises(SystemExit):
            cmd_skill([])

    def test_unrecognized_action(self):
        from xiaomei_brain.cli.skill import cmd_skill
        with pytest.raises(SystemExit):
            cmd_skill(["unknown"])

    def test_install_requires_identifier(self):
        from xiaomei_brain.cli.skill import cmd_skill
        with pytest.raises(SystemExit):
            cmd_skill(["install"])


# ── Config ─────────────────────────────────────────────────────

class TestMirrorEnv:
    def test_mirror_from_env(self):
        os.environ["GITHUB_RAW_MIRRORS"] = "https://mirror1.example.com,https://mirror2.example.com"
        # Clear module cache to re-parse
        from xiaomei_brain.skills.sources import github as github_mod
        github_mod._MIRRORS.clear()
        mirrors = github_mod._get_mirrors()
        assert "https://mirror1.example.com" in mirrors
        assert "https://mirror2.example.com" in mirrors
        # Cleanup
        del os.environ["GITHUB_RAW_MIRRORS"]
        github_mod._MIRRORS.clear()
