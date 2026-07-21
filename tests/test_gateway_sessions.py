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

    def test_chat_history_uses_message_id_cursor_without_duplicates(self):
        message_ids = [
            self.db.log("paged-session", "user", f"message {index}")
            for index in range(5)
        ]
        living = SimpleNamespace(agent=SimpleNamespace(conversation_db=self.db))
        router = MethodRouter(living=living)
        router._auth_sessions.add("desktop-connection")

        newest = router.dispatch(
            "desktop-connection",
            "history-1",
            "chat.history",
            {"session_id": "paged-session", "limit": 2},
        )["result"]
        older = router.dispatch(
            "desktop-connection",
            "history-2",
            "chat.history",
            {
                "session_id": "paged-session",
                "limit": 2,
                "before_id": newest["next_before_id"],
            },
        )["result"]

        self.assertEqual([message["id"] for message in newest["messages"]], message_ids[-2:])
        self.assertEqual([message["id"] for message in older["messages"]], message_ids[1:3])
        self.assertTrue(newest["has_more"])
        self.assertTrue(older["has_more"])
        self.assertFalse(
            {message["id"] for message in newest["messages"]}
            & {message["id"] for message in older["messages"]}
        )

    def test_chat_history_restores_interaction_timeline_record(self):
        self.db.log("card-session", "user", "help me choose")
        self.db.save_interaction({
            "id": "interaction-1",
            "question": "选择哪一种？",
            "choices": ["简约", "科技"],
            "session_id": "card-session",
            "user_id": "desktop-user",
            "status": "pending",
            "response": "",
            "created_at": 1.0,
        })
        self.db.save_interaction({
            "id": "interaction-1",
            "question": "选择哪一种？",
            "choices": ["简约", "科技"],
            "session_id": "card-session",
            "user_id": "desktop-user",
            "status": "answered",
            "response": "科技",
            "created_at": 1.0,
        })
        self.db.log("card-session", "assistant", "科技风格方案")

        living = SimpleNamespace(agent=SimpleNamespace(conversation_db=self.db))
        router = MethodRouter(living=living)
        router._auth_sessions.add("desktop-connection")
        result = router.dispatch(
            "desktop-connection",
            "history-card",
            "chat.history",
            {"session_id": "card-session", "limit": 20},
        )["result"]

        self.assertEqual(
            [message["role"] for message in result["messages"]],
            ["user", "interaction", "assistant"],
        )
        self.assertEqual(result["messages"][1]["interaction"]["status"], "answered")
        self.assertEqual(result["messages"][1]["interaction"]["response"], "科技")
        self.assertEqual(
            [row["role"] for row in self.db.get_recent(20, session_id="card-session")],
            ["user", "assistant"],
        )

    def test_chat_sessions_supports_search_and_offset_pagination(self):
        self.db.log("session-alpha", "user", "ordinary discussion")
        self.db.log("session-beta", "user", "needle in the title")
        self.db.log("session-gamma", "user", "another discussion")
        living = SimpleNamespace(agent=SimpleNamespace(conversation_db=self.db))
        router = MethodRouter(living=living)
        router._auth_sessions.add("desktop-connection")

        first_page = router.dispatch(
            "desktop-connection",
            "sessions-1",
            "chat.sessions",
            {"limit": 2, "offset": 0},
        )["result"]
        second_page = router.dispatch(
            "desktop-connection",
            "sessions-2",
            "chat.sessions",
            {"limit": 2, "offset": first_page["next_offset"]},
        )["result"]
        search = router.dispatch(
            "desktop-connection",
            "sessions-3",
            "chat.sessions",
            {"query": "needle", "limit": 30},
        )["result"]

        self.assertEqual(len(first_page["sessions"]), 2)
        self.assertTrue(first_page["has_more"])
        self.assertEqual(len(second_page["sessions"]), 1)
        self.assertFalse(second_page["has_more"])
        self.assertEqual(
            [session["session_id"] for session in search["sessions"]],
            ["session-beta"],
        )


if __name__ == "__main__":
    unittest.main()
