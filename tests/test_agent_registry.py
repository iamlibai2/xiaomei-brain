import json
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

    def test_create_agent_rejects_unsafe_ids(self):
        with tempfile.TemporaryDirectory() as rootdir:
            registry = AgentRegistry(rootdir)
            for agent_id in ["../escape", "..\\escape", "", ".."]:
                with self.subTest(agent_id=agent_id):
                    with self.assertRaisesRegex(ValueError, "Agent ID"):
                        registry.create_agent(agent_id)


if __name__ == "__main__":
    unittest.main()
