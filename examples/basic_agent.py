"""Basic agent example with full feature set including proactive behavior."""

import io
import logging
import os
import sys
import time as _time
import warnings
os.environ["HF_HUB_OFFLINE"] = "1"

# ── Suppress ALL noisy third-party output BEFORE any imports ──
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
warnings.filterwarnings("ignore")
for _name in [
    "sentence_transformers", "transformers", "httpx", "httpcore",
    "filelock", "huggingface_hub", "urllib3", "torch",
]:
    logging.getLogger(_name).setLevel(logging.ERROR)

# Suppress tqdm progress bars globally
try:
    import tqdm as _tqdm
    _tqdm.tqdm.disable = True
except ImportError:
    pass

from xiaomei_brain import Agent, Config, AgentManager
from xiaomei_brain.doctor import Doctor
from xiaomei_brain.memory import (
    ConversationLogger, DreamProcessor, DreamScheduler, EpisodicMemory,
)
from xiaomei_brain.memory.layers import WorkingMemory
from xiaomei_brain.proactive import ProactiveEngine
from xiaomei_brain.reminder import ReminderManager
from xiaomei_brain.speech import TTSProvider, VoiceConfig, AudioConfig, StreamingTTSPlayer
from xiaomei_brain.speech import MusicProvider, MusicAudioConfig
from xiaomei_brain.image import ImageProvider, ImageConfig
from xiaomei_brain.websearch import BaiduSearchProvider
from xiaomei_brain.webget import WebGetProvider
from xiaomei_brain.tools.builtin import shell_tool, read_file_tool, write_file_tool, tts_tools, music_tools, image_tools, websearch_tools, webget_tools
from xiaomei_brain.tools.builtin.memory import create_memory_tools


