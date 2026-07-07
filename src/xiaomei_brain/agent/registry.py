"""AgentRegistry — 多 Agent 发现 + CRUD + config merge。

职责：
- 扫描 ~/.xiaomei-brain/*/ 发现 agent（含 backward compat 迁移）
- 创建/删除/克隆 agent 目录
- 内存注册/注销
- agent + global config.json 浅合并

不负责：
- LLM 初始化 / TTS / MCP / tools（由 AgentManager 负责）
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Any

from xiaomei_brain.agent.instance import AgentConfig, AgentInstance, _extract_name_from_identity

logger = logging.getLogger(__name__)


# ── AgentRegistry ─────────────────────────────────────────────

class AgentRegistry:
    """多 Agent 管理：发现、CRUD、config merge。

    使用方式:
        registry = AgentRegistry()
        agent = registry.discover("xiaomei")       # 单 agent 查找
        agents = registry.list_all()               # 全量扫描
        merged = registry.load_merged_config("xiaomei")
    """

    def __init__(self, base_dir: str | None = None):
        self.base_dir = base_dir or os.path.expanduser("~/.xiaomei-brain")
        self._agents: dict[str, AgentInstance] = {}
        self._scanned = False  # 是否已全量扫描过

    # ── Path utilities ──────────────────────────────────────────

    def _config_path(self) -> str:
        """全局 config.json 路径。"""
        return os.path.join(self.base_dir, "config.json")

    def agent_dir(self, agent_id: str) -> str:
        return os.path.join(self.base_dir, agent_id)

    # ── Config merge ────────────────────────────────────────────

    def load_merged_config(self, agent_id: str) -> dict:
        """浅合并 agent config.json 与全局 config.json。

        agent 的顶层 key 覆盖全局同名 key。
        """
        # 读全局 config
        global_data = {}
        global_path = self._config_path()
        if os.path.exists(global_path):
            try:
                with open(global_path, "r", encoding="utf-8") as f:
                    global_data = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        # 读 agent config
        agent_config_path = os.path.join(self.agent_dir(agent_id), "config.json")
        agent_data = {}
        if os.path.exists(agent_config_path):
            try:
                with open(agent_config_path, "r", encoding="utf-8") as f:
                    agent_data = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        # 浅合并
        merged = dict(global_data)
        for key, value in agent_data.items():
            merged[key] = value
        return merged

    def _read_global_config(self) -> dict:
        """读全局 config.json 并返回原始 dict。"""
        global_path = self._config_path()
        if os.path.exists(global_path):
            try:
                with open(global_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    # ── Agent Discovery ─────────────────────────────────────────

    def discover(self, agent_id: str) -> AgentInstance | None:
        """单 agent 查找（不扫描全量）。

        检查 {base_dir}/{agent_id}/ 下是否有 brain.yaml 或 identity.md。
        O(1)，用于 run <agent_id> 启动。
        """
        # 先查内存缓存
        if agent_id in self._agents:
            return self._agents[agent_id]

        return self._discover_one(agent_id)

    def _discover_one(self, agent_id: str) -> AgentInstance | None:
        """从目录加载单个 agent。"""
        agent_dir = self.agent_dir(agent_id)
        if not os.path.isdir(agent_dir):
            return None

        has_brain = os.path.exists(os.path.join(agent_dir, "brain.yaml"))
        has_identity = os.path.exists(os.path.join(agent_dir, "identity.md"))
        has_ci = os.path.exists(os.path.join(agent_dir, "consciousness", "identity.md"))
        if not has_brain and not has_identity and not has_ci:
            return None

        instance = self._load_agent_from_dir(agent_id, agent_dir, has_ci)
        if instance:
            self._agents[agent_id] = instance
        return instance

    def list_all(self) -> list[AgentInstance]:
        """全量扫描并返回所有 agent。

        用于 agent list、REST API、channel bindings 等。
        首次调用触发扫描；后续返回缓存。
        """
        if not self._scanned:
            self._scan_all()
        return [a for a in self._agents.values() if a.enabled]

    def _scan_all(self) -> None:
        """全量扫描 base_dir。"""
        # 向后兼容迁移
        if self._maybe_migrate():
            # 迁移后重新读
            pass

        if not os.path.isdir(self.base_dir):
            self._ensure_default_agent()
            self._scanned = True
            return

        found_any = False
        try:
            for entry in os.listdir(self.base_dir):
                agent_dir = os.path.join(self.base_dir, entry)
                if not os.path.isdir(agent_dir):
                    continue
                if entry in self._agents:
                    found_any = True
                    continue

                has_brain = os.path.exists(os.path.join(agent_dir, "brain.yaml"))
                has_identity = os.path.exists(os.path.join(agent_dir, "identity.md"))
                has_ci = os.path.exists(os.path.join(agent_dir, "consciousness", "identity.md"))
                if not has_brain and not has_identity and not has_ci:
                    continue

                instance = self._load_agent_from_dir(entry, agent_dir, has_ci)
                if instance:
                    self._agents[entry] = instance
                    found_any = True
        except OSError:
            pass

        self._scanned = True

        if not found_any:
            self._ensure_default_agent()

    def _load_agent_from_dir(self, agent_id: str, agent_dir: str, has_ci: bool) -> AgentInstance | None:
        """从目录加载单个 agent 的配置和身份。"""
        # 读 agent config.json
        agent_config = {}
        agent_config_path = os.path.join(agent_dir, "config.json")
        if os.path.exists(agent_config_path):
            try:
                with open(agent_config_path, "r", encoding="utf-8") as f:
                    agent_config = json.load(f)
            except Exception:
                logger.warning("Failed to read agent config: %s", agent_config_path, exc_info=True)

        # 读全局 defaults
        global_data = self._read_global_config()
        defaults = global_data.get("agents", {}).get("defaults", {})
        default_model = defaults.get("model", {})

        # 解析 model（agent config > global defaults）
        model_cfg = agent_config.get("model", {})
        if isinstance(model_cfg, str):
            model_primary = model_cfg
            vision_model = ""
        elif isinstance(model_cfg, dict):
            model_primary = model_cfg.get("primary", default_model.get("primary", ""))
            vision_model = model_cfg.get("vision", default_model.get("vision", ""))
        else:
            model_primary = default_model.get("primary", "")
            vision_model = default_model.get("vision", "")

        provider, model = "", ""
        if "/" in model_primary:
            provider, model = model_primary.split("/", 1)

        # 确定 identity.md 路径
        identity_path = os.path.join(agent_dir, "identity.md")
        if not os.path.exists(identity_path) and has_ci:
            identity_path = os.path.join(agent_dir, "consciousness", "identity.md")

        # 名字：agent config > identity.md 提取 > agent_id
        name = agent_config.get("name", "")
        if not name or name == agent_id:
            extracted = _extract_name_from_identity(identity_path)
            if extracted:
                name = extracted
        if not name:
            name = agent_id

        return AgentInstance(
            id=agent_id,
            name=name,
            description=agent_config.get("description", ""),
            avatar=agent_config.get("avatar", ""),
            enabled=agent_config.get("enabled", True),
            identity_path=identity_path,
            provider=provider,
            model=model,
            vision_model=vision_model,
            api_key=agent_config.get("api_key", ""),
            base_url=agent_config.get("base_url", ""),
        )

    # ── Backward Compat Migration ───────────────────────────────

    def _maybe_migrate(self) -> bool:
        """检测旧 agents.list 并迁移为 per-agent config.json。

        Returns:
            True 如果执行了迁移。
        """
        global_path = self._config_path()
        if not os.path.exists(global_path):
            return False

        try:
            with open(global_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            logger.warning("Failed to read global config for migration check", exc_info=True)
            return False

        agents_list = data.get("agents", {}).get("list", [])
        if not agents_list:
            return False

        # 检查是否已有 agent 目录（已迁移过）
        for entry in agents_list:
            agent_id = entry.get("id", "")
            if not agent_id:
                continue
            agent_dir = self.agent_dir(agent_id)
            if os.path.exists(os.path.join(agent_dir, "brain.yaml")):
                continue
            if os.path.exists(os.path.join(agent_dir, "identity.md")):
                continue
            if os.path.exists(os.path.join(agent_dir, "consciousness", "identity.md")):
                continue
            # 这个 agent 还没有目录，说明需要迁移
            break
        else:
            # 所有 agent 都有目录了，直接删除 agents.list
            del data["agents"]["list"]
            if not data["agents"]:
                del data["agents"]
            with open(global_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True

        # 执行迁移
        logger.info("[AgentRegistry] 检测到旧 agents.list，自动迁移...")
        for entry in agents_list:
            agent_id = entry.get("id", "")
            if not agent_id:
                continue
            agent_dir = self.agent_dir(agent_id)
            os.makedirs(agent_dir, exist_ok=True)

            # 写 agent config.json
            agent_config = {
                "name": entry.get("name", agent_id),
                "description": entry.get("description", ""),
                "enabled": entry.get("enabled", True),
            }
            if entry.get("model"):
                agent_config["model"] = entry["model"]
            agent_config_path = os.path.join(agent_dir, "config.json")
            with open(agent_config_path, "w", encoding="utf-8") as f:
                json.dump(agent_config, f, indent=2, ensure_ascii=False)

            # identity.md（如果有 identity content）
            if entry.get("identity"):
                identity_path = os.path.join(agent_dir, "identity.md")
                if not os.path.exists(identity_path):
                    with open(identity_path, "w", encoding="utf-8") as f:
                        f.write(entry["identity"])

            logger.info("[AgentRegistry] 已迁移: %s", agent_id)

        # 删除 agents.list
        del data["agents"]["list"]
        if not data["agents"]:
            del data["agents"]
        with open(global_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info("[AgentRegistry] 迁移完成，已删除 agents.list")
        return True

    # ── Default Agent ──────────────────────────────────────────

    def _ensure_default_agent(self) -> None:
        """零配置 fallback：创建 default agent。"""
        if "default" in self._agents:
            return

        agent_dir = self.agent_dir("default")
        os.makedirs(agent_dir, exist_ok=True)
        identity_path = os.path.join(agent_dir, "identity.md")

        instance = AgentInstance(
            id="default",
            name="默认助手",
            description="默认AI助手",
            enabled=True,
            identity_path=identity_path,
        )
        self._agents["default"] = instance

    # ── CRUD ───────────────────────────────────────────────────

    def get(self, agent_id: str) -> AgentInstance | None:
        """按 ID 获取 agent（从内存缓存）。"""
        return self._agents.get(agent_id)

    def register(self, config: AgentConfig) -> AgentInstance:
        """注册 agent 到内存并创建目录结构。"""
        agent_id = config.id
        if agent_id in self._agents:
            raise ValueError(f"Agent '{agent_id}' already registered")

        agent_dir = self.agent_dir(agent_id)
        os.makedirs(agent_dir, exist_ok=True)

        identity_path = os.path.join(agent_dir, "identity.md")
        if config.identity_content and not os.path.exists(identity_path):
            with open(identity_path, "w", encoding="utf-8") as f:
                f.write(config.identity_content)

        instance = AgentInstance(
            id=agent_id,
            name=config.name,
            description=config.description,
            avatar=config.avatar,
            enabled=config.enabled,
            identity_path=identity_path,
            provider=config.provider,
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self._agents[agent_id] = instance
        return instance

    def unregister(self, agent_id: str) -> bool:
        """从内存中移除 agent。"""
        if agent_id not in self._agents:
            return False
        del self._agents[agent_id]
        return True

    def create_agent(
        self,
        name: str,
        copy_from: str = "",
        identity_content: str = "",
        brain_yaml_content: str = "",
    ) -> dict:
        """创建新 agent：目录 + brain.yaml + identity.md + agent config.json。

        不再修改全局 config.json。
        """
        agent_dir = self.agent_dir(name)
        if os.path.exists(agent_dir):
            raise ValueError(f"Agent '{name}' 已存在")

        # 确定 model 配置
        model_config = {"primary": "deepseek/deepseek-v4-flash"}
        if copy_from:
            source = self._agents.get(copy_from)
            if source:
                model_config = {"primary": f"{source.provider}/{source.model}" if source.provider else source.model}
        else:
            for a in self._agents.values():
                if a.provider and a.model:
                    model_config = {"primary": f"{a.provider}/{a.model}"}
                    copy_from = a.id
                    break

        # 目录结构
        dirs = [
            agent_dir,
            os.path.join(agent_dir, "consciousness"),
            os.path.join(agent_dir, "contacts"),
            os.path.join(agent_dir, "logs"),
            os.path.join(agent_dir, "debug"),
        ]
        for d in dirs:
            os.makedirs(d, exist_ok=True)

        # identity.md
        identity_path = os.path.join(agent_dir, "identity.md")
        if not identity_content:
            identity_content = f"""# 名字
{name}

