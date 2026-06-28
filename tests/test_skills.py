"""Skills system tests — SkillStorage, SkillLoader, slash command, tools.

Avoids heavy dependencies (LanceDB, embedding model) by mocking where needed.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from xiaomei_brain.skills.loader import Skill, SkillLoader
from xiaomei_brain.skills.storage import SkillStorage

# ── Fixtures ───────────────────────────────────────────────────


@pytest.fixture
def tmp_db():
    d = tempfile.mkdtemp()
    db_path = os.path.join(d, "brain.db")
    yield db_path
    import shutil
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def storage(tmp_db):
    """SkillStorage with LanceDB/embedding mocked out."""
    with (
        patch.object(SkillStorage, '_get_lance_table', return_value=None),
        patch.object(SkillStorage, '_upsert_lance', return_value=None),
    ):
        s = SkillStorage(db_path=tmp_db)
        yield s
        s.close()


@pytest.fixture
def populated_storage(storage):
    """Storage with 3 pre-loaded skills."""
    storage.add_skill(
        name="browser-automation",
        description="Use Playwright to automate browser tasks",
        content="# Browser Automation\n\nSteps:\n1. navigate\n2. screenshot",
        tags=["browser", "automation"],
        tool_bindings=["navigate_page", "take_screenshot"],
    )
    storage.add_skill(
        name="python-testing",
        description="Write and run Python tests with pytest",
        content="# Python Testing\n\nUse pytest for testing",
        tags=["python", "testing"],
        tool_bindings=["shell"],
    )
    storage.add_skill(
        name="git-workflow",
        description="Git branching and PR workflow conventions",
        content="# Git Workflow\n\nFeature branches, PR reviews",
        tags=["git", "workflow"],
        tool_bindings=["shell"],
    )
    return storage


# ═══ SkillStorage — 初始化 ═══════════════════════════════════════


def test_init_creates_tables(tmp_db):
    """SQLite tables are created on init."""
    with (
        patch.object(SkillStorage, '_get_lance_table', return_value=None),
        patch.object(SkillStorage, '_upsert_lance', return_value=None),
    ):
        s = SkillStorage(db_path=tmp_db)
        conn = s._get_conn()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {r["name"] for r in tables}
        assert "skills" in table_names
        assert "schema_versions" in table_names
        s.close()


def test_init_sets_schema_version(tmp_db):
    with (
        patch.object(SkillStorage, '_get_lance_table', return_value=None),
        patch.object(SkillStorage, '_upsert_lance', return_value=None),
    ):
        s = SkillStorage(db_path=tmp_db)
        v = s._get_schema_version("skills")
        assert v == 1
        s.close()


# ═══ SkillStorage — CRUD ─════════════════════════════════════════


def test_add_skill(storage):
    sid = storage.add_skill(
        name="test-skill",
        description="A test skill",
        content="# Test\nContent here",
        tags=["test", "demo"],
        tool_bindings=["shell"],
    )
    assert sid > 0

    skill = storage.view_skill("test-skill")
    assert skill is not None
    assert skill["name"] == "test-skill"
    assert skill["description"] == "A test skill"
    assert skill["content"] == "# Test\nContent here"
    assert skill["tags"] == ["test", "demo"]
    assert skill["tool_bindings"] == ["shell"]
    assert skill["source"] == "generated"
    assert skill["usage_count"] == 0


def test_add_skill_duplicate_updates(storage):
    """Adding a skill with same name updates the existing record."""
    storage.add_skill("test-skill", "First desc", "First content")
    storage.add_skill("test-skill", "Updated desc", "Updated content")

    skill = storage.view_skill("test-skill")
    assert skill["description"] == "Updated desc"
    assert skill["content"] == "Updated content"
    assert storage.count() == 1


def test_remove_skill(storage):
    storage.add_skill("to-remove", "Desc", "Content")
    assert storage.count() == 1

    assert storage.remove_skill("to-remove") is True
    assert storage.count() == 0
    assert storage.view_skill("to-remove") is None


def test_remove_skill_missing(storage):
    assert storage.remove_skill("nonexistent") is False


def test_record_usage(storage):
    storage.add_skill("used-skill", "Desc", "Content")
    assert storage.view_skill("used-skill")["usage_count"] == 0

    storage.record_usage("used-skill")
    assert storage.view_skill("used-skill")["usage_count"] == 1

    storage.record_usage("used-skill")
    assert storage.view_skill("used-skill")["usage_count"] == 2


def test_list_names(storage):
    storage.add_skill("skill-a", "Desc A", "Content A")
    storage.add_skill("skill-b", "Desc B", "Content B")

    names = storage.list_names()
    assert sorted(names) == ["skill-a", "skill-b"]


def test_count(storage):
    assert storage.count() == 0
    storage.add_skill("a", "d", "c")
    storage.add_skill("b", "d", "c")
    assert storage.count() == 2


# ═══ SkillStorage — list_skills (no query, no LanceDB) ═══════════


def test_list_skills_no_query_returns_all(populated_storage):
    skills = populated_storage.list_skills(query="")
    assert len(skills) == 3
    names = {s["name"] for s in skills}
    assert names == {"browser-automation", "python-testing", "git-workflow"}


def test_list_skills_no_query_sorted_by_usage(populated_storage):
    populated_storage.record_usage("git-workflow")
    populated_storage.record_usage("git-workflow")
    populated_storage.record_usage("python-testing")

    skills = populated_storage.list_skills(query="")
    # git-workflow (2 uses) should be first
    assert skills[0]["name"] == "git-workflow"


def test_list_skills_respects_top_k(populated_storage):
    skills = populated_storage.list_skills(query="", top_k=2)
    assert len(skills) == 2


def test_list_skills_excludes_content(populated_storage):
    skills = populated_storage.list_skills(query="")
    for s in skills:
        assert "content" not in s, f"{s['name']} should not expose content"


# ═══ SkillStorage — view_skill ═══════════════════════════════════


def test_view_skill_includes_content(storage):
    storage.add_skill("s", "desc", "full content here")
    skill = storage.view_skill("s")
    assert skill is not None
    assert skill["content"] == "full content here"


def test_view_skill_missing(storage):
    assert storage.view_skill("nonexistent") is None


# ═══ SkillStorage — keyword search (LanceDB fallback) ════════════


def test_keyword_search_by_name(populated_storage):
    """When LanceDB is unavailable, falls back to keyword search."""
    results = populated_storage._keyword_search("browser", top_k=5)
    assert len(results) == 1
    assert results[0]["name"] == "browser-automation"


def test_keyword_search_by_description(populated_storage):
    results = populated_storage._keyword_search("pytest", top_k=5)
    assert len(results) == 1
    assert results[0]["name"] == "python-testing"


def test_keyword_search_by_tag(populated_storage):
    results = populated_storage._keyword_search("git", top_k=5)
    assert len(results) >= 1
    assert any(r["name"] == "git-workflow" for r in results)


def test_keyword_search_no_match(populated_storage):
    results = populated_storage._keyword_search("zzz_nonexistent", top_k=5)
    assert results == []


def test_keyword_search_case_insensitive(populated_storage):
    results = populated_storage._keyword_search("PLAYWRIGHT", top_k=5)
    assert len(results) == 1
    assert results[0]["name"] == "browser-automation"


def test_keyword_search_scores_name_higher(storage):
    """Name match scores higher than description/tag match."""
    storage.add_skill("shell-scripting", "Something about browser use", "content", tags=["test"])
    storage.add_skill("browser-tools", "General browser", "content", tags=["test"])

    results = storage._keyword_search("browser", top_k=5)
    # browser-tools matches name (=100) and description (=50), higher total
    scores = {}
    for r in results:
        scores[r["name"]] = r.get("_score", "N/A")
    assert results[0]["name"] == "browser-tools"


# ═══ SkillStorage — build_skill_index_prompt ═══════════════════


def test_build_skill_index_prompt_empty_when_no_skills(storage):
    result = storage.build_skill_index_prompt("anything")
    assert result == ""


def test_build_skill_index_prompt_with_keyword_fallback(populated_storage):
    """Uses keyword search when LanceDB is unavailable.

    Uses 'pytest' which is a substring of the python-testing description,
    ensuring keyword search can find it without needing actual embedding.
    """
    result = populated_storage.build_skill_index_prompt("pytest", top_k=3)
    assert "## Skills（技能）" in result
    assert "<available_skills>" in result
    assert "</available_skills>" in result
    assert "python-testing" in result
    assert "skill_view" in result


def test_build_skill_index_prompt_no_match_returns_empty(populated_storage):
    result = populated_storage.build_skill_index_prompt("zzz_nonexistent_xyz", top_k=3)
    assert result == ""


def test_build_skill_index_prompt_includes_tags(populated_storage):
    result = populated_storage.build_skill_index_prompt("browser", top_k=3)
    assert "[browser, automation]" in result or "browser" in result


def test_build_skill_index_prompt_top_k_respected(populated_storage):
    result = populated_storage.build_skill_index_prompt("skill", top_k=1)
    # Count skill list lines (minus header/footer)
    skill_lines = [l for l in result.split("\n") if l.strip().startswith("  - ")]
    assert len(skill_lines) <= 1


# ═══ SkillStorage — _row_to_dict ═══════════════════════════════


def test_row_to_dict_tags_parsing(storage):
    storage.add_skill("s", "desc", "content", tags=["a", "b"])
    skill = storage.view_skill("s")
    assert skill["tags"] == ["a", "b"]


def test_row_to_dict_invalid_tags_json(storage):
    """Gracefully handles non-JSON tags stored as string."""
    conn = storage._get_conn()
    conn.execute(
        "INSERT INTO skills (name, description, tags, content, source, created_at, updated_at) "
        "VALUES ('broken', 'desc', 'not-json', 'content', 'local', 0, 0)"
    )
    conn.commit()
    skill = storage.view_skill("broken")
    # Corrupted JSON tags should silently fall back to empty list
    assert skill["tags"] == []
    assert skill["tool_bindings"] == []


# ═══ SkillStorage — import_from_dir ═════════════════════════════


def test_import_creates_dir_if_missing(storage, tmp_db):
    d = os.path.join(os.path.dirname(tmp_db), "new_skills")
    assert not os.path.isdir(d)
    n = storage.import_from_dir(d)
    assert n == 0
    assert os.path.isdir(d)


def test_import_from_dir_with_skills(storage, tmp_db):
    d = os.path.join(os.path.dirname(tmp_db), "skills")
    os.makedirs(os.path.join(d, "my-browser-skill"), exist_ok=True)

    skill_md = os.path.join(d, "my-browser-skill", "SKILL.md")
    with open(skill_md, "w") as f:
        f.write("""---