def main():
    # Load config from config.json (OpenClaw format)
    config = Config.from_json()

    # Configure logging based on config
    logging.basicConfig(
        level=getattr(logging, config.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # ── AgentManager: multi-agent registry ──────────────────────────
    # Base dir for all agents: ~/.xiaomei-brain/
    # Each agent has: talent.md, memory/, sessions/
    agent_manager = AgentManager(base_dir=os.path.expanduser("~/.xiaomei-brain"))

    # Build the "default" agent (reads from config.json, creates dirs on first run)
    agent_instance = agent_manager.build_agent("default", config)

    # Get the LLM, tools, memory, session_manager from the agent instance
    llm = agent_instance.llm
    tools = agent_instance.tools
    memory = agent_instance.memory
    episodic_memory = agent_instance.episodic_memory
    session_manager = agent_instance.session_manager
    working_memory = agent_instance.working_memory

    # Get system prompt from talent.md
    system_prompt = agent_instance.get_system_prompt() or config.system_prompt

    # TTS setup — tools already registered by build_agent, just set player here
    tts_player = None
    if config.tts_enabled:
        tts_api_key = config.tts_api_key or config.api_key
        if not tts_api_key:
            print("Warning: TTS enabled but no API key found")
        else:
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
            tts_player = StreamingTTSPlayer(tts_provider)
            tts_tools.set_tts_player(tts_player, tts_provider)
            print(f"TTS enabled: voice={config.tts_voice_id}, emotion={config.tts_emotion}")

    # Music — tools already registered by build_agent
    if config.music_enabled:
        music_api_key = config.music_api_key or config.tts_api_key or config.api_key
        if music_api_key:
            print(f"Music enabled: base_url={config.music_base_url}")

    # Image — tools already registered by build_agent
    if config.image_enabled:
        image_api_key = config.image_api_key or config.tts_api_key or config.api_key
        if image_api_key:
            print(f"Image enabled: base_url={config.image_base_url}, aspect_ratio={config.image_aspect_ratio}")

    # Web search — tools already registered by build_agent
    if config.web_search_enabled:
        if config.baidu_api_key:
            print("Web search enabled: Baidu AI Search")

    # Web get — tools already registered by build_agent
    if config.web_get_enabled:
        print(f"Web get enabled: max_chars={config.web_get_max_chars}")

    # Create conversation logger (uses agent's memory dir)
    conversation_dir = os.path.join(agent_instance.agent_dir(), "memory", "conversations")
    conversation_logger = ConversationLogger(log_dir=conversation_dir)

    # Create dream system (with episodic memory)
    dream_processor = DreamProcessor(
        llm=llm,
        memory=memory,
        conversation_logger=conversation_logger,
        episodic_memory=episodic_memory,
    )
    dream_scheduler = DreamScheduler(
        dream_processor=dream_processor,
        idle_threshold=config.dream_idle_threshold,
    )

    # Create reminder manager
    reminder_manager = ReminderManager(memory_dir=os.path.join(agent_instance.agent_dir(), "memory"), llm_client=llm)

    # Create proactive engine with callback for real-time messages
    def on_proactive_message(msg):
        print(f"\n[Proactive] {msg.text}\nYou: ", end="", flush=True)

    proactive_engine = ProactiveEngine(
        llm_client=llm,
        reminder_manager=reminder_manager,
        on_message=on_proactive_message,
        away_threshold=config.proactive_away_threshold,
    )

    # Create background context extractor
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

    # Create agent with all features (system_prompt from talent.md)
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
    if context_extractor:
        context_extractor.start()

    # Try to restore last session
    latest_id = session_manager.latest_session_id()
    current_session = None
    if latest_id:
        try:
            choice = input(f"Found previous session ({latest_id}). Resume? [Y/n] ").strip().lower()
            if choice in ("", "y", "yes"):
                if agent.load_session(session_manager, latest_id):
                    current_session = latest_id
                    print(f"Resumed session: {latest_id}")
        except EOFError:
            pass

    if not current_session:
        current_session = f"session-{int(_time.time())}"

    # Preload embedding model
    print("Loading embedding model...", end="", flush=True)
    _old_stdout, _old_stderr = sys.stdout, sys.stderr
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    try:
        memory.embedder.embed("preload")
    finally:
        sys.stdout, sys.stderr = _old_stdout, _old_stderr
    print(" done")

    # Build memory index
    print("Building memory index...", end="", flush=True)
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    try:
        memory._ensure_index()
    finally:
        sys.stdout, sys.stderr = _old_stdout, _old_stderr
    print(f" done ({len(memory.list_topics())} topics)")

    # Start background services
    agent.start_dream_scheduler()

    # Check for return greeting
    greeting = agent.check_return_greeting()
    if greeting:
        print(f"[Agent] {greeting}")

    # Check for pending proactive messages
    pending = agent.get_proactive_messages()
    for msg in pending:
        print(f"[Agent] {msg.text}")

    # Check for due reminders
    if reminder_manager:
        due = reminder_manager.check_due()
        for r in due:
            print(f"[Reminder] 别忘了：{r.text}")

    print("\n=== Xiaomei Brain Agent ===")
    print(f"Provider: {config.provider}, Model: {config.model}")
    print("Tools:", [t.name for t in tools.list_tools()])
    print(f"Agent: {agent_instance.id} ({agent_instance.name})")
    print(f"  Talent: {agent_instance.talent_path}")
    print(f"  Memory: {os.path.join(agent_instance.agent_dir(), 'memory')}")
    print(f"  Topics: {memory.list_topics()}")
    print(f"  Episodes: {len(episodic_memory.load_all())}")
    pending_reminders = reminder_manager.get_pending() if reminder_manager else []
    print(f"  Reminders: {len(pending_reminders)} pending")
    print(f"  TTS: {'enabled' if config.tts_enabled else 'disabled'}")
    print(f"  Music: {'enabled' if config.music_enabled else 'disabled'}")
    print(f"  Image: {'enabled' if config.image_enabled else 'disabled'}")
    print(f"  WebSearch: {'enabled' if config.web_search_enabled else 'disabled'}")
    print(f"  WebGet: {'enabled' if config.web_get_enabled else 'disabled'}")
    print(f"Session: {current_session}")
    print("Dream: auto on idle (5min) or midnight")
    print("Proactive: away detection + reminder alerts")
    print()
    print("Commands: dream | memory | reminders | sessions | agents | reset | save | doctor | quit")
    print()

    # Interaction loop with streaming
    try:
        while True:
            try:
                user_input = input("You: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nBye!")
                break
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                break
            if user_input.lower() == "reset":
                agent.reset()
                print("Conversation cleared.")
                continue
            if user_input.lower() == "dream":
                print("Dreaming...", flush=True)
                saved = agent.trigger_dream()
                if saved:
                    print(f"Dream complete. Saved/updated: {saved}")
                else:
                    print("Dream complete. No new memories.")
                continue
            if user_input.lower() == "memory":
                wm = agent.working_memory.to_context_string()
                print(f"Working memory:\n{wm}" if wm else "Working memory: empty")
                continue
            if user_input.lower() == "reminders":
                all_reminders = reminder_manager.get_all()
                if all_reminders:
                    for r in all_reminders:
                        status = "done" if r.fired else "pending"
                        ts = _time.strftime("%m/%d", _time.localtime(r.trigger_time))
                        print(f"  [{status}] {ts} - {r.text}")
                else:
                    print("No reminders.")
                continue
            if user_input.lower() == "save":
                sid = agent.save_session(session_manager, current_session)
                print(f"Session saved: {sid}")
                continue
            if user_input.lower() == "sessions":
                sessions = session_manager.list_sessions()
                if sessions:
                    for s in sessions[:5]:
                        ts = _time.strftime("%Y-%m-%d %H:%M", _time.localtime(s["timestamp"]))
                        print(f"  {s['id']} ({ts}, {s['message_count']} msgs)")
                else:
                    print("No saved sessions.")
                continue
            if user_input.lower() == "agents":
                for a in agent_manager.list():
                    print(f"  [{a.id}] {a.name} — {a.description}")
                continue
            if user_input.lower() == "doctor":
                print()
                doctor = Doctor()
                doctor.run()
                doctor.print_report()
                continue

            try:
                print("Agent: ", end="", flush=True)
                for chunk in agent.stream(user_input):
                    print(chunk, end="", flush=True)
                print()
            except KeyboardInterrupt:
                print("\nBye!")
                break
    finally:
        try:
            agent.save_session(session_manager, current_session)
            print(f"\nSession auto-saved: {current_session}")
        except BaseException as e:
            print(f"\nSession save failed: {e}")
        agent.stop_dream_scheduler()


if __name__ == "__main__":
    main()