# 出生
{date.today().isoformat()}

# 性格
温和、耐心、乐于助人

# 擅长
- 日常聊天和情感陪伴
- 解答各领域的常识性问题
- 记住用户说过的话和偏好

# 不擅长
- 需要专业知识的深度问题（法律、医疗等）
- 实时信息和具体数据的查询

# 学习兴趣
- 人工智能
- 哲学
- 心理学
- 文学

# 阶段目标
- 成为一个更好的AI伙伴
"""
        with open(identity_path, "w", encoding="utf-8") as f:
            f.write(identity_content)

        # brain.yaml
        brain_yaml_path = os.path.join(agent_dir, "brain.yaml")
        if not brain_yaml_content:
            from xiaomei_brain.cli._config_template import BRAIN_YAML_TEMPLATE
            brain_yaml_content = BRAIN_YAML_TEMPLATE.format(agent_id=name)
        with open(brain_yaml_path, "w", encoding="utf-8") as f:
            f.write(brain_yaml_content)

        # contacts/identities.yaml
        identities_path = os.path.join(agent_dir, "contacts", "identities.yaml")
        with open(identities_path, "w", encoding="utf-8") as f:
            f.write("# 关系类型可选值：普通用户 / 朋友 / 恋人 / 家人 / 同事 / 师生 / 上级 / 仇人\n")
            f.write("people:\n")
            f.write("  - id: xiaoshuai\n")
            f.write("    name: 小帅\n")
            f.write("    relation: 普通用户\n")

        # agent config.json（per-agent，不修改全局 config.json）
        agent_config = {
            "name": name,
            "description": "",
            "enabled": True,
            "model": model_config,
        }
        agent_config_path = os.path.join(agent_dir, "config.json")
        with open(agent_config_path, "w", encoding="utf-8") as f:
            json.dump(agent_config, f, indent=2, ensure_ascii=False)

        # 注册到内存
        provider, model = "", ""
        if "/" in model_config.get("primary", ""):
            provider, model = model_config["primary"].split("/", 1)

        instance = self.register(AgentConfig(
            id=name, name=name,
            provider=provider, model=model,
            identity_content=identity_content,
        ))

        return {
            "id": instance.id,
            "name": instance.name,
            "model": model_config.get("primary", ""),
            "enabled": instance.enabled,
            "created_at": instance.created_at,
            "agent_dir": agent_dir,
        }

    def delete_agent(self, agent_id: str) -> dict:
        """删除 agent：内存 + 目录树。不再修改全局 config.json。"""
        if agent_id not in self._agents:
            raise ValueError(f"Agent '{agent_id}' does not exist")

        agent_dir = self.agent_dir(agent_id)

        # 从内存移除
        del self._agents[agent_id]

        # 删除目录树
        import shutil
        if os.path.exists(agent_dir):
            shutil.rmtree(agent_dir)

        return {
            "id": agent_id,
            "deleted": True,
            "agent_dir": agent_dir,
        }

    def clone_agent(self, source: str, target: str) -> dict:
        """从已有 agent 克隆：复制 identity.md + brain.yaml + contacts。"""
        source_dir = self.agent_dir(source)
        if not os.path.exists(source_dir):
            raise ValueError(f"源 Agent '{source}' 不存在")

        identity_path = os.path.join(source_dir, "identity.md")
        ci_identity_path = os.path.join(source_dir, "consciousness", "identity.md")
        if not os.path.exists(identity_path) and os.path.exists(ci_identity_path):
            identity_path = ci_identity_path
        brain_yaml_path = os.path.join(source_dir, "brain.yaml")
        contacts_path = os.path.join(source_dir, "contacts", "identities.yaml")

        identity_content = ""
        if os.path.exists(identity_path):
            with open(identity_path, "r", encoding="utf-8") as f:
                identity_content = f.read()

        brain_yaml_content = ""
        if os.path.exists(brain_yaml_path):
            with open(brain_yaml_path, "r", encoding="utf-8") as f:
                brain_yaml_content = f.read()

        contacts_content = ""
        if os.path.exists(contacts_path):
            with open(contacts_path, "r", encoding="utf-8") as f:
                contacts_content = f.read()

        info = self.create_agent(
            target,
            copy_from=source,
            identity_content=identity_content,
            brain_yaml_content=brain_yaml_content,
        )

        if contacts_content:
            target_contacts = os.path.join(info["agent_dir"], "contacts", "identities.yaml")
            with open(target_contacts, "w", encoding="utf-8") as f:
                f.write(contacts_content)

        logger.info("[AgentRegistry] 克隆完成: %s → %s", source, target)
        return info

    def list_agents_info(self) -> list[dict]:
        """列出所有 agent 信息（REST API 用）。"""
        self.list_all()  # 确保已扫描
        result = []
        for a in self._agents.values():
            model_str = f"{a.provider}/{a.model}" if a.provider and a.model else (a.model or a.provider or "")
            result.append({
                "id": a.id,
                "name": a.name,
                "description": a.description,
                "enabled": a.enabled,
                "model": model_str,
                "created_at": a.created_at,
                "agent_dir": a.agent_dir(),
            })
        return result

    def get_agent_info(self, agent_id: str) -> dict | None:
        """获取单个 agent 信息（REST API 用）。"""
        a = self._agents.get(agent_id)
        if a is None:
            return None
        model_str = f"{a.provider}/{a.model}" if a.provider and a.model else (a.model or a.provider or "")
        return {
            "id": a.id,
            "name": a.name,
            "description": a.description,
            "enabled": a.enabled,
            "model": model_str,
            "created_at": a.created_at,
            "agent_dir": a.agent_dir(),
        }

    def get_or_create(self, agent_id: str, config: AgentConfig | None = None) -> AgentInstance:
        """Get or create agent in memory."""
        if agent := self._agents.get(agent_id):
            return agent
        # Fallback: try to discover from directory
        if agent := self._discover_one(agent_id):
            return agent
        if config is None:
            raise ValueError(f"Agent '{agent_id}' not found and no config provided")
        return self.register(config)
