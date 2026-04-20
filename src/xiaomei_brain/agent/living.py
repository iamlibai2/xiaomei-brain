"""AgentLiving: a living agent with lifecycle states.

Each agent runs as an independent process with its own event loop.
States cycle between AWAKE (handling messages) and SLEEPING (internal work).

Usage:
    from xiaomei_brain.agent.agent_manager import AgentManager
    from xiaomei_brain.agent.living import AgentLiving

    manager = AgentManager()
    instance = manager.build_agent("xiaomei")

    living = AgentLiving(instance)
    living.put_message("你好", user_id="张三")
    living.run()   # blocking, runs until stop()
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from xiaomei_brain.agent.proactive_output import ProactiveOutput, ProactiveTrigger

logger = logging.getLogger(__name__)


# ── States ──────────────────────────────────────────────────────────────

class AgentState(Enum):
    DORMANT = "dormant"
    WAKING = "waking"
    AWAKE = "awake"
    IDLE = "idle"
    SLEEPING = "sleeping"
    DREAMING = "dreaming"


# ── Message ─────────────────────────────────────────────────────────────

@dataclass
class LivingMessage:
    """A message from an external channel."""
    content: str
    user_id: str = "global"
    session_id: str = "main"
    source: str = ""  # which channel: "cli", "feishu", "websocket", etc.


# ── AgentLiving ─────────────────────────────────────────────────────────

class AgentLiving:
    """A living agent with lifecycle states.

    Main loop (synchronous — chat/LLM calls are blocking):
        DORMANT → WAKING → AWAKE ⇄ SLEEPING → DREAMING → SLEEPING ...

    AWAKE:  handle incoming messages via AgentInstance.chat()
    SLEEPING: wait for messages or trigger dream cycle
    DREAMING: dream phase (reinforce + extract) + reflect phase
    """

    def __init__(
        self,
        agent_instance: Any,
        idle_threshold: float = 1800,       # seconds before SLEEPING
        dream_interval: float = 300,        # seconds between dream cycles
        idle_short: float = 30,             # seconds before IDLE
    ) -> None:
        self.agent = agent_instance
        self.state = AgentState.DORMANT
        self.idle_threshold = idle_threshold
        self.dream_interval = dream_interval
        self.idle_short = idle_short

        self._queue: queue.Queue[LivingMessage | None] = queue.Queue()
        self._last_active: float = 0
        self._running: bool = False

        # Proactive output
        self.proactive = ProactiveOutput(agent_instance)

        # Channel callbacks
        self.on_proactive: Callable[[Any], Any] | None = None
        self.on_chat_chunk: Callable[[str], Any] | None = None

        # ── Hooks ────────────────────────────────────────────────
        self.on_wake: Callable[[], Any] | None = None
        self.on_sleep: Callable[[], Any] | None = None
        self.on_wake_up: Callable[[], Any] | None = None
        self.on_dream: Callable[[], Any] | None = None
        self.on_dream_end: Callable[[], Any] | None = None

    # ── Public API ───────────────────────────────────────────────

    def put_message(
        self,
        content: str,
        user_id: str = "global",
        session_id: str = "main",
        source: str = "",
    ) -> None:
        """Push a message into the living agent's queue (thread-safe)."""
        msg = LivingMessage(
            content=content,
            user_id=user_id,
            session_id=session_id,
            source=source,
        )
        self._queue.put_nowait(msg)

    def run(self) -> None:
        """Main loop — runs until stop() is called. Blocking."""
        self._running = True

        # ── DORMANT → WAKING ─────────────────────────────────────
        self._transition(AgentState.WAKING)

        # ── WAKING: morning routine ──────────────────────────────
        self._on_wake()
        self._transition(AgentState.AWAKE)

        # ── Main loop ────────────────────────────────────────────
        while self._running:
            if self.state == AgentState.AWAKE:
                self._loop_awake()
            elif self.state == AgentState.SLEEPING:
                self._loop_sleeping()
            elif self.state == AgentState.DREAMING:
                self._loop_dreaming()
            else:
                logger.warning("[Living] Unexpected state: %s", self.state)
                time.sleep(1)

    def stop(self) -> None:
        """Signal the main loop to stop."""
        self._running = False
        self._queue.put_nowait(None)  # unblock any waiting get()

    @property
    def is_running(self) -> bool:
        return self._running

    # ── State transitions ────────────────────────────────────────

    def _transition(self, new_state: AgentState) -> None:
        old = self.state
        self.state = new_state
        logger.info("[Living] %s → %s", old.value, new_state.value)

    # ── Loop: AWAKE ──────────────────────────────────────────────

    def _loop_awake(self) -> None:
        """Wait for messages. If idle too long, go to SLEEPING."""
        msg = self._wait_message(timeout=self.idle_short)

        if msg is not None:
            self._handle_message(msg)
            self._last_active = time.time()
            return

        if time.time() - self._last_active >= self.idle_threshold:
            for pmsg in self.proactive.check(ProactiveTrigger.IDLE):
                self._send_proactive(pmsg)
            self._on_sleep()
            self._transition(AgentState.SLEEPING)

    # ── Loop: SLEEPING ───────────────────────────────────────────

    def _loop_sleeping(self) -> None:
        """Wait for messages or trigger dream cycle on timeout."""
        for msg in self.proactive.check(ProactiveTrigger.REMINDER):
            self._send_proactive(msg)

        msg = self._wait_message(timeout=self.dream_interval)

        if msg is not None:
            self._on_wake_up()
            self._transition(AgentState.AWAKE)
            self._handle_message(msg)
            self._last_active = time.time()
            return

        self._on_dream()
        self._transition(AgentState.DREAMING)

    # ── Loop: DREAMING ───────────────────────────────────────────

    def _loop_dreaming(self) -> None:
        """Run one dream cycle: dream phase → reflect phase."""
        try:
            self._run_dream_cycle()
        except Exception as e:
            logger.error("[Living] Dream cycle failed: %s", e)

        self._on_dream_end()
        self._transition(AgentState.SLEEPING)

    # ── Dream cycle ──────────────────────────────────────────────

    def _run_dream_cycle(self) -> None:
        """One complete dream cycle: dream phase + reflect phase."""
        self._dream_phase()
        self._reflect_phase()

    def _dream_phase(self) -> None:
        """Reinforce low-strength memories + deep extraction."""
        from xiaomei_brain.memory.dream import DreamProcessor, make_reinforce_job, make_extract_job

        processor = DreamProcessor(
            self.agent.conversation_db,
            self.agent.memory_extractor,
        )
        processor.add_job(*make_reinforce_job(self.agent.longterm_memory))
        processor.add_job(*make_extract_job(self.agent.memory_extractor, "global"))

        results = processor.process_all()

        dream_topics = []
        for r in results:
            logger.info(
                "[Living/Dream] %s: saved=%d reinforced=%d extinct=%d",
                r.job, r.saved, r.reinforced, r.extinct,
            )
            if r.saved > 0 and r.details:
                dream_topics.append(r.details[:30])

        if dream_topics:
            self.proactive.notify_dream_result(dream_topics)

    def _reflect_phase(self) -> None:
        """Self-reflection — not yet implemented."""
        logger.debug("[Living/Reflect] (not yet implemented)")

    # ── Message handling ─────────────────────────────────────────

    def _handle_message(self, msg: LivingMessage) -> None:
        """Process one incoming message."""
        if self.agent.commands:
            result = self.agent.commands.execute(
                msg.content,
                user_id=msg.user_id,
                session_id=msg.session_id,
            )
            if result:
                logger.info("[Living] Command: %s", result.output)
                return

        try:
            content = self.agent.chat(
                msg.content,
                session_id=msg.session_id,
                user_id=msg.user_id,
                on_chunk=self.on_chat_chunk,
            )
            logger.info("[Living] Response: %s", content[:80].replace("\n", "\\n"))
        except Exception as e:
            logger.error("[Living] Chat failed: %s", e)
            # Write error response to DB so the user message isn't orphaned
            if self.agent.conversation_db:
                try:
                    self.agent.conversation_db.log(
                        session_id=msg.session_id,
                        role="assistant",
                        content=f"[系统] 回复失败：{e}",
                    )
                except Exception:
                    pass

    # ── Queue helpers ────────────────────────────────────────────

    def _wait_message(self, timeout: float) -> LivingMessage | None:
        """Wait for a message with timeout. Returns None on timeout."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    # ── Proactive output ─────────────────────────────────────────

    def _send_proactive(self, msg: Any) -> None:
        """Send a proactive message to channels."""
        if self.agent.conversation_db:
            try:
                self.agent.conversation_db.log(
                    session_id="main",
                    role="assistant",
                    content=f"[主动] {msg.content}",
                )
            except Exception:
                pass

        if self.on_proactive:
            try:
                self.on_proactive(msg)
            except Exception as e:
                logger.error("[Living] Proactive delivery failed: %s", e)

        logger.info("[Living/Proactive] [%s] %s", msg.trigger.value, msg.content[:60])

    # ── Hook implementations ─────────────────────────────────────

    def _on_wake(self) -> None:
        """DORMANT → WAKING: morning routine with self-positioning."""
        self._last_active = time.time()
        if self.on_wake:
            self.on_wake()

        messages = self.proactive.check(ProactiveTrigger.WAKE)
        for msg in messages:
            self._send_proactive(msg)

        logger.info("[Living] Good morning! Waking up.")

    def _on_sleep(self) -> None:
        """IDLE → SLEEPING: entering sleep."""
        if self.on_sleep:
            self.on_sleep()
        logger.info("[Living] Going to sleep (idle %ds)", self.idle_threshold)

    def _on_wake_up(self) -> None:
        """SLEEPING → AWAKE: external message wakes up."""
        if self.on_wake_up:
            self.on_wake_up()

        for msg in self.proactive.check(ProactiveTrigger.REMINDER):
            self._send_proactive(msg)

        for msg in self.proactive.check(ProactiveTrigger.RECALL):
            self._send_proactive(msg)

        logger.info("[Living] Waking up — message received!")

    def _on_dream(self) -> None:
        """SLEEPING → DREAMING: starting dream cycle."""
        if self.on_dream:
            self.on_dream()
        logger.info("[Living] Starting dream cycle...")

    def _on_dream_end(self) -> None:
        """DREAMING → SLEEPING: dream cycle finished."""
        if self.on_dream_end:
            self.on_dream_end()
        logger.info("[Living] Dream cycle finished, back to sleep.")
