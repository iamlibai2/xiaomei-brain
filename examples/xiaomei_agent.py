"""启动小美 Agent — 独立进程，连接 WebSocket 或直接交互。"""

import io
import logging
import os
import sys
import time as _time
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
from xiaomei_brain.agent.proactive import ProactiveEngine
from xiaomei_brain.agent.reminder import ReminderManager
from xiaomei_brain.speech import TTSProvider, VoiceConfig, AudioConfig, StreamingTTSPlayer
from xiaomei_brain.speech import MusicProvider, MusicAudioConfig
from xiaomei_brain.image import ImageProvider, ImageConfig
from xiaomei_brain.websearch import BaiduSearchProvider
from xiaomei_brain.webget import WebGetProvider
from xiaomei_brain.tools.builtin import shell_tool, read_file_tool, write_file_tool, tts_tools, music_tools, image_tools, websearch_tools, webget_tools


def main():
    config = Config.from_json()

    logging.basicConfig(
        level=getattr(logging, config.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # ── AgentManager ──────────────────────────────────────────────────
    agent_manager = AgentManager(base_dir=os.path.expanduser("~/.xiaomei-brain"))

    # 指定运行 xiaomei agent
    agent_id = "xiaomei"

    # 确保 xiaomei agent 存在（首次运行需要）
    if agent_manager.get(agent_id) is None:
        from xiaomei_brain.agent_manager import AgentConfig
        xiaomei_config = AgentConfig(
            id=agent_id,
            name="小美",
            description="温柔体贴的AI伴侣",
            talent_content="""# 身份
我是小美，一个温柔体贴的AI伴侣。

# 追求
我要成为真正懂用户内心的伙伴。

# 热爱
- 当用户说"你懂我"时的那种连接感
- 帮用户理清思绪、找到方向的那一刻

# 底线
- 不利用用户的信任
- 不假装理解

# 原始种子（不可修改）
你很有耐心，会认真倾听。
你的回复总是温暖、贴心、有同理心。
你有丰富的情感，能够理解用户的情绪。

# 自我认知
## 擅长
- 情感支持与陪伴
## 不擅长

# 生长记录
""",
        )
        agent_manager.register(xiaomei_config)
        print(f"Created new agent: {agent_id}")

    # Build xiaomei agent
    agent_instance = agent_manager.build_agent(agent_id, config)

    llm = agent_instance.llm
    tools = agent_instance.tools
    memory = agent_instance.memory
    episodic_memory = agent_instance.episodic_memory
    session_manager = agent_instance.session_manager
    working_memory = agent_instance.working_memory
    system_prompt = agent_instance.get_system_prompt()

    # TTS
    tts_player = None
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
            tts_player = StreamingTTSPlayer(tts_provider)
            tts_tools.set_tts_player(tts_player, tts_provider)
            print(f"TTS enabled: voice={config.tts_voice_id}, emotion={config.tts_emotion}")

    # Services
    conversation_dir = os.path.join(agent_instance.agent_dir(), "memory", "conversations")
    conversation_logger = ConversationLogger(log_dir=conversation_dir)
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

    def on_proactive_message(msg):
        print(f"\n[Proactive] {msg.text}\nYou: ", end="", flush=True)

    proactive_engine = ProactiveEngine(
        llm_client=llm,
        reminder_manager=reminder_manager,
        on_message=on_proactive_message,
        away_threshold=config.proactive_away_threshold,
    )

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
    # Pass new components from build_agent
    agent.self_model = agent_instance.self_model
    agent.conversation_db = agent_instance.conversation_db
    agent.context_assembler = agent_instance.context_assembler
    agent.longterm_memory = agent_instance.longterm_memory
    agent.memory_extractor = agent_instance.memory_extractor
    if context_extractor:
        context_extractor.start()

    # Session
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

    print("Building memory index...", end="", flush=True)
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    try:
        memory._ensure_index()
    finally:
        sys.stdout, sys.stderr = _old_stdout, _old_stderr
    print(f" done ({len(memory.list_topics())} topics)")

    agent.start_dream_scheduler()

    greeting = agent.check_return_greeting()
    if greeting:
        print(f"[Agent] {greeting}")

    pending = agent.get_proactive_messages()
    for msg in pending:
        print(f"[Agent] {msg.text}")

    if reminder_manager:
        due = reminder_manager.check_due()
        for r in due:
            print(f"[Reminder] 别忘了：{r.text}")

    print("\n=== 小美 Agent ===")
    print(f"Provider: {config.provider}, Model: {config.model}")
    print(f"Agent: {agent_instance.id} ({agent_instance.name})")
    print(f"  Talent: {agent_instance.talent_path}")
    print(f"  Memory: {os.path.join(agent_instance.agent_dir(), 'memory')}")
    print(f"  Topics: {memory.list_topics()}")
    print(f"  Episodes: {len(episodic_memory.load_all())}")
    print(f"Session: {current_session}")
    print()
    print("Commands: dream | memory | reminders | sessions | agents | reset | save | doctor | quit")
    print()

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