name: my-browser-skill
description: Automate browser with Playwright
version: "1.2.0"
tags:
  - browser
  - web
requires_tools:
  - navigate_page
  - take_screenshot
---
# My Browser Skill

## Steps
1. Open browser
2. Do stuff
""")

    n = storage.import_from_dir(d)
    assert n == 1

    skill = storage.view_skill("my-browser-skill")
    assert skill is not None
    assert skill["description"] == "Automate browser with Playwright"
    assert skill["version"] == "1.2.0"
    assert skill["tags"] == ["browser", "web"]
    assert skill["tool_bindings"] == ["navigate_page", "take_screenshot"]
    assert "## Steps" in skill["content"]


def test_import_from_dir_tags_as_comma_string(storage, tmp_db):
    """Tags as comma-separated string in frontmatter should be split."""
    d = os.path.join(os.path.dirname(tmp_db), "skills2")
    os.makedirs(os.path.join(d, "comma-skill"), exist_ok=True)
    with open(os.path.join(d, "comma-skill", "SKILL.md"), "w") as f:
        f.write("""---
name: comma-skill
description: Has comma tags
tags: a, b, c
---
# Body
""")
    n = storage.import_from_dir(d)
    assert n == 1
    skill = storage.view_skill("comma-skill")
    assert skill["tags"] == ["a", "b", "c"]


def test_import_from_dir_no_frontmatter(storage, tmp_db):
    """Skill file without YAML frontmatter uses directory name."""
    d = os.path.join(os.path.dirname(tmp_db), "skills3")
    os.makedirs(os.path.join(d, "no-fm-skill"), exist_ok=True)
    with open(os.path.join(d, "no-fm-skill", "SKILL.md"), "w") as f:
        f.write("Just raw markdown content")
    n = storage.import_from_dir(d)
    assert n == 1
    skill = storage.view_skill("no-fm-skill")
    assert skill["description"] == ""
    assert skill["content"] == "Just raw markdown content"


# ═══ SkillLoader — 委托 ══════════════════════════════════════════


class TestSkillLoader:
    def test_scan_creates_dir(self, tmp_db):
        skills_dir = os.path.join(os.path.dirname(tmp_db), "skills_dir")
        loader = SkillLoader(skills_dir=skills_dir, db_path=tmp_db)
        loader.scan()
        assert os.path.isdir(skills_dir)

    def test_scan_imports_skills(self, tmp_db):
        skills_dir = os.path.join(os.path.dirname(tmp_db), "skills4")
        os.makedirs(os.path.join(skills_dir, "test-skill"), exist_ok=True)
        with open(os.path.join(skills_dir, "test-skill", "SKILL.md"), "w") as f:
            f.write("""---
