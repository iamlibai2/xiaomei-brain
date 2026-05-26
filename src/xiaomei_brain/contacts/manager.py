"""IdentityManager — 多用户身份管理。

和 Linux /etc/passwd 类似：id 是主键，name 是显示名。
别名/绰号/称呼不是配置，而是 agent 的记忆。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    import yaml
except ImportError:
    yaml = None


class IdentityManager:
    """管理多用户身份。从 identities.yaml 加载。"""

    def __init__(self, data_dir: str | Path) -> None:
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._identities: dict[str, dict] = {}  # id → {name, ...}
        self._load()

    # ── lookup ─────────────────────────────────────────────────

    def resolve(self, identity_id: str) -> dict | None:
        """根据 id 查找身份信息。返回 {id, name} 或 None。"""
        return self._identities.get(identity_id)

    def get_display_name(self, identity_id: str) -> str:
        """获取显示名。"""
        entry = self._identities.get(identity_id)
        return entry["name"] if entry else identity_id

    def list_ids(self) -> list[str]:
        """列出所有身份 id。"""
        return list(self._identities.keys())

    def exists(self, identity_id: str) -> bool:
        """检查 id 是否存在。"""
        return identity_id in self._identities

    # ── preferred names（从记忆加载） ──────────────────────────

    def load_preferred_names(self, user_id: str, longterm_memory: Any = None) -> list[str]:
        """从长期记忆中加载该用户的所有称呼。

        一次向量召回，把 agent 记住的别名/绰号全拉出来。
        存入 SelfImage，后面每次对话都能看到。
        """
        if longterm_memory is None:
            return []

        try:
            results = longterm_memory.recall(
                query=f"{user_id} 称呼 名字 叫我",
                user_id=user_id,
                top_k=5,
            )
            names = []
            for m in results:
                content = m.get("content", "")
                # 提取称呼模式：对方让我叫他XX / 可以叫我XX / 他叫XX
                names.append(content)
            return names
        except Exception as e:
            logger.warning("[Contacts] 加载称呼记忆失败: %s", e)
            return []

    # ── persistence ────────────────────────────────────────────

    def _load(self) -> None:
        yaml_file = self._dir / "identities.yaml"
        if yaml_file.exists():
            try:
                if yaml is not None:
                    data = yaml.safe_load(yaml_file.read_text())
                else:
                    # 无 PyYAML 时尝试基本解析
                    data = _parse_simple_yaml(yaml_file.read_text())
                for person in data.get("people", []):
                    self._identities[person["id"]] = {
                        "name": person.get("name", person["id"]),
                    }
                logger.info("[Contacts] 加载 %d 个身份", len(self._identities))
            except Exception as e:
                logger.warning("[Contacts] 加载 identities.yaml 失败: %s", e)

        # 兼容旧 identities.json，迁移提示
        json_file = self._dir / "identities.json"
        if json_file.exists() and yaml_file.exists():
            logger.info("[Contacts] identities.json 已废弃，请手动迁移到 identities.yaml 后删除")


def _parse_simple_yaml(text: str) -> dict:
    """无 PyYAML 时的极简解析（只支持 people 列表，每项 id + name）。"""
    import re
    result: dict[str, list[dict]] = {"people": []}
    current: dict = {}
    for line in text.split("\n"):
        m = re.match(r"\s*-\s*id:\s*(.+)", line)
        if m:
            if current:
                result["people"].append(current)
            current = {"id": m.group(1).strip()}
        else:
            m = re.match(r"\s*name:\s*(.+)", line)
            if m and current:
                current["name"] = m.group(1).strip()
    if current:
        result["people"].append(current)
    return result
