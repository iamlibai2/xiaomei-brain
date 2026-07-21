import threading
import unittest
from types import SimpleNamespace

from xiaomei_brain.consciousness.interaction_broker import InteractionBroker
from xiaomei_brain.gateway.connection import cm
from xiaomei_brain.gateway.server_methods import MethodRouter
from xiaomei_brain.tools.builtin.clarify import clarify


class InteractionBrokerTest(unittest.TestCase):
    def test_clarify_choices_are_exposed_as_string_array(self):
        self.assertEqual(clarify.parameters["properties"]["choices"], {
            "type": "array",
            "items": {"type": "string"},
        })

    def test_request_waits_for_response_from_same_session(self):
        published = []
        requested = threading.Event()

        def publish(event, payload):
            published.append((event, payload))
            if event == "interaction.requested":
                requested.set()

        broker = InteractionBroker(publish)
        result = []
        worker = threading.Thread(
            target=lambda: result.append(broker.request(
                "先做哪个？", ["设计", "实现"], "session-a", "user-a", timeout=1,
            )),
        )
        worker.start()
        self.assertTrue(requested.wait(timeout=1))
        request_id = published[0][1]["id"]

        self.assertFalse(broker.respond(request_id, "实现", "session-b"))
        self.assertTrue(broker.respond(request_id, "实现", "session-a"))
        worker.join(timeout=1)

        self.assertEqual(result, ["实现"])
        self.assertEqual([event for event, _ in published], [
            "interaction.requested", "interaction.updated",
        ])
        self.assertEqual(published[-1][1]["status"], "answered")

    def test_cancel_session_releases_only_matching_request(self):
        published = []
        both_requested = threading.Event()

        def publish(event, payload):
            published.append((event, payload))
            requested_count = sum(
                name == "interaction.requested" for name, _ in published
            )
            if requested_count == 2:
                both_requested.set()

        broker = InteractionBroker(publish)
        results = {}

        def ask(session_id):
            results[session_id] = broker.request(
                "继续吗？", ["继续", "停止"], session_id, "user", timeout=1,
            )

        worker_a = threading.Thread(target=ask, args=("session-a",))
        worker_b = threading.Thread(target=ask, args=("session-b",))
        worker_a.start()
        worker_b.start()
        self.assertTrue(both_requested.wait(timeout=1))

        broker.cancel_session("session-a")
        worker_a.join(timeout=1)
        self.assertFalse(worker_a.is_alive())
        self.assertTrue(worker_b.is_alive())
        self.assertEqual(results["session-a"], "")

        request_b = next(
            payload["id"] for event, payload in published
            if event == "interaction.requested" and payload["session_id"] == "session-b"
        )
        self.assertTrue(broker.respond(request_b, "继续", "session-b"))
        worker_b.join(timeout=1)
        self.assertEqual(results["session-b"], "继续")

    def test_gateway_response_uses_authenticated_connection_session(self):
        class Broker:
            def __init__(self):
                self.calls = []

            def respond(self, request_id, response, session_id):
                self.calls.append((request_id, response, session_id))
                return True

        broker = Broker()
        router = MethodRouter(living=SimpleNamespace(_interaction_broker=broker))
        conn_id = "interaction-test-connection"
        session_id = "interaction-test-session"
        router._auth_sessions.add(conn_id)
        cm.set_session(session_id, conn_id)
        try:
            response = router.dispatch(
                conn_id,
                "request-1",
                "interaction.respond",
                {"request_id": "interaction-1", "response": "继续"},
            )
        finally:
            cm.unregister(conn_id)

        self.assertNotIn("error", response)
        self.assertEqual(broker.calls, [("interaction-1", "继续", session_id)])

    def test_gateway_abort_and_disconnect_cancel_connection_session(self):
        class Broker:
            def __init__(self):
                self.cancelled = []

            def cancel_session(self, session_id):
                self.cancelled.append(session_id)

        broker = Broker()
        living = SimpleNamespace(
            _interaction_broker=broker,
            abort_chat=lambda: None,
        )
        router = MethodRouter(living=living)
        conn_id = "abort-test-connection"
        session_id = "abort-test-session"
        router._auth_sessions.add(conn_id)
        cm.set_session(session_id, conn_id)
        try:
            response = router.dispatch(conn_id, "request-2", "chat.abort", {})
            self.assertNotIn("error", response)
            router.drop_session(conn_id)
        finally:
            cm.unregister(conn_id)

        self.assertEqual(broker.cancelled, [session_id, session_id])


if __name__ == "__main__":
    unittest.main()