name: test-skill
description: Test skill description
---
# Test Skill Content
""")
        loader = SkillLoader(skills_dir=skills_dir, db_path=tmp_db)
        loader.scan()

        names = loader.list_names()
        assert "test-skill" in names

    def test_list_skills_delegates(self, tmp_db):
        loader = SkillLoader(skills_dir="/tmp/x", db_path=tmp_db)
        storage = loader._get_storage()
        storage.add_skill("s", "desc", "content")
        results = loader.list_skills()
        assert len(results) == 1
        assert results[0]["name"] == "s"

    def test_view_skill_delegates(self, tmp_db):
        loader = SkillLoader(skills_dir="/tmp/x", db_path=tmp_db)
        storage = loader._get_storage()
        storage.add_skill("v", "d", "c")
        s = loader.view_skill("v")
        assert s["content"] == "c"

    def test_view_skill_missing(self, tmp_db):
        loader = SkillLoader(skills_dir="/tmp/x", db_path=tmp_db)
        assert loader.view_skill("no") is None

    def test_add_remove_skill(self, tmp_db):
        loader = SkillLoader(skills_dir="/tmp/x", db_path=tmp_db)
        loader.add_skill("r", "d", "c")
        assert loader.list_names() == ["r"]
        assert loader.remove_skill("r") is True
        assert loader.list_names() == []

    def test_record_usage(self, tmp_db):
        loader = SkillLoader(skills_dir="/tmp/x", db_path=tmp_db)
        loader.add_skill("u", "d", "c")
        loader.record_usage("u")
        s = loader.view_skill("u")
        assert s["usage_count"] == 1

    def test_build_skill_index_prompt_delegates(self, tmp_db):
        loader = SkillLoader(skills_dir="/tmp/x", db_path=tmp_db)
        storage = loader._get_storage()
        storage.add_skill("idx-test", "Index test skill", "Content", tags=["test"])
        result = loader.build_skill_index_prompt("index test")
        assert "idx-test" in result

    def test_build_skill_index_prompt_empty(self, tmp_db):
        loader = SkillLoader(skills_dir="/tmp/x", db_path=tmp_db)
        assert loader.build_skill_index_prompt("anything") == ""


# ═══ Skill dataclass ═══════════════════════════════════════════


def test_skill_to_embedding_text():
    s = Skill(name="test", description="A test skill", tags=["a", "b"])
    assert s.to_embedding_text() == "test: A test skill a b"

    s2 = Skill(name="no-tags", description="Desc")
    assert s2.to_embedding_text() == "no-tags: Desc "


def test_skill_to_dict():
    s = Skill(name="test", description="desc", tags=["x"])
    d = s.to_dict()
    assert d["name"] == "test"
    assert d["description"] == "desc"
    assert d["tags"] == ["x"]
    assert "content" not in d  # Tier 0 metadata excludes content


# ═══ Slash command 解析 ════════════════════════════════════════


class TestSlashCommandParsing:
    """Test _handle_slash_command logic in isolation."""

    def test_parses_slash_with_args(self):
        content = "/myskill 帮我查一下资料"
        parts = content.strip().split(None, 1)
        cmd = parts[0][1:]
        user_input = parts[1] if len(parts) > 1 else ""
        assert cmd == "myskill"
        assert user_input == "帮我查一下资料"

    def test_parses_slash_no_args(self):
        content = "/myskill"
        parts = content.strip().split(None, 1)
        cmd = parts[0][1:]
        user_input = parts[1] if len(parts) > 1 else ""
        assert cmd == "myskill"
        assert user_input == ""

    def test_parses_slash_trailing_spaces(self):
        content = "/myskill   "
        parts = content.strip().split(None, 1)
        cmd = parts[0][1:]
        user_input = parts[1] if len(parts) > 1 else ""
        assert cmd == "myskill"
        assert user_input == ""

    def test_parses_slash_with_leading_spaces(self):
        content = "  /skill arg"
        parts = content.strip().split(None, 1)
        cmd = parts[0][1:]
        user_input = parts[1] if len(parts) > 1 else ""
        assert cmd == "skill"
        assert user_input == "arg"

    def test_ignores_non_slash(self):
        content = "hello world"
        assert not content.strip().startswith("/")

    def test_build_injection_message(self):
        """Verify the injected message format."""
        cmd = "browser-automation"
        skill_content = "# Browser\nSteps here"
        user_input = "打开百度"

        result = (
            f'[IMPORTANT: 用户激活了技能 "{cmd}"，请严格按其指示执行。]\n\n'
            f"{skill_content}\n\n"
            f"{user_input}"
        )
        assert "IMPORTANT" in result
        assert cmd in result
        assert skill_content in result
        assert user_input in result

    def test_build_injection_message_no_input(self):
        cmd = "test-skill"
        skill_content = "Content"
        user_input = ""

        result = (
            f'[IMPORTANT: 用户激活了技能 "{cmd}"，请严格按其指示执行。]\n\n'
            f"{skill_content}\n\n"
            f"{user_input or '请按此技能的要求执行。'}"
        )
        assert "IMPORTANT" in result
        assert "请按此技能的要求执行" in result


# ═══ Skill tools (skills_list, skill_view) ═════════════════════


class TestSkillTools:
    """Test the tool functions directly (not via Tool wrapper)."""

    def _make_agent(self, storage):
        """Mock agent with _skill_loader."""
        loader = MagicMock()
        loader.list_skills = storage.list_skills
        loader.view_skill = storage.view_skill
        loader.list_names = storage.list_names
        loader.record_usage = storage.record_usage
        agent = MagicMock()
        agent._skill_loader = loader
        return agent

    def test_skills_list_empty(self, storage):
        from xiaomei_brain.skills.tools import create_skill_tools
        agent = self._make_agent(storage)
        tools = create_skill_tools(agent)
        skills_list_fn = next(t.func for t in tools if t.name == "skills_list")
        result = skills_list_fn()
        assert "没有任何可用技能" in result

    def test_skills_list_with_results(self, populated_storage):
        from xiaomei_brain.skills.tools import create_skill_tools
        agent = self._make_agent(populated_storage)
        tools = create_skill_tools(agent)
        skills_list_fn = next(t.func for t in tools if t.name == "skills_list")
        result = skills_list_fn()
        assert "browser-automation" in result
        assert "python-testing" in result
        assert "git-workflow" in result

    def test_skills_list_with_query(self, populated_storage):
        from xiaomei_brain.skills.tools import create_skill_tools
        agent = self._make_agent(populated_storage)
        tools = create_skill_tools(agent)
        skills_list_fn = next(t.func for t in tools if t.name == "skills_list")
        result = skills_list_fn(query="browser")
        assert "browser-automation" in result
        assert "语义搜索" in result

    def test_skill_view_not_found(self, storage):
        from xiaomei_brain.skills.tools import create_skill_tools
        agent = self._make_agent(storage)
        tools = create_skill_tools(agent)
        skill_view_fn = next(t.func for t in tools if t.name == "skill_view")
        result = skill_view_fn(name="nonexistent")
        assert "未找到技能" in result

    def test_skill_view_found(self, populated_storage):
        from xiaomei_brain.skills.tools import create_skill_tools
        agent = self._make_agent(populated_storage)
        tools = create_skill_tools(agent)
        skill_view_fn = next(t.func for t in tools if t.name == "skill_view")
        result = skill_view_fn(name="browser-automation")
        assert "browser-automation" in result
        assert "Playwright" in result
        assert "navigate" in result

    def test_skill_view_records_usage(self, populated_storage):
        from xiaomei_brain.skills.tools import create_skill_tools
        agent = self._make_agent(populated_storage)
        tools = create_skill_tools(agent)
        skill_view_fn = next(t.func for t in tools if t.name == "skill_view")

        assert populated_storage.view_skill("browser-automation")["usage_count"] == 0
        skill_view_fn(name="browser-automation")
        assert populated_storage.view_skill("browser-automation")["usage_count"] == 1

    def test_create_skill_tools_returns_two_tools(self, storage):
        from xiaomei_brain.skills.tools import create_skill_tools
        agent = self._make_agent(storage)
        tools = create_skill_tools(agent)
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"skills_list", "skill_view"}

    def test_skills_list_no_loader(self):
        """When agent has no _skill_loader, returns hint message."""
        from xiaomei_brain.skills.tools import create_skill_tools
        agent = MagicMock()
        agent._skill_loader = None
        tools = create_skill_tools(agent)
        skills_list_fn = next(t.func for t in tools if t.name == "skills_list")
        result = skills_list_fn()
        assert "未初始化" in result

    def test_skill_view_no_loader(self):
        from xiaomei_brain.skills.tools import create_skill_tools
        agent = MagicMock()
        agent._skill_loader = None
        tools = create_skill_tools(agent)
        skill_view_fn = next(t.func for t in tools if t.name == "skill_view")
        result = skill_view_fn(name="x")
        assert "未初始化" in result


# ═══ Render function (_render_skills_index) ════════════════════


class TestRenderSkillsIndex:
    def test_renders_when_present(self):
        from xiaomei_brain.consciousness.workspace.render_consciousness_v3 import _render_skills_index

        si = MagicMock()
        si.memory.skill_index = (
            "## Skills（技能）\n"
            "<available_skills>\n"
            "  - test-skill: A test skill\n"
            "</available_skills>\n"
            "使用 skill_view(name) 加载技能完整内容。"
        )
        result = _render_skills_index(si)
        assert len(result) == 1
        assert "## Skills（技能）" in result[0]
        assert "test-skill" in result[0]

    def test_returns_empty_when_empty_string(self):
        from xiaomei_brain.consciousness.workspace.render_consciousness_v3 import _render_skills_index

        si = MagicMock()
        si.memory.skill_index = ""
        result = _render_skills_index(si)
        assert result == []

    def test_returns_empty_when_none(self):
        from xiaomei_brain.consciousness.workspace.render_consciousness_v3 import _render_skills_index

        si = MagicMock()
        si.memory.skill_index = None
        result = _render_skills_index(si)
        assert result == []

    def test_returns_empty_when_missing_attr(self):
        from xiaomei_brain.consciousness.workspace.render_consciousness_v3 import _render_skills_index

        si = MagicMock()
        del si.memory.skill_index  # Remove attr
        result = _render_skills_index(si)
        assert result == []


# ═══ Inject consciousness — assembly mode coverage ═════════════


class TestAssemblyModes:
    """Verify _render_skills_index is included in the correct modes."""

    def _get_mode_renderers(self):
        """Return a dict of mode → render functions list."""
        from xiaomei_brain.consciousness.workspace import inject_consciousness_v3 as v3

        # Extract the functions used in each assembly
        modes = {}
        for mode_name in ["flow", "daily", "task", "reflect", "proactive", "internal", "dream", "learn"]:
            assemble = getattr(v3, f"_assemble_{mode_name}", None)
            if assemble is None:
                continue
            # Check source code for _render_skills_index
            import inspect
            source = inspect.getsource(assemble)
            has_skills = "_render_skills_index" in source
            modes[mode_name] = has_skills
        return modes

    def test_skills_index_in_flow_daily_task(self):
        modes = self._get_mode_renderers()
        assert modes.get("flow"), "flow should include skills index"
        assert modes.get("daily"), "daily should include skills index"
        assert modes.get("task"), "task should include skills index"

    def test_skills_index_not_in_other_modes(self):
        """reflect/proactive/internal/dream/learn — by design do NOT render skills."""
        modes = self._get_mode_renderers()
        for mode in ["reflect", "proactive", "internal", "dream", "learn"]:
            assert not modes.get(mode, False), f"{mode} should NOT include skills index"


# ═══ SQLiteStore base — shared DB ═══════════════════════════════


def test_sqlite_store_shared_connection(tmp_db):
    """Two SkillStorage instances on same db share schema_versions table."""
    with (
        patch.object(SkillStorage, '_get_lance_table', return_value=None),
        patch.object(SkillStorage, '_upsert_lance', return_value=None),
    ):
        s1 = SkillStorage(db_path=tmp_db)
        s2 = SkillStorage(db_path=tmp_db)

        assert s1._get_schema_version("skills") == 1
        assert s2._get_schema_version("skills") == 1

        s1.close()
        s2.close()


# ═══ Run ════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
