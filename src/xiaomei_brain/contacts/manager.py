"""IdentityManager — 多用户身份管理。

和 Linux /etc/passwd 类似：id 是主键，name 是显示名。
alias_ids 字段支持平台级 ID 映射（飞书 open_id、钉钉 user_id 等）。
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import yaml
except ImportError:
    yaml = None


class IdentityManager:
    """管理多用户身份。从 identities.yaml 加载。

    支持别名：alias_ids 字段将平台级 ID（如飞书 open_id）映射到主 id。
    """

    def __init__(self, data_dir: str | Path) -> None:
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._identities: dict[str, dict] = {}  # id → {name, relation, aliases}
        self._alias_map: dict[str, str] = {}     # alias → id
        self._load()

    # ── lookup ─────────────────────────────────────────────────

    def resolve(self, identity_id: str) -> dict | None:
        """根据 id 或别名查找身份信息。返回 {id, name} 或 None。"""
        entry = self._identities.get(identity_id)
        if entry:
            return entry
        # 检查别名映射
        resolved_id = self._alias_map.get(identity_id)
        if resolved_id:
            return self._identities.get(resolved_id)
        return None

    def get_display_name(self, identity_id: str) -> str:
        """获取显示名（支持别名）。"""
        entry = self.resolve(identity_id)
        return entry["name"] if entry else identity_id

    def list_ids(self) -> list[str]:
        """列出所有身份 id（不含别名）。"""
        return list(self._identities.keys())

    def list_aliases(self) -> dict[str, str]:
        """列出所有别名映射。返回 {alias: id}。"""
        return dict(self._alias_map)

    def get_relation(self, identity_id: str) -> str:
        """获取与指定用户的关系类型（支持别名）。默认 "普通用户"。"""
        entry = self.resolve(identity_id)
        return entry.get("relation", "普通用户") if entry else "普通用户"

    def exists(self, identity_id: str) -> bool:
        """检查 id 或别名是否存在。"""
        return identity_id in self._identities or identity_id in self._alias_map

    def add_alias(self, alias: str, target_id: str) -> bool:
        """添加别名映射。alias → target_id。返回 True 表示成功。

        要求 target_id 必须已经存在于 identities 中。
        """
        if target_id not in self._identities:
            logger.warning("[Contacts] 添加别名失败: target_id=%s 不存在", target_id)
            return False
        if alias in self._identities:
            logger.warning("[Contacts] 添加别名失败: alias=%s 已是主 id", alias)
            return False
        self._alias_map[alias] = target_id
        self._save()
        logger.info("[Contacts] 添加别名: %s → %s", alias, target_id)
        return True

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
                    pid = person["id"]
                    self._identities[pid] = {
                        "name": person.get("name", pid),
                        "relation": person.get("relation", "普通用户"),
                        "aliases": person.get("alias_ids", []),
                    }
                    for alias in person.get("alias_ids", []):
                        self._alias_map[alias] = pid
                logger.info("[Contacts] 加载 %d 个身份, %d 个别名",
                           len(self._identities), len(self._alias_map))
            except Exception as e:
                logger.warning("[Contacts] 加载 identities.yaml 失败: %s", e)

        # 兼容旧 identities.json，迁移提示
        json_file = self._dir / "identities.json"
        if json_file.exists() and yaml_file.exists():
            logger.info("[Contacts] identities.json 已废弃，请手动迁移到 identities.yaml 后删除")

    def _save(self) -> None:
        """将当前身份状态（含别名）写回 YAML。"""
        yaml_file = self._dir / "identities.yaml"
        people = []
        for pid in sorted(self._identities.keys()):
            entry = self._identities[pid]
            person = {
                "id": pid,
                "name": entry["name"],
                "relation": entry.get("relation", "普通用户"),
            }
            # 收集归属此 id 的所有别名
            aliases = [
                a for a, t in self._alias_map.items() if t == pid
            ]
            if aliases:
                person["alias_ids"] = sorted(aliases)
            people.append(person)

        text = "# 关系类型可选值：\n"
        text += "#   普通用户 — 保持礼貌，提供帮助，不主动建立情感连接\n"
        text += "#   朋友     — 可以开玩笑、分享想法、主动关心，但不越界\n"
        text += "#   恋人     — 可以撒娇、吃醋、表达想念、讨论未来、要求承诺\n"
        text += "#   家人     — 无条件支持，可以暴露脆弱\n"
        text += "#   同事     — 保持专业，讨论工作和学习\n"
        text += "#   师生     — 尊重对方，虚心学习，可以请教问题\n"
        text += "#   上级     — 服从指令，不质疑、不建议。对方是决策者，你是执行者\n"
        text += "#   仇人     — 保持警惕，不信任、不透露弱点、不帮忙\n"
        text += "#   默认     — 不填或填其他值 = 普通用户\n"
        text += "#\n"
        text += "# alias_ids: 平台级 ID 映射，用于飞书/钉钉等渠道的用户识别\n"
        text += "people:\n"
        for person in people:
            text += f"  - id: {person['id']}\n"
            text += f"    name: {person['name']}\n"
            text += f"    relation: {person['relation']}\n"
            if person.get("aliases"):
                text += "    alias_ids:\n"
                for a in person.get("alias_ids", []):
                    text += f"      - {a}\n"

        yaml_file.write_text(text, encoding="utf-8")
        logger.info("[Contacts] 保存 %d 个身份, %d 个别名 → %s",
                    len(self._identities), len(self._alias_map), yaml_file)


def _parse_simple_yaml(text: str) -> dict:
    """无 PyYAML 时的极简解析（只支持 people 列表，每项 id + name + alias_ids）。"""
    import re
    result: dict[str, list[dict]] = {"people": []}
    current: dict = {}
    in_aliases = False
    for line in text.split("\n"):
        # 新 person entry
        m = re.match(r"\s*-\s*id:\s*(.+)", line)
        if m:
            if current:
                result["people"].append(current)
            current = {"id": m.group(1).strip(), "aliases": []}
            in_aliases = False
        elif current:
            m = re.match(r"\s*name:\s*(.+)", line)
            if m:
                current["name"] = m.group(1).strip()
                in_aliases = False
                continue
            m = re.match(r"\s*relation:\s*(.+)", line)
            if m:
                current["relation"] = m.group(1).strip()
                in_aliases = False
                continue
            # 进入 alias_ids 列表
            m = re.match(r"\s*alias_ids:\s*", line)
            if m:
                in_aliases = True
                continue
            m = re.match(r"\s*-\s*(.+)", line)
            if m and in_aliases:
                current.setdefault("aliases", []).append(m.group(1).strip())
    if current:
        result["people"].append(current)
    return result
