import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from xiaomei_brain.gateway.server_methods import MethodRouter
from xiaomei_brain.gateway.connection import cm
from xiaomei_brain.memory.conversation_db import ConversationDB
from xiaomei_brain.people import PeopleService


class GatewaySessionsTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "brain.db"
        self.db = ConversationDB(self.db_path)
        self.people = PeopleService.for_agent_db(self.db_path)
        self.person = self.people.create_person("Desktop Person")

    def tearDown(self):
        cm.unregister("desktop-connection")
        self.people.store.close()
        self.db.close()
        self.temp_dir.cleanup()

    def authorized_router(self, *session_ids):
        for session_id in session_ids:
            self.people.store.ensure_session(
                session_id,
                "person",
                self.person.person_id,
            )
        living = SimpleNamespace(
            agent=SimpleNamespace(conversation_db=self.db),
            _people_service=self.people,
        )
        router = MethodRouter(living=living)
        router._auth_sessions.add("desktop-connection")
        cm.set_session("rpc-current", "desktop-connection", self.person.person_id)
        return router

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
        router = self.authorized_router("desktop-session")

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

    def test_session_list_exposes_channel_and_recognizes_legacy_channel_ids(self):
        self.db.log(
            "feishu-person-1",
            "user",
            "from feishu",
            metadata={"channel": "feishu"},
        )
        self.db.log("dingtalk-person-1", "user", "legacy dingtalk")
        self.db.log("desktop-session", "user", "from desktop")

        sessions = {
            item["session_id"]: item
            for item in self.db.list_sessions()
        }

        self.assertEqual(sessions["feishu-person-1"]["channel"], "feishu")
        self.assertEqual(sessions["dingtalk-person-1"]["channel"], "dingtalk")
        self.assertEqual(sessions["desktop-session"]["channel"], "desktop")

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

    def test_chat_history_restores_user_turn_status(self):
        self.db.log(
            "status-session",
            "user",
            "please retry",
            metadata={
                "turn_id": "turn-1",
                "status": "failed",
                "error": {"code": "LLM_UNAVAILABLE", "message": "offline"},
            },
        )
        living = SimpleNamespace(agent=SimpleNamespace(conversation_db=self.db))
        router = MethodRouter(living=living)
        router._auth_sessions.add("desktop-connection")

        result = router.dispatch(
            "desktop-connection",
            "history-status",
            "chat.history",
            {"session_id": "status-session", "limit": 20},
        )["result"]

        self.assertEqual(result["messages"][0]["turn_id"], "turn-1")
        self.assertEqual(result["messages"][0]["status"], "failed")
        self.assertEqual(result["messages"][0]["error"]["message"], "offline")

    def test_chat_history_restores_assistant_memory_references(self):
        references = [{
            "id": "42",
            "summary": "李白希望优先完善独立 Agent",
            "source": "immediate",
            "memory_type": "common",
            "tags": ["产品方向"],
            "created_at": 123.0,
        }]
        self.db.log(
            "memory-session",
            "assistant",
            "我们继续完善独立 Agent。",
            metadata={
                "turn_id": "turn-memory",
                "memory_references": references,
            },
        )
        living = SimpleNamespace(
            agent=SimpleNamespace(conversation_db=self.db),
        )
        router = MethodRouter(living=living)
        router._auth_sessions.add("desktop-connection")

        result = router.dispatch(
            "desktop-connection",
            "history-memory",
            "chat.history",
            {"session_id": "memory-session", "limit": 20},
        )["result"]

        self.assertEqual(result["messages"][0]["turn_id"], "turn-memory")
        self.assertEqual(
            result["messages"][0]["memory_references"],
            references,
        )

    def test_chat_history_restores_assistant_reasoning_content(self):
        self.db.log(
            "reasoning-session",
            "assistant",
            "final answer",
            metadata={
                "turn_id": "turn-reasoning",
                "reasoning_content": "consider the evidence first",
            },
        )
        living = SimpleNamespace(agent=SimpleNamespace(conversation_db=self.db))
        router = MethodRouter(living=living)
        router._auth_sessions.add("desktop-connection")

        result = router.dispatch(
            "desktop-connection",
            "history-reasoning",
            "chat.history",
            {"session_id": "reasoning-session", "limit": 20},
        )["result"]

        self.assertEqual(
            result["messages"][0]["reasoning_content"],
            "consider the evidence first",
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

    def test_chat_history_restores_capability_setup_card(self):
        self.db.log("setup-session", "user", "搜索今天的行业新闻")
        self.db.save_interaction({
            "id": "capability-setup-1",
            "kind": "capability_setup",
            "capability_id": "web_search",
            "capability_name": "联网搜索",
            "capability_status": "needs_setup",
            "summary": "联网搜索服务尚未配置。",
            "session_id": "setup-session",
            "turn_id": "turn-setup",
            "user_id": self.person.person_id,
            "action": {
                "type": "open_settings",
                "section": "search",
                "target": "web_search_baidu",
                "label": "配置联网搜索服务",
            },
        })
        self.db.update_interaction_metadata("capability-setup-1", {
            "resume_status": "resumed",
            "resumed_message_id": 99,
        })
        living = SimpleNamespace(agent=SimpleNamespace(conversation_db=self.db))
        router = MethodRouter(living=living)
        router._auth_sessions.add("desktop-connection")

        response = router.dispatch(
            "desktop-connection",
            "history-setup-card",
            "chat.history",
            {"session_id": "setup-session", "limit": 20},
        )
        self.assertNotIn("error", response, response)
        result = response["result"]

        self.assertEqual([item["role"] for item in result["messages"]], ["user", "interaction"])
        setup = result["messages"][1]["capability_setup"]
        self.assertEqual(setup["capability_id"], "web_search")
        self.assertEqual(setup["action"]["section"], "search")
        self.assertEqual(setup["resume_status"], "resumed")
        self.assertEqual(setup["resumed_message_id"], 99)

    def test_chat_sessions_supports_search_and_offset_pagination(self):
        self.db.log("session-alpha", "user", "ordinary discussion")
        self.db.log("session-beta", "user", "needle in the title")
        self.db.log("session-gamma", "user", "another discussion")
        router = self.authorized_router(
            "session-alpha",
            "session-beta",
            "session-gamma",
        )

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
