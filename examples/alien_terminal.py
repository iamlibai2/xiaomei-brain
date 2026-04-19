#!/usr/bin/env python3
"""Alien (1979) Nostromo Terminal aesthetic for xiaomei-brain.

Inspired by the WYLIWYG display interface from the original film.
Amber phosphor CRT look, scanlines, boot sequence.
"""

from __future__ import annotations

import asyncio
import datetime
import math
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass
from typing import Generator

# ANSI color codes (amber phosphor)
AMBER = "\033[38;5;214m"
AMBER_DIM = "\033[38;5;130m"
AMBER_BRIGHT = "\033[38;5;220m"
GREEN = "\033[38;5;82m"
RED = "\033[38;5;160m"
CLEAR = "\033[2J\033[H"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
BOLD = "\033[1m"
RESET = "\033[0m"
SCANLINE = "\033[6n"  # request cursor position (used as marker)

# Box drawing
BOX_TL = "┌"
BOX_TR = "┐"
BOX_BL = "└"
BOX_BR = "┘"
BOX_V = "│"
BOX_H = "─"


@dataclass
class TerminalChar:
    char: str
    x: int
    y: int
    brightness: float = 1.0
    flicker: float = 1.0


class AlienTerminal:
    """Nostromo-style terminal with amber phosphor CRT aesthetic."""

    WIDTH = 80
    HEIGHT = 24

    def __init__(self) -> None:
        self.lines: list[list[str]] = [[" "] * self.WIDTH for _ in range(self.HEIGHT)]
        self.dirty = True
        self.running = True
        self.input_buf = ""
        self.input_pos = 0
        self.cursor_blink = True
        self.flicker_intensity = 0.02
        self.scanline_offset = 0
        self.boot_complete = False
        self.start_time = time.time()
        self.scrollback: list[str] = []
        self.scrollback_max = 200
        self.active_frame = 0  # animation frame counter

        # Boot sequence state
        self.boot_lines: list[str] = []
        self.boot_index = 0

        # Registered command handlers
        self.handlers: dict[str, callable] = {}

    # ── Low-level rendering ─────────────────────────────────────

    def _set(self, x: int, y: int, char: str) -> None:
        if 0 <= x < self.WIDTH and 0 <= y < self.HEIGHT:
            self.lines[y][x] = char
            self.dirty = True

    def _write_str(self, x: int, y: int, s: str) -> None:
        for i, ch in enumerate(s):
            self._set(x + i, y, ch)

    def _write_centered(self, y: int, s: str) -> None:
        x = max(0, (self.WIDTH - len(s)) // 2)
        self._write_str(x, y, s)

    def _write_right(self, y: int, s: str) -> None:
        x = max(0, self.WIDTH - len(s))
        self._write_str(x, y, s)

    def _box(self, x1: int, y1: int, x2: int, y2: int) -> None:
        """Draw a box from (x1,y1) to (x2,y2) inclusive."""
        self._set(x1, y1, BOX_TL)
        self._set(x2, y1, BOX_TR)
        self._set(x1, y2, BOX_BL)
        self._set(x2, y2, BOX_BR)
        for x in range(x1 + 1, x2):
            self._set(x, y1, BOX_H)
            self._set(x, y2, BOX_H)
        for y in range(y1 + 1, y2):
            self._set(x1, y, BOX_V)
            self._set(x2, y, BOX_V)

    # ── Output ─────────────────────────────────────────────────

    def print(self, text: str, y: int | None = None) -> None:
        """Print text at current cursor position or specified y."""
        if y is None:
            # Find first empty line from top
            y = 0
            while y < self.HEIGHT and any(c != " " for c in self.lines[y]):
                y += 1
        self._write_str(0, y, text[: self.WIDTH].ljust(self.WIDTH))
        self.active_frame += 1

    def print_line(self, text: str) -> None:
        """Append a line at the bottom (scroll if needed)."""
        self.scrollback.append(text)
        if len(self.scrollback) > self.scrollback_max:
            self.scrollback.pop(0)

    def clear_screen(self) -> None:
        self.lines = [[" "] * self.WIDTH for _ in range(self.HEIGHT)]
        self.dirty = True

    def frame(self) -> Generator[None, None, None]:
        """Yield to indicate a frame boundary (for animation)."""
        self.active_frame += 1
        yield

    # ── Render ─────────────────────────────────────────────────

    def _render_amber(self, char: str, x: int, y: int) -> str:
        """Apply amber phosphor glow to a character."""
        if char == " ":
            return " "
        # Subtle flicker based on position and time
        flicker = 0.95 + 0.05 * math.sin(self.active_frame * 0.1 + x * 0.3 + y * 0.2)
        # Scanline dimming (every other row)
        if y % 2 == 0:
            flicker *= 0.85
        brightness = int(200 * flicker)
        r = min(255, int(brightness * 1.0))
        g = min(255, int(brightness * 0.7))
        b = min(255, int(brightness * 0.1))
        return f"\033[38;2;{r};{g};{b}m{char}{RESET}"

    def render(self) -> str:
        """Render the terminal to an ANSI string."""
        out: list[str] = [CLEAR, HIDE_CURSOR, "\r"]

        # Render each character with amber glow
        for y in range(self.HEIGHT):
            line_chars = []
            for x in range(self.WIDTH):
                char = self.lines[y][x]
                if char == " ":
                    # Dim scanline effect for empty spaces in alternating rows
                    if y % 2 == 0:
                        line_chars.append(f"{AMBER_DIM}·{RESET}")
                    else:
                        line_chars.append(" ")
                else:
                    line_chars.append(self._render_amber(char, x, y))
            out.append("".join(line_chars))
            out.append("\r\n")

        return "".join(out[:-1])  # strip final newline

    def render_scrollback(self) -> list[str]:
        """Render scrollback buffer in amber terminal style."""
        result = []
        for line in self.scrollback[-self.HEIGHT + 2 :]:
            result.append(f"{AMBER}{line}{RESET}")
        return result

    # ── Boot sequence ───────────────────────────────────────────

    def boot_sequence(self) -> Generator[str, None, None]:
        """Nostromo terminal boot sequence. Yields ANSI frame strings."""

        boot_text = [
            ("USCSS NOSTROMO", 1.5),
            ("CLASS: MIDNIGHT - UNIT 01", 0.5),
            ("SYSTEM: ANDROID UI v2.7.1", 0.3),
            ("KERNEL: WYLIWYG DISPLAY SYSTEM", 0.3),
            ("COPYRIGHT © 2019 WYLIWYG SYSTEMS LTD", 0.2),
            ("ALL RIGHTS RESERVED", 0.2),
            ("", 0.3),
            ("INITIALIZING MEMORY BANKS", 0.4),
            ("LOADING NEURAL INTERFACE", 0.4),
            ("ESTABLISHING COGNITIVE LINK", 0.4),
            ("AXIOM CORE ONLINE", 0.5),
            ("", 0.3),
            (f"DATE: {datetime.datetime.now().strftime('%Y-%m-%d')}", 0.1),
            (f"TIME: {datetime.datetime.now().strftime('%H:%M:%S')}", 0.1),
            ("", 0.3),
            ("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", 0.1),
            ("  W Y L I W Y G   T E R M I N A L   A C T I V E  ", 0.8),
            ("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", 0.1),
            ("", 0.5),
            ("  AXIOM NEURAL INTERFACE v2.7.1", 0.3),
            ("  COGNITIVE SYNC: NOMINAL", 0.3),
            ("  MEMORY BANKS: 100%", 0.3),
            ("  NEURAL LINK: ESTABLISHED", 0.3),
            ("", 0.5),
        ]

        for text, delay in boot_text:
            self._write_str(0, 0, "")
            self.clear_screen()
            self._write_centered(5, f"{AMBER_BRIGHT}{BOLD}{text}{RESET}")
            yield self.render()
            time.sleep(delay)

        self.clear_screen()
        yield self.render()
        self.boot_complete = True

    # ── Status bar ─────────────────────────────────────────────

    def render_status_bar(self, status_text: str = "") -> None:
        """Render top and bottom status bars."""
        now = datetime.datetime.now()
        time_str = now.strftime("%H:%M:%S")

        # Top bar
        self._set(0, 0, " ")
        top = f" NOSTROMO TERMINAL | AXIOM v2.7.1 | {time_str} | {status_text}"
        self._write_str(0, 0, top[: self.WIDTH].ljust(self.WIDTH))

        # Bottom bar
        bottom = f" {AMBER_DIM}│{RESET} {self.input_buf[:self.WIDTH-4]}"
        remaining = self.WIDTH - 2 - len(self.input_buf[:self.WIDTH-4])
        if self.cursor_blink:
            bottom += f"{AMBER_BRIGHT}█{RESET}"
            remaining -= 1
        bottom += " " * remaining
        self._write_str(0, self.HEIGHT - 1, bottom)


# ── Main Terminal Application ─────────────────────────────────────

class NostromoTerminal:
    """Full terminal application with Alien aesthetic."""

    def __init__(self) -> None:
        self.term = AlienTerminal()
        self.agent_loop_thread: threading.Thread | None = None
        self.agent_ready = threading.Event()
        self.agent_error: str | None = None
        self.shutdown = threading.Event()

        # Core components (set by init_agent)
        self.agent: "Agent" | None = None
        self.conversation_db: "ConversationDB" | None = None
        self.dag: "DAGSummaryGraph" | None = None
        self.ltm: "LongTermMemory" | None = None
        self.memory_extractor: "MemoryExtractor" | None = None
        self.context_assembler: "ContextAssembler" | None = None
        self.self_model: "SelfModel" | None = None
        self.current_user: str = "global"
        self.current_session: str = "main"

    # ── Init ───────────────────────────────────────────────────

    def init_agent(self) -> None:
        """Load all xiaomei-brain components in background thread."""
        try:
            import os
            import sys

            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

            from xiaomei_brain.memory.conversation_db import ConversationDB
            from xiaomei_brain.memory.dag import DAGSummaryGraph
            from xiaomei_brain.memory.extractor import MemoryExtractor
            from xiaomei_brain.memory.longterm import LongTermMemory
            from xiaomei_brain.memory.self_model import SelfModel
            from xiaomei_brain.memory.context_assembler import ContextAssembler, determine_mode
            from xiaomei_brain.tools.registry import ToolRegistry
            from xiaomei_brain.tools.builtin.dag_expand import create_dag_tools
            from xiaomei_brain.agent.core import Agent
            from xiaomei_brain.llm import LLMClient
            from xiaomei_brain.config import Config

            config = Config.from_json()
            llm = LLMClient(config.model, config.api_key, config.base_url, config.provider)

            base = os.path.expanduser("~/.xiaomei-brain/agents/xiaomei")
            db_path = os.path.join(base, "memory", "brain.db")
            os.makedirs(os.path.dirname(db_path), exist_ok=True)

            self.self_model = SelfModel.load(os.path.join(base, "talent.md"))
            self.conversation_db = ConversationDB(db_path)
            self.dag = DAGSummaryGraph(db_path, llm_client=llm)
            self.ltm = LongTermMemory(db_path)
            self.memory_extractor = MemoryExtractor(llm, self.ltm, self.conversation_db)
            self.context_assembler = ContextAssembler(
                self.conversation_db, self.dag, self.self_model, self.ltm
            )

            tools = ToolRegistry()
            for dag_tool in create_dag_tools(self.dag, self.ltm):
                tools.register(dag_tool)

            self.agent = Agent(
                llm=llm,
                tools=tools,
                system_prompt="",
                max_steps=10,
            )
            self.agent.self_model = self.self_model
            self.agent.conversation_db = self.conversation_db
            self.agent.context_assembler = self.context_assembler
            self.agent.longterm_memory = self.ltm
            self.agent.memory_extractor = self.memory_extractor
            self.agent.user_id = self.current_user

        except Exception as e:
            import traceback

            self.agent_error = f"INIT ERROR: {e}\n{traceback.format_exc()}"
            sys.stderr.write(self.agent_error)

        finally:
            self.agent_ready.set()

    # ── Command handlers ────────────────────────────────────────

    def handle_input(self, raw: str) -> str | None:
        """Handle user input. Returns output string or None."""
        cmd = raw.strip()

        if not cmd:
            return None

        # Built-in terminal commands
        if cmd in ("q", "quit", "exit"):
            return "SHUTTING DOWN..."

        if cmd == "help":
            return self._help_text()

        if cmd == "db":
            return self._cmd_db()

        if cmd == "memory":
            return self._cmd_memory()

        if cmd == "status":
            return self._cmd_status()

        if cmd == "clear":
            self.term.scrollback.clear()
            return None

        if cmd.startswith("user "):
            new_user = cmd[5:].strip()
            old = self.current_user
            self.current_user = new_user
            if self.agent:
                self.agent.user_id = new_user
            return f"USER CONTEXT SWITCHED: {old} → {new_user}"

        if cmd.startswith("dag "):
            keyword = cmd[4:].strip()
            return self._cmd_dag(keyword)

        if cmd.startswith("expand "):
            keyword = cmd[7:].strip()
            return self._cmd_expand(keyword)

        if cmd == "summarize":
            return self._cmd_summarize()

        if cmd == "dream":
            return self._cmd_dream()

        if cmd == "periodic":
            return self._cmd_periodic()

        # Normal chat — pass to agent
        if not self.agent_ready.is_set():
            return "[SYSTEM NOT READY]"

        try:
            # Import here to avoid top-level import before agent path setup
            from xiaomei_brain.memory.context_assembler import determine_mode
            mode = determine_mode(cmd)
            response_chunks: list[str] = []
            for chunk in self.agent.stream(cmd):
                response_chunks.append(chunk)
            return "".join(response_chunks)
        except Exception as e:
            import traceback

            return f"[ERROR] {e}\n{traceback.format_exc()[:200]}"

    def _help_text(self) -> str:
        return """
AVAILABLE COMMANDS:
  help          Show this help
  db            Memory statistics
  memory        Show recent memories
  status        System status
  clear         Clear scrollback
  user <name>   Switch user context
  dag <keyword> Search DAG summaries
  expand <kw>   Expand DAG summary to originals
  summarize     Trigger DAG compression
  dream         Dream extraction
  periodic      Periodic extraction
  exit / q      Shutdown terminal
""".strip()

    def _cmd_db(self) -> str:
        if not self.conversation_db:
            return "(DB not ready)"
        conn = self.dag._get_conn() if self.dag else None
        msgs = self.conversation_db.count()
        sums = conn.execute("SELECT COUNT(*) FROM summaries").fetchone()[0] if conn else 0
        mems = self.ltm.count(self.current_user) if self.ltm else 0
        tags = self.ltm.get_all_tags() if self.ltm else []
        return f"MESSAGES: {msgs} | SUMMARIES: {sums} | MEMORIES: {mems} | TAGS: {tags}"

    def _cmd_memory(self) -> str:
        if not self.ltm:
            return "(Memory not ready)"
        rows = self.ltm.get_recent(5, user_id=self.current_user)
        if not rows:
            return "(No memories)"
        lines = []
        for r in rows:
            lines.append(f"  [{r['source']}] {r['content'][:60]}")
        return "\n".join(lines)

    def _cmd_status(self) -> str:
        state = "READY" if self.agent_ready.is_set() else "LOADING"
        mem_count = self.ltm.count(self.current_user) if self.ltm else 0
        conn = self.dag._get_conn() if self.dag else None
        sum_count = conn.execute("SELECT COUNT(*) FROM summaries").fetchone()[0] if conn else 0
        return f"AXIOM STATE: {state} | USER: {self.current_user} | MEMORIES: {mem_count} | SUMMARIES: {sum_count}"

    def _cmd_dag(self, keyword: str) -> str:
        if not self.dag or not keyword:
            return "(Usage: dag <keyword>)"
        nodes = self.dag.search(keyword, limit=5)
        if not nodes:
            return f"No summaries found for: {keyword}"
        lines = []
        for n in nodes:
            lines.append(f"  #{n.id} [depth={n.depth}]: {n.content[:70]}...")
        return "\n".join(lines)

    def _cmd_expand(self, keyword: str) -> str:
        if not self.dag or not keyword:
            return "(Usage: expand <keyword>)"
        nodes = self.dag.search(keyword, limit=3)
        if not nodes:
            return f"No summaries found for: {keyword}"
        lines = []
        for node in nodes:
            lines.append(f"─── SUMMARY #{node.id} (depth={node.depth}) ───")
            lines.append(node.content[:100])
            originals = self.dag.expand(node.id)
            lines.append("  → Original messages:")
            for o in originals:
                role = o.get("role", "?")
                content = str(o.get("content", ""))[:80]
                lines.append(f"    [{role}] {content}")
        return "\n".join(lines)

    def _cmd_summarize(self) -> str:
        if not self.dag or not self.conversation_db:
            return "(DAG not ready)"
        msgs = self.conversation_db.get_recent(8, session_id=self.current_session)
        if not msgs:
            return "(No messages to summarize)"
        node = self.dag.compact(self.current_session, [m["id"] for m in msgs], msgs)
        if node:
            return f"SUMMARY CREATED: id={node.id} depth={node.depth} tokens={node.token_count}"
        return "Summarization failed"

    def _cmd_dream(self) -> str:
        if not self.memory_extractor:
            return "(Extractor not ready)"
        ids = self.memory_extractor.extract_dream(user_id=self.current_user)
        return f"[DREAM] Extracted {len(ids)} memories"

    def _cmd_periodic(self) -> str:
        if not self.memory_extractor:
            return "(Extractor not ready)"
        ids = self.memory_extractor.extract_periodic(interval_minutes=0, user_id=self.current_user)
        return f"[PERIODIC] Extracted {len(ids)} memories"

    # ── Render loop ────────────────────────────────────────────

    def render_screen(self) -> str:
        """Render the full terminal screen."""
        self.term.clear_screen()

        # Top status bar
        status = "NOMINAL" if self.agent_ready.is_set() else "INITIALIZING"
        self.term.render_status_bar(status)

        # Main content area
        content_lines = self.term.scrollback[-self.term.HEIGHT + 4 :]
        y = 2
        for line in content_lines:
            # Colorize command prompts
            if line.startswith(">"):
                colored = f"{AMBER_BRIGHT}{BOLD}{line}{RESET}"
            elif line.startswith("[ERROR]"):
                colored = f"{RED}{line}{RESET}"
            elif "MEMORY" in line or "SUMMARY" in line:
                colored = f"{GREEN}{line}{RESET}"
            else:
                colored = f"{AMBER}{line}{RESET}"
            self.term._write_str(0, y, colored[: self.term.WIDTH].ljust(self.term.WIDTH))
            y += 1
            if y >= self.term.HEIGHT - 1:
                break

        # Box around content
        self.term._box(0, 1, self.term.WIDTH - 1, self.term.HEIGHT - 2)

        return self.term.render()

    def render_boot(self) -> Generator[str, None, None]:
        """Render boot sequence."""
        for frame in self.term.boot_sequence():
            yield frame

    # ── Run ───────────────────────────────────────────────────

    def run(self) -> None:
        """Main run loop."""
        # Start agent init in background
        init_thread = threading.Thread(target=self.init_agent, daemon=True)
        init_thread.start()

        # Print boot sequence frames
        sys.stdout.write(CLEAR)
        for frame in self.render_boot():
            sys.stdout.write(frame)
            sys.stdout.flush()

        # Main loop
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.flush()

        prompt = f"{AMBER_BRIGHT}>{RESET} "

        try:
            while not self.shutdown.is_set():
                # Print prompt
                sys.stdout.write(f"\r\n{prompt}")
                sys.stdout.flush()

                # Read input line
                line = sys.stdin.readline()
                if not line:  # EOF
                    break

                raw = line.rstrip("\n\r")

                # Handle command
                output = self.handle_input(raw)

                if output == "SHUTTING DOWN...":
                    self._shutdown()
                    break

                if output:
                    # Print output with amber styling
                    for out_line in output.split("\n"):
                        sys.stdout.write(f"\r\n{AMBER}{out_line}{RESET}\r\n")
                    sys.stdout.flush()

                # Blink cursor
                self.term.cursor_blink = not self.term.cursor_blink

        except KeyboardInterrupt:
            self._shutdown()

        sys.stdout.write(f"\r\n{AMBER}TERMINAL OFFLINE{RESET}\r\n")
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.flush()

    def _shutdown(self) -> None:
        self.shutdown.set()
        if self.conversation_db:
            self.conversation_db.close()
        if self.ltm:
            self.ltm.close()


def main() -> None:
    print(CLEAR, end="")
    print(HIDE_CURSOR, end="")
    term = NostromoTerminal()

    # Graceful shutdown on SIGINT/SIGTERM
    def shutdown_handler(signum, frame):
        sys.stdout.write("\r\n")
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.flush()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    term.run()


if __name__ == "__main__":
    main()
