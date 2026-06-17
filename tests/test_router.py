"""Tests for gateway/router.py -- message routing and match scoring."""

import pytest
from unittest.mock import MagicMock
from xiaomei_brain.gateway.router import (
    Router,
    PeerRule,
    InboundMsg,
    RoutedMsg,
    OutputRoute,
)


# ── OutputRoute ───────────────────────────────────────────────────────

def test_output_route_hash():
    r1 = OutputRoute("cli", "stdout")
    r2 = OutputRoute("cli", "stdout")
    r3 = OutputRoute("ws", "stdout")
    assert hash(r1) == hash(r2)
    assert hash(r1) != hash(r3)


# ── InboundMsg ────────────────────────────────────────────────────────

def test_inbound_msg_defaults():
    msg = InboundMsg(content="hello")
    assert msg.peer_type == "human"
    assert msg.peer_id == ""
    assert msg.channel == "cli"
    assert msg.images == []


# ── Router._match_score ───────────────────────────────────────────────

def test_match_score_exact():
    rule = PeerRule(peer_type="human", peer_id="libai", channel="cli")
    msg = InboundMsg(content="hello", peer_type="human", peer_id="libai", channel="cli")
    # type=10 + peer_id=5 + channel=1 = 16
    assert Router._match_score(rule, msg) == 16


def test_match_score_wildcard_peer():
    rule = PeerRule(peer_type="human", peer_id="*", channel="*")
    msg = InboundMsg(content="hello", peer_type="human", peer_id="anyone")
    # type=10 + peer_id(wildcard)=0 + channel(wildcard)=0 = 10
    assert Router._match_score(rule, msg) == 10


def test_match_score_wildcard_channel():
    rule = PeerRule(peer_type="human", peer_id="libai", channel="*")
    msg = InboundMsg(content="hello", peer_type="human", peer_id="libai", channel="feishu")
    # type=10 + peer_id=5 + channel(wildcard)=0 = 15
    assert Router._match_score(rule, msg) == 15


def test_match_score_type_mismatch():
    rule = PeerRule(peer_type="human", peer_id="libai")
    msg = InboundMsg(content="hello", peer_type="agent", peer_id="libai")
    assert Router._match_score(rule, msg) == -1


def test_match_score_peer_mismatch():
    rule = PeerRule(peer_type="human", peer_id="libai")
    msg = InboundMsg(content="hello", peer_type="human", peer_id="boshi")
    assert Router._match_score(rule, msg) == -1


def test_match_score_channel_mismatch():
    rule = PeerRule(peer_type="human", peer_id="libai", channel="cli")
    msg = InboundMsg(content="hello", peer_type="human", peer_id="libai", channel="feishu")
    assert Router._match_score(rule, msg) == -1


# ── Router init ───────────────────────────────────────────────────────

def test_router_init():
    r = Router()
    assert r._rules == []
    assert r._adapters == {}


# ── add_rule / register_peer ──────────────────────────────────────────

def test_add_rule():
    r = Router()
    r.add_rule(PeerRule(peer_type="human", peer_id="libai", priority=5))
    r.add_rule(PeerRule(peer_type="human", peer_id="*", priority=1))
    assert len(r._rules) == 2
    # Rules sorted by priority descending
    assert r._rules[0].priority == 5


def test_register_peer():
    r = Router()
    r.register_peer("human", "libai", channel="cli", session_id="s1", priority=10)
    assert len(r._rules) == 1
    assert r._rules[0].session_id == "s1"


def test_remove_peer():
    r = Router()
    r.add_rule(PeerRule(peer_type="human", peer_id="libai"))
    r.add_rule(PeerRule(peer_type="human", peer_id="boshi"))
    r.remove_peer("libai")
    assert len(r._rules) == 1
    assert r._rules[0].peer_id == "boshi"


def test_remove_peer_no_match():
    r = Router()
    r.add_rule(PeerRule(peer_type="human", peer_id="libai"))
    r.remove_peer("nobody")  # no-op


# ── route ─────────────────────────────────────────────────────────────

