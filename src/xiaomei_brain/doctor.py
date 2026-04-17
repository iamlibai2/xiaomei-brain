"""Lightweight system health check for xiaomei-brain."""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from . import Config


class Status(Enum):
    OK = "ok"
    FAIL = "fail"
    SKIP = "skip"
    WARN = "warn"


@dataclass
class Check:
    name: str
    status: Status
    message: str = ""
    detail: str = ""

    def is_pass(self) -> bool:
        return self.status in (Status.OK, Status.SKIP)


@dataclass
class Section:
    title: str
    checks: list[Check] = None
    def __post_init__(self):
        self.checks = self.checks or []


class Doctor:
    def __init__(self, config: Config | None = None, verbose: bool = False):
        self.config = config or Config.from_json()
        self.verbose = verbose
        self.sections: list[Section] = []

    # ── Check helpers ──────────────────────────────────────────────

    def _ok(self, name: str, msg: str = "") -> Check:
        return Check(name=name, status=Status.OK, message=msg)

    def _fail(self, name: str, msg: str, detail: str = "") -> Check:
        return Check(name=name, status=Status.FAIL, message=msg, detail=detail)

    def _warn(self, name: str, msg: str, detail: str = "") -> Check:
        return Check(name=name, status=Status.WARN, message=msg, detail=detail)

    def _skip(self, name: str, msg: str = "") -> Check:
        return Check(name=name, status=Status.SKIP, message=msg)

    # ── Individual checks ────────────────────────────────────────────

    def check_config(self) -> Section:
        sec = Section("Config")
        cfg = self.config

        if not cfg.api_key:
            sec.checks.append(self._fail(
                "api_key",
                "API key not configured",
                "Set api_key in config.json or via environment variable",
            ))
        else:
            sec.checks.append(self._ok("api_key", "configured"))

        if not cfg.base_url:
            sec.checks.append(self._fail("base_url", "base_url not set"))
        else:
            sec.checks.append(self._ok("base_url", cfg.base_url))

        if not cfg.model:
            sec.checks.append(self._fail("model", "model not set"))
        else:
            sec.checks.append(self._ok("model", cfg.model))

        return sec

    def check_provider_connectivity(self) -> Section:
        sec = Section("Provider")
        cfg = self.config

        if not cfg.api_key or not cfg.base_url:
            sec.checks.append(self._skip("connectivity", "api_key or base_url missing"))
            return sec

        try:
            import requests
            resp = requests.post(
                f"{cfg.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {cfg.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": cfg.model,
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 5,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                sec.checks.append(self._ok("connectivity", f"status {resp.status_code}"))
            elif resp.status_code == 401:
                sec.checks.append(self._fail(
                    "connectivity",
                    f"authentication failed ({resp.status_code})",
                    "check api_key is valid",
                ))
            elif resp.status_code == 429:
                sec.checks.append(self._warn(
                    "connectivity",
                    f"rate limited ({resp.status_code})",
                    "quota may be exhausted",
                ))
            else:
                sec.checks.append(self._fail(
                    "connectivity",
                    f"unexpected status {resp.status_code}",
                    resp.text[:200],
                ))
        except Exception as e:
            sec.checks.append(self._fail("connectivity", "connection failed", str(e)))

        return sec

    def check_tts(self) -> Section:
        sec = Section("TTS")
        cfg = self.config

        if not cfg.tts_enabled:
            sec.checks.append(self._skip("tts", "disabled"))
            return sec

        if not cfg.tts_api_key:
            sec.checks.append(self._fail("tts_api_key", "tts enabled but api_key missing"))
        else:
            sec.checks.append(self._ok("tts_api_key", "configured"))

        try:
            import requests
            resp = requests.post(
                f"{cfg.tts_base_url}/v1/t2a_v2",
                headers={"Authorization": f"Bearer {cfg.tts_api_key}"},
                json={
                    "model": "speech-2.8-hd",
                    "text": "hello",
                    "stream": True,
                },
                timeout=15,
                stream=True,
            )
            if resp.status_code in (200, 401):
                if resp.status_code == 401:
                    sec.checks.append(self._fail("tts_connectivity", f"auth failed ({resp.status_code})"))
                else:
                    sec.checks.append(self._ok("tts_connectivity", f"status {resp.status_code}"))
            else:
                sec.checks.append(self._fail("tts_connectivity", f"status {resp.status_code}"))
        except Exception as e:
            sec.checks.append(self._fail("tts_connectivity", "connection failed", str(e)))

        return sec

    def check_web_search(self) -> Section:
        sec = Section("Web Search")
        cfg = self.config

        if not cfg.web_search_enabled:
            sec.checks.append(self._skip("web_search", "disabled"))
            return sec

        if not cfg.baidu_api_key:
            sec.checks.append(self._fail("baidu_api_key", "web_search enabled but key missing"))
        else:
            sec.checks.append(self._ok("baidu_api_key", "configured"))

        try:
            from .websearch import BaiduSearchProvider
            provider = BaiduSearchProvider(api_key=cfg.baidu_api_key)
            results = provider.search(query="test", count=1)
            if results:
                sec.checks.append(self._ok("baidu_search", f"{len(results)} result(s)"))
            else:
                sec.checks.append(self._warn("baidu_search", "no results returned"))
        except Exception as e:
            sec.checks.append(self._fail("baidu_search", "search failed", str(e)))

        return sec

    def check_web_get(self) -> Section:
        sec = Section("Web Get")
        cfg = self.config

        if not cfg.web_get_enabled:
            sec.checks.append(self._skip("web_get", "disabled"))
            return sec

        try:
            from .webget import WebGetProvider
            provider = WebGetProvider()
            result = provider.fetch("https://www.baidu.com", extract_mode="text", max_chars=500)
            if result.status == 200:
                sec.checks.append(self._ok("web_get", f"status {result.status}, {len(result.text)} chars"))
            else:
                sec.checks.append(self._fail("web_get", f"status {result.status}"))
        except Exception as e:
            sec.checks.append(self._fail("web_get", "fetch failed", str(e)))

        return sec

    def check_memory_dir(self) -> Section:
        sec = Section("Memory")
        cfg = self.config
        mem_dir = Path(cfg.memory_dir).expanduser()

        if mem_dir.exists():
            if os.access(mem_dir, os.W_OK):
                topics = list(mem_dir.glob("topics/*.md"))
                sec.checks.append(self._ok("memory_dir", f"{mem_dir} ({len(topics)} topics)"))
            else:
                sec.checks.append(self._fail("memory_dir", "not writable"))
        else:
            sec.checks.append(self._warn("memory_dir", f"{mem_dir} does not exist yet", "will be created on first use"))
            return sec

        # Check embedding model
        try:
            from .memory import MemoryStore
            store = MemoryStore(memory_dir=str(mem_dir))
            vec = store.embedder.embed("hello")
            sec.checks.append(self._ok("embedding", f"{len(vec)}-dim vector"))
        except ImportError:
            sec.checks.append(self._skip("embedding", "sentence_transformers not installed"))
        except Exception as e:
            sec.checks.append(self._fail("embedding", "model failed to load", str(e)))

        return sec

    def check_sessions_dir(self) -> Section:
        sec = Section("Sessions")
        cfg = self.config
        from xiaomei_brain.session import SessionManager
        sm = SessionManager(session_dir=cfg.memory_dir)
        sessions = sm.list_sessions()
        sec.checks.append(self._ok("sessions", f"{len(sessions)} saved session(s)"))
        return sec

    # ── Run all checks ──────────────────────────────────────────────

    def run(self) -> bool:
        all_checks = [
            self.check_config,
            self.check_provider_connectivity,
            self.check_tts,
            self.check_web_search,
            self.check_web_get,
            self.check_memory_dir,
            self.check_sessions_dir,
        ]

        for check_fn in all_checks:
            self.sections.append(check_fn())

        return all(c.is_pass() for s in self.sections for c in s.checks)

    # ── Output ──────────────────────────────────────────────────────

    SYMBOLS = {
        Status.OK:   "✓",
        Status.FAIL: "✗",
        Status.SKIP: "·",
        Status.WARN: "!",
    }

    def _color(self, status: Status, text: str) -> str:
        # Simple ANSI color codes, no external deps
        codes = {
            Status.OK:   "32",   # green
            Status.FAIL: "31",   # red
            Status.SKIP: "90",   # bright black
            Status.WARN: "33",   # yellow
        }
        return f"\033[{codes[status]}m{text}\033[0m"

    def _indent(self, text: str, width: int = 28) -> str:
        lines = text.splitlines()
        if len(lines) <= 1:
            return text.rjust(width)
        first, rest = lines[0], lines[1:]
        pad = " " * width
        return first.rjust(width) + "\n" + "\n".join(pad + r for r in rest)

    def _detail(self, text: str, width: int = 28) -> str:
        if not text:
            return ""
        prefix = " " * (width + 2)
        lines = text.splitlines()
        return "\n".join(prefix + l for l in lines)

    def print_report(self) -> None:
        border = "─" * 60
        title = f" xiaomei-brain doctor "
        header = f"\n{'─' * 28}{title}{'─' * (60 - 28 - len(title))}\n"

        print(header)
        all_pass = True

        for sec in self.sections:
            print(f"  {sec.title}")
            for check in sec.checks:
                sym = self.SYMBOLS[check.status]
                label = f"{self._color(check.status, sym)}  {check.name}"
                msg = check.message or ""
                print(f"    {label}  {msg}")
                if check.detail and self.verbose:
                    print(self._detail(check.detail))
                if check.status == Status.FAIL:
                    all_pass = False
            print()

        # Summary
        total = sum(len(s.checks) for s in self.sections)
        failed = sum(1 for s in self.sections for c in s.checks if c.status == Status.FAIL)
        warned = sum(1 for s in self.sections for c in s.checks if c.status == Status.WARN)
        passed = total - failed - warned

        summary = (
            f"  {self._color(Status.OK, '✓')} {passed} passed"
            + (f"  {self._color(Status.WARN, '!')} {warned} warnings" if warned else "")
            + (f"  {self._color(Status.FAIL, '✗')} {failed} failed" if failed else "")
        )
        print(f"  {border}")
        print(summary)
        print()

        if all_pass:
            print(f"  {self._color(Status.OK, '✓ All checks passed')}\n")
        else:
            print(f"  {self._color(Status.FAIL, '✗ Some checks failed — run with --fix for details')}\n")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="xiaomei-brain health check")
    parser.add_argument("--fix", action="store_true", help="auto-fix where possible")
    parser.add_argument("-v", "--verbose", action="store_true", help="show detail on failure")
    args = parser.parse_args()

    doctor = Doctor(verbose=args.verbose)
    doctor.run()
    doctor.print_report()


if __name__ == "__main__":
    main()
