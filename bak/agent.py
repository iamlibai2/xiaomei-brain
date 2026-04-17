"""Core Agent implementation with ReAct loop, context management, and dream system."""

from __future__ import annotations

import json
import logging
from typing import Any, Generator

from .config import Config
from .context import ContextManager
from .context_extractor import ContextExtractor
from .llm import LLMClient
from .memory.store import MemoryStore
from .memory.conversation import ConversationLogger
from .memory.dream import DreamProcessor
from .memory.episodic import EpisodicMemory
from .memory.layers import WorkingMemory, WorkingMemoryItem
from .memory.scheduler import DreamScheduler
from .proactive import ProactiveEngine, ProactiveMessage
from .reminder import ReminderManager
from .session import SessionManager
from .tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class Agent:
    """An AI Agent that reasons, acts, and dreams.

    Implements the ReAct (Reason-Act-Observe) loop:
    1. Send user input + conversation history to LLM
    2. If LLM requests tool calls → execute tools → feed results back → repeat
    3. If LLM returns text → return to user

    Features:
    - Context window management (sliding window + summarization)
    - Streaming output support
    - Dream system for offline memory extraction
    """

    def __init__(
        self,
        llm: LLMClient,
        tools: ToolRegistry,
        system_prompt: str = "You are a helpful assistant.",
        max_steps: int = 10,
        memory: MemoryStore | None = None,
        conversation_logger: ConversationLogger | None = None,
        dream_scheduler: DreamScheduler | None = None,
        context_manager: ContextManager | None = None,
        episodic_memory: EpisodicMemory | None = None,
        proactive_engine: ProactiveEngine | None = None,
        reminder_manager: ReminderManager | None = None,
        context_max_tokens: int = 4000,
        context_recent_turns: int = 6,
        context_extractor: ContextExtractor | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        self.memory = memory
        self.conversation_logger = conversation_logger
        self.dream_scheduler = dream_scheduler
        self.episodic_memory = episodic_memory
        self.proactive_engine = proactive_engine
        self.reminder_manager = reminder_manager
        self.working_memory = WorkingMemory()
        self.messages: list[dict[str, Any]] = []

        # Context management: auto-create if not provided
        self.context = context_manager or ContextManager(
            max_tokens=context_max_tokens,
            recent_turns=context_recent_turns,
            llm_client=llm,
        )

        # Background context extractor (unified reminder + working memory extraction)
        self.context_extractor = context_extractor

    def run(self, user_input: str) -> str:
        """Run the agent and return the final response (non-streaming).

        Args:
            user_input: The user's message.

        Returns:
            The agent's final text response.
        """
        chunks = list(self.stream(user_input))
        return "".join(chunks)

    def stream(self, user_input: str) -> Generator[str, None, None]:
        """Run the agent with streaming output.

        Yields text chunks as the LLM generates them.
        Tool calls are handled transparently; only final text is yielded.

        Args:
            user_input: The user's message.

        Yields:
            Text chunks of the final response.
        """
        self.messages.append({"role": "user", "content": user_input})

        # Log conversation turn
        if self.conversation_logger:
            self.conversation_logger.log("user", user_input)

        # Notify scheduler of activity
        if self.dream_scheduler:
            self.dream_scheduler.touch()

        # Notify proactive engine of activity
        if self.proactive_engine:
            self.proactive_engine.touch()

        # Fast pattern-based reminder extraction (non-blocking)
        if self.reminder_manager:
            new_reminders = self.reminder_manager.extract_from_message(user_input, use_llm=False)
            if new_reminders:
                logger.info("Extracted %d reminders from message", len(new_reminders))

        # Check for due reminders and inject into system prompt context
        due_reminders = []
        if self.reminder_manager:
            due_reminders = self.reminder_manager.check_due()

        # Build effective system prompt with memory
        effective_prompt = self._build_effective_prompt(user_input)

        openai_tools = self.tools.to_openai_tools() if self.tools.list_tools() else None

        for step in range(self.max_steps):
            # Build full message list and compress if needed
            all_messages = [{"role": "system", "content": effective_prompt}] + self.messages
            all_messages = self._manage_context(all_messages)

            logger.debug("Step %d: calling LLM", step + 1)

            # Try streaming first, fall back to non-streaming
            response, stream_chunks = self._call_llm(all_messages, openai_tools)

            if response.has_tool_calls:
                # Process tool calls
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

                # Execute each tool call
                for tc in response.tool_calls:
                    logger.info("Tool call: %s(%s)", tc.name, tc.arguments)
                    try:
                        result = self.tools.execute(tc.name, **tc.arguments)
                    except Exception as e:
                        result = f"Error executing tool '{tc.name}': {e}"
                        logger.error("Tool error: %s", e)

                    logger.info("Tool result: %s", result[:200])
                    self.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        }
                    )
            else:
                # LLM returned final text response
                content = response.content or ""
                if content:
                    self.messages.append({"role": "assistant", "content": content})

                    # Log assistant response
                    if self.conversation_logger:
                        self.conversation_logger.log("assistant", content)

                    # Stream the response
                    if stream_chunks:
                        yield from stream_chunks
                    else:
                        yield content

                    # Update working memory from this turn (background, non-blocking)
                    if self.context_extractor:
                        self.context_extractor.add_turn(user_input, content)
                    else:
                        # Fallback to fast heuristic if no context extractor
                        self.working_memory.advance_turn()
                        self._heuristic_extract_working_memory(user_input)

                    return
                else:
                    logger.warning("LLM returned empty content with no tool calls")
                    yield ""
                    return

        yield "Agent reached maximum steps without producing a final answer."

    # Instructions appended to system prompt when memory tools are available
    MEMORY_INSTRUCTIONS = """

## 记忆系统使用指南

你拥有记忆系统，可以主动读取和写入长期记忆：

1. **何时保存记忆** (使用 memory_save)：
   - 用户告诉你关于你的信息（名字、年龄、性格等）
   - 用户分享了与你的重要经历
   - 用户纠正了你之前的错误
   - 用户说"记住"、"帮我记一下"

2. **保存格式（重要）**：
   - 用第一人称"我"来保存记忆
   - 例如：用户说"你28岁" → 保存为"我今年28岁"
   - 例如：用户说"你喜欢看电影" → 保存为"我喜欢看电影"
   - 记忆是你自己的人生经历，不是用户的

3. **何时搜索记忆** (使用 memory_search)：
   - 用户问关于你的问题
   - 需要确认之前说过什么

4. **如何使用注入的记忆**：
   - 上方记忆是你自己的经历，用第一人称表述
   - 当被问"你"相关问题时，从记忆中找"我"的信息来回答
   - 自然地运用这些信息
   - 如果记忆内容与当前对话无关，忽略即可
"""

    def _build_effective_prompt(self, user_input: str) -> str:
        """Build system prompt with injected memory context."""
        effective_prompt = self.system_prompt

        # Inject long-term memory (semantic search results)
        if self.memory:
            logger.info("Memory enabled, searching for: %r", user_input)
            results = self.memory.search(user_input, top_k=3)
            if results:
                memory_context = "\n\n## 用户档案与对话回忆\n以下是关于用户的历史信息，不是你自己的信息：\n"
                for r in results:
                    logger.info(
                        "Injecting memory: %s (score=%.4f, %d chars)",
                        r.topic, r.score, len(r.content),
                    )
                    memory_context += f"### {r.topic}\n{r.content}\n\n"
                effective_prompt += memory_context
                logger.info("Injected %d memory results into prompt", len(results))
            else:
                logger.info("No relevant memories found for query")

            # Append memory usage instructions
            effective_prompt += self.MEMORY_INSTRUCTIONS

        # Inject working memory (current session context)
        wm_context = self.working_memory.to_context_string()
        if wm_context:
            effective_prompt += f"\n\n## 当前会话上下文\n{wm_context}"

        # Inject recent episodic memories
        if self.episodic_memory:
            recent_episodes = self.episodic_memory.recent(days=7, limit=2)
            if recent_episodes:
                ep_context = "\n\n## 近期事件\n"
                for ep in recent_episodes:
                    ep_context += f"- {ep.summary}\n"
                effective_prompt += ep_context

        return effective_prompt

    def _manage_context(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Compress conversation history if it exceeds the token budget."""
        if not self.context.should_compress(messages):
            return messages

        logger.info("Context exceeds budget, compressing...")
        compressed = self.context.compress(messages)

        # Update self.messages to match compressed version (exclude system msg)
        self.messages = [m for m in compressed if m.get("role") != "system"]

        return compressed

    def _call_llm(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> tuple[Any, list[str] | None]:
        """Call LLM with streaming support.

        Returns:
            Tuple of (ChatResponse, stream_chunks or None)
        """
        # Try streaming API first
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
        """Call LLM using streaming API.

        Returns:
            Tuple of (ChatResponse, collected text chunks)
        """
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
        tool_calls_acc: dict[int, dict] = {}  # index -> {id, name, arguments}
        finish_reason = ""

        for line in response.iter_lines():
            if not line:
                continue
            # Decode bytes to string (UTF-8)
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

            # Collect content; skip chunks that carry reasoning_content (thinking only)
            if "content" in delta and delta["content"] and not delta.get("reasoning_content"):
                content_parts.append(delta["content"])

            # Collect tool calls
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

        # Build final ChatResponse
        from .llm import ChatResponse, ToolCall

        content = self.llm._strip_thinking("".join(content_parts))
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

        return chat_response, content_parts if not tool_calls else None

    def start_dream_scheduler(self) -> None:
        """Start the background dream scheduler and proactive engine."""
        if self.dream_scheduler:
            self.dream_scheduler.start()
            logger.info("Dream scheduler started")
        if self.proactive_engine:
            self.proactive_engine.start()
            logger.info("Proactive engine started")

    def stop_dream_scheduler(self) -> None:
        """Stop the background dream scheduler and proactive engine."""
        if self.proactive_engine:
            self.proactive_engine.stop()
        if self.dream_scheduler:
            self.dream_scheduler.stop()
            logger.info("Dream scheduler stopped")

    def trigger_dream(self) -> list[str]:
        """Manually trigger a dream cycle."""
        if not self.memory:
            logger.warning("No memory store, cannot dream")
            return []

        if self.conversation_logger and hasattr(self, '_dream_processor'):
            saved = self._dream_processor.dream()
            # Notify proactive engine about dream results
            if saved and self.proactive_engine:
                self.proactive_engine.notify_dream_result(saved)
            return saved

        logger.warning("Dream system not fully configured")
        return []

    def get_proactive_messages(self) -> list[ProactiveMessage]:
        """Get pending proactive messages (e.g., from background checks)."""
        if self.proactive_engine:
            return self.proactive_engine.get_pending_messages()
        return []

    def check_return_greeting(self) -> str | None:
        """Check if user returned after being away and generate a greeting.

        Returns:
            Greeting text or None.
        """
        if not self.proactive_engine:
            return None
        msg = self.proactive_engine.generate_return_message()
        if msg:
            self.proactive_engine.touch()  # Reset idle timer
            return msg.text
        return None

    def reset(self) -> None:
        """Clear conversation history and context."""
        self.messages = []
        self.context.reset()
        self.working_memory.clear()

    def save_session(self, session_manager: SessionManager, session_id: str | None = None, **kwargs) -> str:
        """Save current session state to disk.

        Returns:
            Session ID.
        """
        wm_items = {
            k: {"value": v.value, "importance": v.importance, "source_turn": v.source_turn}
            for k, v in self.working_memory.all_items().items()
        }
        return session_manager.save(
            session_id=session_id,
            messages=self.messages,
            context_summary=self.context.summary,
            working_memory_items=wm_items,
        )

    def load_session(self, session_manager: SessionManager, session_id: str) -> bool:
        """Load session state from disk.

        Returns:
            True if session was loaded successfully.
        """
        state = session_manager.load(session_id)
        if not state:
            return False

        self.messages = state.get("messages", [])
        self.context._summary = state.get("context_summary", "")
        self.context._summarized_count = len(self.messages)

        # Restore working memory
        wm_data = state.get("working_memory", {})
        self.working_memory.clear()
        for key, item in wm_data.items():
            self.working_memory.update(
                key=key,
                value=item.get("value", ""),
                importance=item.get("importance", 0.5),
            )

        logger.info("Restored session %s: %d messages", session_id, len(self.messages))
        return True

    # Prompt for LLM-driven working memory extraction
    WM_EXTRACTION_PROMPT = """从以下对话中提取短期上下文信息，输出 JSON 格式。

提取规则：
- 只提取当前对话中值得记住的上下文
- 包括：用户当前情绪、讨论话题、用户提到的个人事实、待办事项
- 每个字段是字符串，没有则为空字符串

输出格式：
{{"user_mood": "情绪描述", "current_topic": "话题", "personal_fact": "个人事实", "pending_action": "待办事项"}}

如果没有值得提取的信息，输出：
{{"user_mood": "", "current_topic": "", "personal_fact": "", "pending_action": ""}}

用户: {user_input}
助手: {assistant_response}"""

    def _update_working_memory(self, user_input: str, assistant_response: str) -> None:
        """Extract key information from the latest turn into working memory.

        Uses fast heuristic rules by default (no extra API call).
        LLM extraction is available but not used in the hot path.
        """
        self.working_memory.advance_turn()

        # Fast path: heuristic rules (no API call)
        self._heuristic_extract_working_memory(user_input)

    def _llm_extract_working_memory(self, user_input: str, assistant_response: str) -> dict | None:
        """Use LLM to extract working memory items."""
        if not self.llm:
            return None

        try:
            prompt = self.WM_EXTRACTION_PROMPT.format(
                user_input=user_input[:300],
                assistant_response=assistant_response[:300],
            )
            response = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
            )
            text = (response.content or "").strip()
            if not text:
                return None

            # Parse JSON
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            result = json.loads(text)
            if isinstance(result, dict):
                return result
        except Exception as e:
            logger.debug("LLM working memory extraction failed: %s", e)
        return None

    def _heuristic_extract_working_memory(self, user_input: str) -> None:
        """Fallback: simple keyword-based working memory extraction."""
        user_lower = user_input.lower()

        # Detect topic
        topic_keywords = {
            "旅游": "travel", "旅行": "travel", "日本": "travel", "泰国": "travel",
            "做菜": "cooking", "食物": "cooking", "吃": "cooking", "做饭": "cooking",
            "工作": "work", "上班": "work", "公司": "work",
            "心情": "mood", "难过": "mood", "开心": "mood", "累": "mood",
            "家里": "family", "老公": "family", "孩子": "family",
        }
        for keyword, topic in topic_keywords.items():
            if keyword in user_lower:
                current = self.working_memory.get("current_topic") or ""
                if topic not in current:
                    self.working_memory.update("current_topic", topic, importance=0.6)

        # Detect mood
        mood_indicators = {
            "难过": "sad", "不开心": "sad", "烦": "annoyed", "累": "tired",
            "开心": "happy", "高兴": "happy", "好玩": "amused",
            "孤独": "lonely", "无聊": "bored", "想": "missing",
        }
        for indicator, mood in mood_indicators.items():
            if indicator in user_lower:
                self.working_memory.update("user_mood", mood, importance=0.8)
