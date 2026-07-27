"""Single-worker executor for an Agent's autonomous behaviours."""

from __future__ import annotations

import logging
import queue
import threading
import uuid
from typing import Any, Callable

from ..agent.runtime import AgentRuntimeContext, AgentRuntimeFactory


logger = logging.getLogger(__name__)
_STOP = object()


class AutonomousBehaviorExecutor:
    """Run autonomous actions serially without occupying Living's main loop."""

    def __init__(
        self,
        agent_instance: Any,
        execute: Callable[[Any, Any, Callable[[], bool]], bool],
    ) -> None:
        self._factory = AgentRuntimeFactory(agent_instance)
        self._execute = execute
        self._queue: queue.Queue[Any] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._current: Any | None = None

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._current is not None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="xiaomei-autonomous-behavior",
            daemon=True,
        )
        self._thread.start()

    def submit(self, item: Any) -> bool:
        if self._stop_event.is_set():
            return False
        self.start()
        self._queue.put(item)
        return True

    def stop(self, timeout: float = 10.0) -> None:
        self._stop_event.set()
        self._queue.put(_STOP)
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))
            if thread.is_alive():
                logger.warning("[AutonomousExecutor] 行为仍在退出，后台线程将随进程结束")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            item = self._queue.get()
            if item is _STOP:
                break
            with self._lock:
                self._current = item
            try:
                action_name = getattr(getattr(item, "action_type", None), "value", "action")
                run_id = uuid.uuid4().hex
                runtime = self._factory.create(AgentRuntimeContext(
                    session_id=f"autonomous:{action_name}:{run_id}",
                    turn_id=f"turn_{run_id}",
                    user_id="system",
                    memory_scope_id="global",
                    max_steps=50,
                ))
                self._execute(item, runtime, self._stop_event.is_set)
            except Exception:
                logger.exception("[AutonomousExecutor] 自主行为执行失败")
            finally:
                with self._lock:
                    self._current = None

