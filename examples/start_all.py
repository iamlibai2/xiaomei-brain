"""Unified startup script for xiaomei-brain — integrates Gateway, Channels, and WebSocket Server.

This is the main entry point that:
1. Loads configuration
2. Initializes AgentManager for multi-agent support
3. Creates Gateway to manage all channels (Feishu, DingTalk, WeChat, etc.)
4. Starts all channels
5. Starts WebSocket server

Usage:
    PYTHONPATH=src python3 examples/start_all.py

Configuration:
    - ~/.xiaomei-brain/config.json (OpenClaw format)
    - Agent definitions in agents.list
    - Channel configs in channels section

Channels supported:
    - Feishu (via channels.feishu)
    - DingTalk (via channels.dingtalk) — TODO
    - WeChat (via channels.wechat) — TODO
"""

import asyncio
import io
import logging
import os
import sys
import threading
import warnings
from pathlib import Path
from typing import AsyncIterator

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
warnings.filterwarnings("ignore")

for _name in [
    "sentence_transformers", "transformers", "httpx", "httpcore",
    "filelock", "huggingface_hub", "urllib3", "torch",
]:
    logging.getLogger(_name).setLevel(logging.ERROR)

import logging as _logging
logging.basicConfig(
    level=_logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# Suppress tqdm
try:
    import tqdm as _tqdm
    _tqdm.tqdm.disable = True
except ImportError:
    pass

from xiaomei_brain import Agent, Config, AgentManager
from xiaomei_brain.channels.gateway import Gateway
from xiaomei_brain.channels.types import InboundMsg, OutboundMsg
from xiaomei_brain.memory import (
    ConversationLogger, DreamProcessor, DreamScheduler, EpisodicMemory,
)
from xiaomei_brain.memory.layers import WorkingMemory
from xiaomei_brain.proactive import ProactiveEngine
from xiaomei_brain.reminder import ReminderManager
from xiaomei_brain.session import SessionManager
from xiaomei_brain.speech import TTSProvider, VoiceConfig, AudioConfig
from xiaomei_brain.tools.builtin import (
    shell_tool, read_file_tool, write_file_tool,
    tts_tools, music_tools, image_tools, websearch_tools, webget_tools,
)
from xiaomei_brain.tools.builtin.memory import create_memory_tools
from xiaomei_brain.ws import create_app

logger = logging.getLogger(__name__)


class AgentGateway(Gateway):
    """Gateway that routes inbound messages to agents.

    Routing logic:
    1. If msg.extra contains 'agent_id', use that agent directly
    2. Otherwise, look up bindings based on channel + account_id
    3. Fall back to 'xiaomei' agent if no binding found
    """

    def __init__(self, agent_manager: AgentManager, config: Config, bindings: list[dict] | None = None):
        super().__init__()
        self.agent_manager = agent_manager
        self.config = config
        self._agents: dict[str, Agent] = {}  # Cache of built Agent objects
        self._default_agent: Agent | None = None
        self._bindings = bindings or []

    def _get_agent_for_msg(self, msg: InboundMsg) -> Agent:
        """Get the appropriate Agent for a message."""
        # Check if msg specifies an agent_id directly
        if msg.extra:
            agent_id = msg.extra.get("agent_id")
            if agent_id:
                return self._get_or_build_agent(agent_id)

        # Look up agent from bindings based on channel + account_id
        account_id = msg.extra.get("account_id", "default") if msg.extra else "default"
        for binding in self._bindings:
            if (binding.get("match", {}).get("channel") == msg.platform and
                binding.get("match", {}).get("accountId") == account_id):
                agent_id = binding.get("agentId")
                return self._get_or_build_agent(agent_id)

        # Fall back to xiaomei agent (default)
        return self._get_or_build_agent("xiaomei")

    def _get_or_build_agent(self, agent_id: str) -> Agent:
        """Get cached agent or build new one."""
        if agent_id not in self._agents:
            agent_instance = self.agent_manager.build_agent(agent_id, self.config)
            self._agents[agent_id] = self._build_full_agent(agent_instance)
        return self._agents[agent_id]

    def _build_full_agent(self, agent_instance) -> Agent:
        """Build full Agent object from AgentInstance."""
        llm = agent_instance.llm
        tools = agent_instance.tools
        memory = agent_instance.memory
        episodic_memory = agent_instance.episodic_memory
        session_manager = agent_instance.session_manager
        working_memory = agent_instance.working_memory

        system_prompt = agent_instance.get_system_prompt() or self.config.system_prompt

        conversation_dir = os.path.join(agent_instance.agent_dir(), "memory", "conversations")
        conversation_logger = ConversationLogger(log_dir=conversation_dir)

        dream_processor = DreamProcessor(
            llm=llm,
            memory=memory,
            conversation_logger=conversation_logger,
            episodic_memory=episodic_memory,
        )
        dream_scheduler = DreamScheduler(
            dream_processor=dream_processor,
            idle_threshold=self.config.dream_idle_threshold,
        )

        reminder_manager = ReminderManager(
            memory_dir=os.path.join(agent_instance.agent_dir(), "memory"),
            llm_client=llm,
        )

        proactive_engine = ProactiveEngine(
            llm_client=llm,
            reminder_manager=reminder_manager,
            on_message=lambda msg: logger.info(f"[Proactive] {msg.text}"),
            away_threshold=self.config.proactive_away_threshold,
        )

        context_extractor = None
        try:
            from xiaomei_brain.context_extractor import ContextExtractor
            context_extractor = ContextExtractor(
                llm=llm,
                working_memory=working_memory,
                reminder_manager=reminder_manager,
                message_interval=5,
                time_interval=120,
            )
        except ImportError:
            pass

        agent = Agent(
            llm=llm,
            tools=tools,
            system_prompt=system_prompt,
            max_steps=self.config.max_steps,
            memory=memory,
            conversation_logger=conversation_logger,
            dream_scheduler=dream_scheduler,
            episodic_memory=episodic_memory,
            proactive_engine=proactive_engine,
            reminder_manager=reminder_manager,
            context_max_tokens=self.config.context_max_tokens,
            context_recent_turns=self.config.context_recent_turns,
            context_extractor=context_extractor,
        )
        agent.working_memory = working_memory
        agent._dream_processor = dream_processor

        # Start services
        agent.start_dream_scheduler()
        if context_extractor:
            context_extractor.start()

        return agent

    async def on_message(self, msg: InboundMsg) -> OutboundMsg:
        """Handle inbound message by routing to appropriate agent."""
        try:
            agent = self._get_agent_for_msg(msg)
            logger.info(f"[GATEWAY] Routing to agent: {agent.llm.model}")

            # Stream response from agent (agent.stream returns a regular generator)
            full_response = ""
            for chunk in agent.stream(msg.text):
                full_response += chunk

            return OutboundMsg(text=full_response)

        except Exception as e:
            logger.error(f"[GATEWAY] Error processing message: {e}", exc_info=True)
            return OutboundMsg(text="Sorry, I encountered an error processing your message.")

    async def on_message_streaming(self, msg: InboundMsg) -> AsyncIterator[str]:
        """流式返回 Agent 回复 chunks"""
        try:
            agent = self._get_agent_for_msg(msg)
            logger.info(f"[GATEWAY] Streaming with agent: {agent.llm.model}")

            # Stream response from agent (agent.stream returns a generator, wrap as async generator)
            for chunk in agent.stream(msg.text):
                yield chunk

        except Exception as e:
            logger.error(f"[GATEWAY] Error streaming message: {e}", exc_info=True)
            yield f"⚠️ 回复出错: {str(e)}"


def load_channels_from_config(config: Config, gateway: Gateway) -> list[dict]:
    """Load channels from config and add to gateway.

    Config format (OpenClaw style):
    {
        "channels": {
            "feishu": {
                "enabled": true,
                "accounts": {
                    "default": {"appId": "...", "appSecret": "..."},
                    "xiaomei": {"appId": "...", "appSecret": "..."}
                }
            },
            ...
        }
    }

    Returns:
        List of bindings for agent routing.
    """
    import json
    config_path = None
    search_paths = [
        Path("config.json"),
        Path.cwd().parent / "config.json",
        Path.home() / ".xiaomei-brain" / "config.json",
    ]

    for path in search_paths:
        if path.exists():
            config_path = path
            break

    if not config_path:
        logger.info("No config.json found, skipping channel loading")
        return []

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)

        channels_cfg = config_data.get("channels", {})
        bindings = config_data.get("bindings", [])

        # Feishu channel (supports multiple accounts)
        if channels_cfg.get("feishu", {}).get("enabled", False):
            from xiaomei_brain.channels.feishu import FeishuChannel
            feishu_cfg = channels_cfg["feishu"]
            accounts = feishu_cfg.get("accounts", {})
            streaming = feishu_cfg.get("streaming", False)
            streaming_header_title = feishu_cfg.get("streamingHeaderTitle", "小美")

            logger.info(f"[GATEWAY] Feishu streaming={streaming}, header_title={streaming_header_title}")

            for account_id, account_cfg in accounts.items():
                feishu_channel = FeishuChannel(
                    app_id=account_cfg.get("appId", ""),
                    app_secret=account_cfg.get("appSecret", ""),
                    verification_token=account_cfg.get("verificationToken", ""),
                    account_id=account_id,
                    streaming=streaming,
                    streaming_header_title=streaming_header_title,
                )
                gateway.add_channel(feishu_channel)
                logger.info(f"[GATEWAY] Added Feishu channel (account: {account_id})")

        # DingTalk channel (TODO)
        if channels_cfg.get("dingtalk", {}).get("enabled", False):
            logger.warning("[GATEWAY] DingTalk channel not yet implemented")

        # WeChat channel (TODO)
        if channels_cfg.get("wechat", {}).get("enabled", False):
            logger.warning("[GATEWAY] WeChat channel not yet implemented")

        return bindings

    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"[GATEWAY] Failed to load channels from config: {e}")
        return []


