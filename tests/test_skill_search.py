from __future__ import annotations

import json
from unittest.mock import Mock, patch

import requests

from xiaomei_brain.skills.search import find_external_skills


def test_find_external_skills_normalizes_sources():
    skills_response = Mock()
    skills_response.raise_for_status = Mock()
    skills_response.json.return_value = {
        "skills": [{
            "id": "owner/repo/word-guide",
            "name": "Word Guide",
            "source": "owner/repo",
            "description": "Create Word documents",
            "installs": 1200,
        }]
    }
    skillhub_payload = json.dumps({
        "skills": [{
            "namespace": "office",
            "slug": "word-layout",
            "summary": "中文文档排版",
            "version": "1.0.0",
        }]
    })
    completed = Mock(returncode=0, stdout=skillhub_payload)
    with patch("xiaomei_brain.skills.search.requests.get", return_value=skills_response), patch(
        "xiaomei_brain.skills.search.shutil.which", return_value="skillhub"
    ), patch("xiaomei_brain.skills.search.subprocess.run", return_value=completed):
        result = find_external_skills("Word 文档")

    assert result["count"] == 2
    assert result["results"][0]["learn_source"] == (
        "https://skills.sh/owner/repo/word-guide"
    )
    assert result["results"][1]["learn_source"] == (
        "skillhub install office/word-layout"
    )
    assert result["web_search_recommended"] is True


def test_find_external_skills_recommends_web_search_when_sources_fail():
    with patch(
        "xiaomei_brain.skills.search.requests.get",
        side_effect=requests.Timeout("slow"),
    ), patch("xiaomei_brain.skills.search.shutil.which", return_value=None):
        result = find_external_skills("视频制作")

    assert result["results"] == []
    assert result["sources"]["skillhub"] == "not_installed"
    assert result["web_search_recommended"] is True
    assert "web_search" in result["next_step"]


def test_find_external_skills_requires_meaningful_query():
    try:
        find_external_skills("a")
    except ValueError as exc:
        assert "2 个字符" in str(exc)
    else:
        raise AssertionError("short query should fail")
