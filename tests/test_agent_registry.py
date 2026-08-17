import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from xiaomei_brain.agent.registry import AgentRegistry


class AgentRegistryCreationTests(unittest.TestCase):
    def test_create_agent_with_desktop_fields(self):
        with tempfile.TemporaryDirectory() as rootdir:
            registry = AgentRegistry(rootdir)

            result = registry.create_agent(
                "employee-1",
                display_name="小明",
                description="负责软件开发",
                ws_port=19770,
            )

            agent_dir = Path(rootdir) / "employee-1"
            config = json.loads((agent_dir / "config.json").read_text(encoding="utf-8"))
            identity = (agent_dir / "identity.md").read_text(encoding="utf-8")
            identities = (agent_dir / "contacts" / "identities.yaml").read_text(encoding="utf-8")

            self.assertEqual(result["id"], "employee-1")
            self.assertEqual(result["name"], "小明")
            self.assertEqual(result["description"], "负责软件开发")
            self.assertEqual(result["ws_port"], 19770)
            self.assertEqual(config["name"], "小明")
            self.assertEqual(config["description"], "负责软件开发")
            self.assertEqual(config["ws_port"], 19770)
            self.assertEqual(config["admin_port"], 19771)
            self.assertIn("# 名字\n小明", identity)
            self.assertIn("# 职责\n负责软件开发", identity)
            self.assertEqual(identities.splitlines()[-1], "people: []")
            self.assertNotIn("xiaoshuai", identities)

            expected_directories = {
                "consciousness",
                "contacts",
                "debug",
                "integrations",
                "logs",
                "memory",
                "people",
                "schedule",
                "secrets",
                "sessions",
                "skills",
                "workspace",
            }
            self.assertTrue(expected_directories.issubset({
                path.name for path in agent_dir.iterdir() if path.is_dir()
            }))
            for relative in (
                "people/biometrics",
                "people/biometrics/faces",
                "people/biometrics/voices",
                "workspace/inputs/attachments",
                "workspace/work",
                "workspace/outputs/images",
                "workspace/outputs/audio",
                "workspace/outputs/video",
                "workspace/outputs/documents",
                "workspace/projects",
            ):
                self.assertTrue((agent_dir / relative).is_dir(), relative)

            # Database schemas are intentionally not frozen into creation.
            # The current stores own and initialize/migrate their own tables.
            self.assertFalse((agent_dir / "memory" / "brain.db").exists())

            from xiaomei_brain.contacts.manager import IdentityManager

            self.assertEqual(IdentityManager(agent_dir / "contacts").list_ids(), [])

    def test_create_agent_rejects_unsafe_ids(self):
        with tempfile.TemporaryDirectory() as rootdir:
            registry = AgentRegistry(rootdir)
            for agent_id in ["../escape", "..\\escape", "", ".."]:
                with self.subTest(agent_id=agent_id):
                    with self.assertRaisesRegex(ValueError, "Agent ID"):
                        registry.create_agent(agent_id)

    def test_create_agent_inherits_global_default_model(self):
        with tempfile.TemporaryDirectory() as rootdir:
            Path(rootdir, "config.json").write_text(
                json.dumps({
                    "agents": {
                        "defaults": {"model": {"primary": "demo/current-model"}}
                    }
                }),
                encoding="utf-8",
            )

            result = AgentRegistry(rootdir).create_agent("employee-2")
            config = json.loads(
                Path(rootdir, "employee-2", "config.json").read_text(encoding="utf-8")
            )

            self.assertEqual(result["model"], "demo/current-model")
            self.assertEqual(config["model"]["primary"], "demo/current-model")

    def test_list_ignores_missing_identity_when_scanning_legacy_agent(self):
        with tempfile.TemporaryDirectory() as rootdir:
            agent_dir = Path(rootdir) / "legacy-agent"
            agent_dir.mkdir()
            (agent_dir / "brain.yaml").write_text("name: legacy\n", encoding="utf-8")

            agents = AgentRegistry(rootdir).list_all()

            self.assertEqual([agent.id for agent in agents], ["legacy-agent"])
            self.assertEqual(agents[0].name, "legacy-agent")

    def test_register_reconciles_existing_agent_layout_without_overwriting_contacts(self):
        with tempfile.TemporaryDirectory() as rootdir:
            agent_dir = Path(rootdir) / "legacy-agent"
            contacts = agent_dir / "contacts"
            contacts.mkdir(parents=True)
            identities = contacts / "identities.yaml"
            original = "people:\n  - id: real-person\n    name: 真实人物\n"
            identities.write_text(original, encoding="utf-8")

            from xiaomei_brain.agent.instance import AgentConfig

            AgentRegistry(rootdir).register(AgentConfig(id="legacy-agent"))

            self.assertEqual(identities.read_text(encoding="utf-8"), original)
            self.assertTrue((agent_dir / "workspace" / "outputs" / "documents").is_dir())
            self.assertTrue((agent_dir / "people" / "biometrics").is_dir())

    def test_first_build_reconciles_layout_for_discovered_legacy_agent(self):
        with tempfile.TemporaryDirectory() as rootdir:
            agent_dir = Path(rootdir) / "legacy-agent"
            agent_dir.mkdir()
            (agent_dir / "identity.md").write_text("# 名字\n旧 Agent\n", encoding="utf-8")

            from xiaomei_brain.agent.agent_manager import AgentManager

            manager = AgentManager(rootdir)
            agent = manager.get("legacy-agent")
            self.assertIsNotNone(agent)
            # A pre-initialized core avoids loading providers; this test only
            # exercises the first-build layout reconciliation boundary.
            agent.llm = object()

            built = manager.build_agent("legacy-agent")

            self.assertIs(built, agent)
            self.assertTrue((agent_dir / "memory").is_dir())
            self.assertTrue((agent_dir / "workspace" / "inputs" / "attachments").is_dir())
            self.assertTrue((agent_dir / "contacts" / "identities.yaml").is_file())

    def test_created_agent_database_is_initialized_by_current_store_schemas(self):
        with tempfile.TemporaryDirectory() as rootdir:
            agent_dir = Path(rootdir) / "employee-3"
            AgentRegistry(rootdir).create_agent("employee-3")
            db_path = agent_dir / "memory" / "brain.db"

            from xiaomei_brain.activity.store import ActivityStore
            from xiaomei_brain.consciousness.missions.store import MissionStore
            from xiaomei_brain.memory.conversation_db import ConversationDB
            from xiaomei_brain.memory.short_term import ShortTermMemoryStore
            from xiaomei_brain.people.store import PeopleStore

            stores = (
                ConversationDB(db_path),
                ShortTermMemoryStore(db_path),
                PeopleStore(db_path),
                ActivityStore(db_path),
                MissionStore(db_path),
            )
            for store in stores:
                store.close()

            conn = sqlite3.connect(db_path)
            try:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                versions = {
                    row[0]
                    for row in conn.execute("SELECT component FROM schema_versions")
                }
            finally:
                conn.close()

            self.assertTrue({
                "messages",
                "memories0",
                "persons",
                "agent_activity_runs",
                "missions",
            }.issubset(tables))
            self.assertTrue({
                "conversation_db",
                "people",
                "agent_activity_storage",
                "missions",
            }.issubset(versions))


if __name__ == "__main__":
    unittest.main()