def main() -> None:
    """Main entry point."""
    # Load config
    config = Config.from_json()
    logger.info(f"[START] Config loaded: provider={config.provider}, model={config.model}")

    # Initialize AgentManager
    base_dir = os.path.expanduser("~/.xiaomei-brain")
    agent_manager = AgentManager(base_dir=base_dir)
    logger.info(f"[START] AgentManager initialized: {base_dir}")

    # List available agents
    agents = agent_manager.list()
    logger.info(f"[START] Available agents: {', '.join(a.id for a in agents)}")

    # Create Gateway (with bindings for routing)
    # First load config to get bindings
    import json
    config_path = None
    search_paths = [
        Path("config.json"),
        Path.cwd().parent / "config.json",
        Path.home() / ".xiaomei-brain" / "config.json",
    ]
    for path in search_paths:
        if path.exists():
            config_path = path
            break

    bindings = []
    if config_path:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
            bindings = config_data.get("bindings", [])
            logger.info(f"[START] Loaded {len(bindings)} bindings")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"[START] Failed to load bindings: {e}")

    gateway = AgentGateway(agent_manager=agent_manager, config=config, bindings=bindings)

    # Load channels from config
    load_channels_from_config(config, gateway)

    # Preload default agent (build index, etc.)
    logger.info("[START] Preloading default agent...")
    default_instance = agent_manager.build_agent("default", config)

    # Preload embedding model
    logger.info("[START] Loading embedding model...")
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    try:
        default_instance.memory.embedder.embed("preload")
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
    logger.info("[START] Embedding model loaded")

    # Build memory index
    logger.info("[START] Building memory index...")
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    try:
        default_instance.memory._ensure_index()
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
    logger.info(f"[START] Memory index built ({len(default_instance.memory.list_topics())} topics)")
    logger.info("[DEBUG] About to check TTS config...")

    # Setup TTS for WebSocket
    tts_provider = None
    if config.tts_enabled:
        tts_api_key = config.tts_api_key or config.api_key
        if tts_api_key:
            voice_config = VoiceConfig(
                voice_id=config.tts_voice_id,
                speed=config.tts_speed,
                vol=config.tts_vol,
                pitch=config.tts_pitch,
                emotion=config.tts_emotion,
            )
            audio_config = AudioConfig(
                format=config.tts_format,
                sample_rate=config.tts_sample_rate,
                bitrate=config.tts_bitrate,
            )
            tts_provider = TTSProvider(
                api_key=tts_api_key,
                base_url=config.tts_base_url,
                voice_config=voice_config,
                audio_config=audio_config,
            )
            logger.info(f"[START] TTS enabled: voice={config.tts_voice_id}")

    # Build default agent for WebSocket
    agent = gateway._build_full_agent(default_instance)

    # Create WebSocket app
    app = create_app(
        agent=agent,
        tts=tts_provider,
        session_manager=default_instance.session_manager,
        agent_manager=agent_manager,
        config=config,
    )

    # Start channels in a background event loop (before uvicorn)
    def run_channels():
        """Run channels in a dedicated event loop"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(gateway.start_all())
            # Keep the loop running for background tasks
            loop.run_forever()
        except KeyboardInterrupt:
            logger.info("[CHANNELS] Interrupted, stopping...")
        finally:
            loop.run_until_complete(gateway.stop_all())
            loop.close()

    channels_thread = threading.Thread(target=run_channels, daemon=True, name="ChannelsEventLoop")
    channels_thread.start()
    logger.info("[START] Channels event loop thread started")

    # Start WebSocket server
    host = os.environ.get("WS_HOST", "0.0.0.0")
    port = int(os.environ.get("WS_PORT", "8765"))

    logger.info("=" * 60)
    logger.info(f"[START] xiaomei-brain Unified Gateway")
    logger.info("=" * 60)
    logger.info(f"[START] WebSocket: ws://{host}:{port}/ws")
    logger.info(f"[START] Health:    http://{host}:{port}/health")
    logger.info(f"[START] Agent:     {config.provider}/{config.model}")
    logger.info(f"[START] Channels:  {', '.join(ch.platform_name() for ch in gateway.channels)}")
    logger.info(f"[START] Base dir:  {base_dir}")
    logger.info("=" * 60)

    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("[START] Shutting down...")
    finally:
        logger.info("[START] Goodbye!")
