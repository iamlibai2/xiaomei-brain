"""Core Agent implementation with ReAct loop and new memory architecture."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Generator

from xiaomei_brain.llm import LLMClient
from xiaomei_brain.memory.conversation_db import ConversationDB
from xiaomei_brain.memory.self_model import SelfModel
from xiaomei_brain.memory.context_assembler import ContextAssembler, determine_mode
from xiaomei_brain.memory.longterm import LongTermMemory
from xiaomei_brain.memory.extractor import MemoryExtractor
from xiaomei_brain.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class Agent:
    """An AI Agent that reasons and acts via ReAct loop.

    Memory architecture:
    - ContextAssembler + DAG + LongTermMemory + ConversationDB
    - Context is assembled from DB each turn, self.messages only tracks current ReAct loop.
    """

    def __init__(
        self,
        llm: LLMClient,
        tools: ToolRegistry,
        system_prompt: str = "You are a helpful assistant.",
        max_steps: int = 10,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.system_prompt = system_prompt
        self.max_steps = max_steps

        # ── New memory architecture ──────────────────────
        self.self_model: SelfModel | None = None
        self.conversation_db: ConversationDB | None = None
        self.context_assembler: ContextAssembler | None = None
        self.longterm_memory: LongTermMemory | None = None
        self.memory_extractor: MemoryExtractor | None = None

        self.messages: list[dict[str, Any]] = []
        self.user_id: str = "global"

    def run(self, user_input: str) -> str:
        """Run the agent and return the final response (non-streaming)."""
        chunks = list(self.stream(user_input))
        return "".join(chunks)

    def stream(self, user_input: str) -> Generator[str, None, None]:
        """Run the agent with streaming output.

        Yields text chunks as the LLM generates them.
        Tool calls are handled transparently; only final text is yielded.
        """
        # self.messages tracks current ReAct loop's intermediate steps
        # (assistant tool_calls + tool results). User message is NOT included
        # here because ContextAssembler._fresh_tail() reads it from DB.
        self.messages = []

        # Log user message to DB immediately so _fresh_tail() can pick it up
        if self.conversation_db:
            self.conversation_db.log(
                session_id=self._current_session_id(),
                role="user",
                content=user_input,
            )

        # Determine operational mode
        mode = determine_mode(user_input)

        openai_tools = self.tools.to_openai_tools() if self.tools.list_tools() else None

        # Base context: assembled once at the start (system + DAG + memories + recent tail)
        base_context = self.context_assembler.assemble(
            user_input=user_input,
            max_tokens=4000,
            mode=mode,
            session_id=self._current_session_id(),
            user_id=self.user_id,
        )

        for step in range(self.max_steps):
            # Reuse base context + append current ReAct loop messages
            all_messages = list(base_context) + self.messages

            # Clean surrogate characters from all message content before sending to LLM
            all_messages = self._clean_messages(all_messages)

            logger.debug("Step %d: calling LLM", step + 1)

            response, stream_chunks = self._call_llm(all_messages, openai_tools)

            if response.has_tool_calls:
                self.messages.append(
                    {
                        "role": "assistant",
                        "content": response.content,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments),
                                },
                            }
                            for tc in response.tool_calls
                        ],
                    }
                )

                for tc in response.tool_calls:
                    logger.info("Tool call: %s(%s)", tc.name, tc.arguments)
                    try:
                        result = self.tools.execute(tc.name, **tc.arguments)
                    except Exception as e:
                        result = f"Error executing tool '{tc.name}': {e}"
                        logger.error("Tool error: %s", e)

                    logger.info("Tool result: %s", result[:200])

                    if self.conversation_db:
                        self.conversation_db.log(
                            session_id=self._current_session_id(),
                            role="tool",
                            content=result,
                            tool_name=tc.name,
                            tool_call_id=tc.id,
                        )
                        # Procedure memory: record tool invocation (no LLM call)
                        self.conversation_db.store_tool(
                            tool_name=tc.name,
                            args=tc.arguments,
                            result=str(result)[:500],
                            user_id=self.user_id,
                            session_id=self._current_session_id(),
                        )
                    self.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        }
                    )
            else:
                content = response.content or ""
                if content:
                    self.messages.append({"role": "assistant", "content": content})

                    if self.conversation_db:
                        self.conversation_db.log(
                            session_id=self._current_session_id(),
                            role="assistant",
                            content=content,
                        )

                    # Stream the response
                    if stream_chunks:
                        yield from stream_chunks
                    else:
                        yield content

                    return
                else:
                    logger.warning("LLM returned empty content with no tool calls")
                    yield ""
                    return

        yield "Agent reached maximum steps without producing a final answer."

    # ── LLM calling ──────────────────────────────────────────────

    def _call_llm(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> tuple[Any, list[str] | None]:
        """Call LLM with streaming support."""
        try:
            return self._call_llm_streaming(messages, tools)
        except Exception as e:
            logger.debug("Streaming not available, falling back: %s", e)
            response = self.llm.chat(messages=messages, tools=tools)
            return response, None

    def _call_llm_streaming(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> tuple[Any, list[str] | None]:
        """Call LLM using streaming API."""
        import requests as req

        api_messages = self.llm._build_messages(messages)

        payload = {
            "model": self.llm.model,
            "messages": api_messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        headers = {
            "Authorization": f"Bearer {self.llm.api_key}",
            "Content-Type": "application/json",
        }

        import datetime as _dt
        _t0 = time.time()
        _msg_preview = (api_messages[0].get("content") or "")[:40] if api_messages else ""
        _has_tools = bool(tools)

        def _log(success: bool, detail: str = ""):
            elapsed = time.time() - _t0
            status = "OK" if success else "ERR"
            ts = _dt.datetime.now().strftime("%H:%M:%S")
            logger.info(
                "[LLM %s STREAM] %s model=%s msgs=%d tools=%s elapsed=%.2fs %s %s",
                status, ts, self.llm.model, len(api_messages), _has_tools, elapsed, _msg_preview, detail,
            )

        response = req.post(
            f"{self.llm.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
            stream=True,
        )
        response.raise_for_status()

        # Parse SSE stream
        content_parts = []
        stream_parts = []  # filtered parts for streaming output (no thinking)
        tool_calls_acc: dict[int, dict] = {}
        finish_reason = ""
        in_think = False  # track <think> blocks across chunks

        try:
            for line in response.iter_lines():
                if not line:
                    continue
                if isinstance(line, bytes):
                    try:
                        line = line.decode("utf-8")
                    except UnicodeDecodeError:
                        line = line.decode("utf-8", errors="replace")
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break

                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue

                choice = chunk.get("choices", [{}])[0]
                delta = choice.get("delta", {})
                finish_reason = choice.get("finish_reason", "") or finish_reason

                if "content" in delta and delta["content"] and not delta.get("reasoning_content"):
                    content_parts.append(delta["content"])
                    # Filter <think> blocks for streaming output
                    text = delta["content"]
                    if in_think:
                        end_idx = text.find("</think>")
                        if end_idx != -1:
                            in_think = False
                            text = text[end_idx + 8:]
                        else:
                            text = ""
                    if not in_think:
                        start_idx = text.find("<think")
                        if start_idx != -1:
                            end_idx = text.find("</think>", start_idx)
                            if end_idx != -1:
                                text = text[:start_idx] + text[end_idx + 8:]
                            else:
                                text = text[:start_idx]
                                in_think = True
                    if text:
                        stream_parts.append(text)

                if "tool_calls" in delta:
                    for tc_delta in delta["tool_calls"]:
                        idx = tc_delta.get("index", 0)
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": "",
                                "name": "",
                                "arguments": "",
                            }
                        if tc_delta.get("id"):
                            tool_calls_acc[idx]["id"] = tc_delta["id"]
                        fn = tc_delta.get("function", {})
                        if fn.get("name"):
                            tool_calls_acc[idx]["name"] = fn["name"]
                        if fn.get("arguments"):
                            tool_calls_acc[idx]["arguments"] += fn["arguments"]
        except Exception as e:
            _log(False, f"stream_err:{e}")
            raise

        # Build final ChatResponse
        from xiaomei_brain.llm import ChatResponse, ToolCall

        content = self.llm._strip_thinking("".join(content_parts))
        # Clean surrogate characters from LLM output
        try:
            content = content.encode("utf-8", "surrogatepass").decode("utf-8", "replace")
        except Exception:
            pass
        tool_calls = []
        for idx in sorted(tool_calls_acc):
            tc = tool_calls_acc[idx]
            try:
                args = json.loads(tc["arguments"]) if tc["arguments"] else {}
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=tc["id"], name=tc["name"], arguments=args))

        chat_response = ChatResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
        )

        _log(True)
        return chat_response, stream_parts if not tool_calls else None

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _clean_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Clean surrogate characters from message content."""
        cleaned = []
        for m in messages:
            m = dict(m)  # shallow copy
            content = m.get("content")
            if isinstance(content, str):
                try:
                    content = content.encode("utf-8", "surrogatepass").decode("utf-8", "replace")
                except Exception:
                    pass
                m["content"] = content
            cleaned.append(m)
        return cleaned

    def load_self_model(self, talent_path: str) -> None:
        """Load SelfModel from talent.md at startup."""
        self.self_model = SelfModel.load(talent_path)
        if self.self_model and self.self_model.purpose_seed.identity:
            logger.info("SelfModel loaded: %s", self.self_model.purpose_seed.identity[:50])
        elif self.self_model and self.self_model.seed_text:
            logger.info("SelfModel loaded (legacy format)")

    def save_self_model(self, talent_path: str) -> None:
        """Save SelfModel to talent.md at shutdown."""
        if self.self_model:
            self.self_model.save(talent_path)

    def _current_session_id(self) -> str:
        """Get current session identifier for ConversationDB."""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d")
