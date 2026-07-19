import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from xiaomei_brain.gateway.server_methods import MethodRouter
from xiaomei_brain.memory.conversation_db import ConversationDB


class GatewaySessionsTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = ConversationDB(Path(self.temp_dir.name) / "brain.db")

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_list_sessions_returns_recent_chat_summaries(self):
        self.db.log("session-old", "user", "older question")
        self.db.log("session-old", "assistant", "older answer")
        self.db.log("session-new", "user", "newer question")
        self.db.log("session-new", "tool", "internal result")
        self.db.log("session-new", "assistant", "newer answer")
        self.db.log("", "user", "not a real session")

        sessions = self.db.list_sessions()

        self.assertEqual(
            [session["session_id"] for session in sessions],
            ["session-new", "session-old"],
        )
        self.assertEqual(sessions[0]["first_user_message"], "newer question")
        self.assertEqual(sessions[0]["message_count"], 2)
        self.assertGreaterEqual(sessions[0]["updated_at"], sessions[0]["created_at"])

    def test_chat_sessions_rpc_uses_agent_conversation_database(self):
        self.db.log("desktop-session", "user", "restore me")
        living = SimpleNamespace(agent=SimpleNamespace(conversation_db=self.db))
        router = MethodRouter(living=living)
        router._auth_sessions.add("desktop-connection")

        response = router.dispatch(
            "desktop-connection",
            "request-1",
            "chat.sessions",
            {"limit": 20},
        )

        self.assertNotIn("error", response)
        session = response["result"]["sessions"][0]
        self.assertEqual(session["session_id"], "desktop-session")
        self.assertEqual(session["first_user_message"], "restore me")


if __name__ == "__main__":
    unittest.main()