def test_route_exact_match():
    r = Router()
    r.add_rule(PeerRule(
        peer_type="human", peer_id="libai", channel="cli",
        session_id="s_libai", priority=10,
    ))
    result = r.route(InboundMsg(content="hi", peer_type="human", peer_id="libai", channel="cli"))
    assert result.session_id == "s_libai"
    assert result.content == "hi"


def test_route_human_gets_peer_id():
    r = Router()
    r.add_rule(PeerRule(peer_type="human", peer_id="libai", channel="*"))
    result = r.route(InboundMsg(content="hi", peer_type="human", peer_id="libai"))
    assert result.user_id == "libai"


def test_route_agent_gets_global():
    r = Router()
    r.add_rule(PeerRule(peer_type="agent", peer_id="lingkong", channel="*"))
    result = r.route(InboundMsg(content="hi", peer_type="agent", peer_id="lingkong"))
    assert result.user_id == "global"


def test_route_no_rules_default():
    r = Router()
    result = r.route(InboundMsg(content="hi"))
    assert result.session_id == "main"
    assert result.user_id == "global"  # peer_id is empty → "global"


def test_route_with_peer_id_no_rules():
    r = Router()
    result = r.route(InboundMsg(content="hi", peer_id="libai"))
    assert result.user_id == "libai"


def test_route_best_match_priority():
    r = Router()
    r.add_rule(PeerRule(peer_type="human", peer_id="*", channel="*", session_id="wildcard", priority=1))
    r.add_rule(PeerRule(peer_type="human", peer_id="libai", channel="cli", session_id="exact", priority=10))
    result = r.route(InboundMsg(content="hi", peer_type="human", peer_id="libai", channel="cli"))
    assert result.session_id == "exact"  # higher priority match wins


# ── route_for_session ─────────────────────────────────────────────────

def test_route_for_session():
    r = Router()
    r.add_rule(PeerRule(
        peer_type="human", peer_id="libai", session_id="s1",
        output_route=OutputRoute("ws", "conn1"),
    ))
    route = r.route_for_session("s1")
    assert route is not None
    assert route.type == "ws"


def test_route_for_session_not_found():
    r = Router()
    assert r.route_for_session("nonexistent") is None


# ── adapter ───────────────────────────────────────────────────────────

def test_register_adapter():
    r = Router()
    adapter = MagicMock()
    r.register_adapter("feishu", adapter)
    assert r.get_adapter("feishu") is adapter


def test_get_adapter_unknown():
    r = Router()
    assert r.get_adapter("unknown") is None


# ── deliver ───────────────────────────────────────────────────────────

def test_deliver_no_adapter():
    r = Router()
    route = OutputRoute("unknown", "target")
    assert r.deliver("hello", route) is False


def test_deliver_with_adapter():
    r = Router()
    adapter = MagicMock()
    r.register_adapter("cli", adapter)
    route = OutputRoute("cli", "stdout")
    assert r.deliver("hello", route) is True
    adapter.send.assert_called_once_with("stdout", "hello", msg_type="text")


def test_deliver_adapter_exception():
    r = Router()
    adapter = MagicMock()
    adapter.send.side_effect = RuntimeError("failed")
    r.register_adapter("cli", adapter)
    route = OutputRoute("cli", "stdout")
    assert r.deliver("hello", route) is False


# ── broadcast ─────────────────────────────────────────────────────────

def test_broadcast_deduplicates():
    r = Router()
    adapter = MagicMock()
    r.register_adapter("cli", adapter)
    # Two rules with same output route → should deliver only once
    r.add_rule(PeerRule(peer_type="human", peer_id="a", output_route=OutputRoute("cli", "stdout")))
    r.add_rule(PeerRule(peer_type="human", peer_id="b", output_route=OutputRoute("cli", "stdout")))
    sent = r.broadcast("hello")
    assert sent == 1  # deduplicated


# ── check_route ───────────────────────────────────────────────────────

def test_check_route_no_adapter():
    r = Router()
    route = OutputRoute("unknown", "target")
    assert r.check_route(route) is True  # no adapter → defaults to True


def test_check_route_with_ping():
    r = Router()
    adapter = MagicMock()
    adapter.ping.return_value = True
    r.register_adapter("ws", adapter)
    route = OutputRoute("ws", "conn1")
    assert r.check_route(route) is True
