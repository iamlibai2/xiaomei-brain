from __future__ import annotations

from xiaomei_brain.agent.agent_manager import _discover_user_skill_directories


def test_discovers_user_shared_skills_independent_of_working_directory(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    shared = home / ".agents" / "skills"
    shared.mkdir(parents=True)

    source_tree = tmp_path / "source"
    project_skills = source_tree / ".agents" / "skills"
    project_skills.mkdir(parents=True)
    monkeypatch.chdir(source_tree)

    assert _discover_user_skill_directories(str(home)) == [str(shared)]
    assert str(project_skills) not in _discover_user_skill_directories(str(home))


def test_ignores_missing_user_shared_skills(tmp_path):
    assert _discover_user_skill_directories(str(tmp_path / "home")) == []
