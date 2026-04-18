"""WebSocket server entry point for xiaomei-brain — multi-agent aware."""

import io
import logging
import os
import sys
import warnings

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
from xiaomei_brain.memory import (
    ConversationLogger, DreamProcessor, DreamScheduler, EpisodicMemory,
)
from xiaomei_brain.memory.layers import WorkingMemory
from xiaomei_brain.agent.proactive import ProactiveEngine
from xiaomei_brain.agent.reminder import ReminderManager
from xiaomei_brain.agent.session import SessionManager
from xiaomei_brain.speech import TTSProvider, VoiceConfig, AudioConfig
from xiaomei_brain.tools.builtin import (
    shell_tool, read_file_tool, write_file_tool,
    tts_tools, music_tools, image_tools, websearch_tools, webget_tools,
)
from xiaomei_brain.tools.builtin.memory import create_memory_tools
from xiaomei_brain.ws import create_app


def main() -> None:
    config = Config.from_json()

    # ── AgentManager: multi-agent registry ──────────────────────────
    agent_manager = AgentManager(base_dir=os.path.expanduser("~/.xiaomei-brain"))

    # Build default agent (lazy — dirs created on first run)
    agent_instance = agent_manager.build_agent("default", config)

    # Get components from agent instance
    llm = agent_instance.llm
    tools = agent_instance.tools
    memory = agent_instance.memory
    episodic_memory = agent_instance.episodic_memory
    session_manager = agent_instance.session_manager
    working_memory = agent_instance.working_memory

    # Get system prompt from talent.md
    system_prompt = agent_instance.get_system_prompt() or config.system_prompt

    # TTS — tools already registered by build_agent, just set provider
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
            tts_tools.set_tts_player(None, tts_provider)
            print(f"TTS enabled: voice={config.tts_voice_id}")

    # Music — tools already registered by build_agent
    if config.music_enabled:
        music_api_key = config.music_api_key or config.tts_api_key or config.api_key
        if music_api_key:
            print(f"Music enabled")

    # Image — tools already registered by build_agent
    if config.image_enabled:
        image_api_key = config.image_api_key or config.tts_api_key or config.api_key
        if image_api_key:
            print(f"Image enabled")

    # Web search — tools already registered by build_agent
    if config.web_search_enabled and config.baidu_api_key:
        print("Web search enabled")

    # Web get — tools already registered by build_agent
    if config.web_get_enabled:
        print("Web get enabled")

    # Conversation logger
    conversation_dir = os.path.join(agent_instance.agent_dir(), "memory", "conversations")
    conversation_logger = ConversationLogger(log_dir=conversation_dir)

    # Dream system
    dream_processor = DreamProcessor(
        llm=llm, memory=memory,
        conversation_logger=conversation_logger,
        episodic_memory=episodic_memory,
    )
    dream_scheduler = DreamScheduler(
        dream_processor=dream_processor,
        idle_threshold=config.dream_idle_threshold,
    )
    reminder_manager = ReminderManager(
        memory_dir=os.path.join(agent_instance.agent_dir(), "memory"),
        llm_client=llm,
    )

    proactive_engine = ProactiveEngine(
        llm_client=llm,
        reminder_manager=reminder_manager,
        on_message=lambda msg: print(f"\n[Proactive] {msg.text}\nYou: "),
        away_threshold=config.proactive_away_threshold,
    )

    # Context extractor
    context_extractor = None
    try:
        from xiaomei_brain.agent.context_extractor import ContextExtractor
        context_extractor = ContextExtractor(
            llm=llm,
            working_memory=working_memory,
            reminder_manager=reminder_manager,
            message_interval=5,
            time_interval=120,
        )
    except ImportError:
        pass

    # Build the Agent with all features
    agent = Agent(
        llm=llm,
        tools=tools,
        system_prompt=system_prompt,
        max_steps=config.max_steps,
        memory=memory,
        conversation_logger=conversation_logger,
        dream_scheduler=dream_scheduler,
        episodic_memory=episodic_memory,
        proactive_engine=proactive_engine,
        reminder_manager=reminder_manager,
        context_max_tokens=config.context_max_tokens,
        context_recent_turns=config.context_recent_turns,
        context_extractor=context_extractor,
    )
    agent.working_memory = working_memory
    agent._dream_processor = dream_processor

    # Preload embedding model
    print("Loading embedding model...", end="", flush=True)
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    try:
        memory.embedder.embed("preload")
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
    print(" done")

    print("Building memory index...", end="", flush=True)
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    try:
        memory._ensure_index()
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
    print(f" done ({len(memory.list_topics())} topics)")

    # Start services
    agent.start_dream_scheduler()
    if context_extractor:
        context_extractor.start()

    # Create WS app with agent + agent_manager for multi-agent routing
    app = create_app(agent, tts=tts_provider, session_manager=session_manager, agent_manager=agent_manager, config=config)

    import uvicorn
    host = os.environ.get("WS_HOST", "0.0.0.0")
    port = int(os.environ.get("WS_PORT", "8765"))
    print(f"\n=== xiaomei-brain WebSocket Server ===")
    print(f"WebSocket: ws://{host}:{port}/ws")
    print(f"Health:    http://{host}:{port}/health")
    print(f"Agent:     {config.provider}/{config.model} ({agent_instance.id}/{agent_instance.name})")
    print(f"  Talent:  {agent_instance.talent_path}")
    print(f"  Memory:  {os.path.join(agent_instance.agent_dir(), 'memory')}")
    print()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
