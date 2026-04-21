import os, logging, time
os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')
os.environ.setdefault('HF_HUB_OFFLINE', '1')
logging.basicConfig(level=logging.INFO, format='%(message)s')

from xiaomei_brain.config import Config
from xiaomei_brain.llm import LLMClient
from xiaomei_brain.agent.core import Agent
from xiaomei_brain.memory.self_model import SelfModel
from xiaomei_brain.memory.conversation_db import ConversationDB
from xiaomei_brain.memory.dag import DAGSummaryGraph
from xiaomei_brain.memory.context_assembler import ContextAssembler
from xiaomei_brain.memory.longterm import LongTermMemory
from xiaomei_brain.memory.extractor import MemoryExtractor
from xiaomei_brain.tools.registry import ToolRegistry
from xiaomei_brain.tools.builtin.dag_expand import create_dag_tools

config = Config.from_json()
llm = LLMClient(config.model, config.api_key, config.base_url, config.provider)

base = os.path.expanduser('~/.xiaomei-brain/agents/xiaomei')
db_path = '/tmp/test_trace.db'
import shutil
shutil.rmtree(os.path.dirname(db_path), ignore_errors=True)
os.makedirs(os.path.dirname(db_path), exist_ok=True)

self_model = SelfModel.load(os.path.join(base, 'talent.md'))
conversation_db = ConversationDB(db_path)
dag = DAGSummaryGraph(db_path, llm_client=llm)
longterm_memory = LongTermMemory(db_path)
memory_extractor = MemoryExtractor(llm, longterm_memory, conversation_db)
context_assembler = ContextAssembler(conversation_db, dag, self_model, longterm_memory)

tools = ToolRegistry()
for dag_tool in create_dag_tools(dag, longterm_memory):
    tools.register(dag_tool)

agent = Agent(llm=llm, tools=tools, system_prompt='', max_steps=10)
agent.self_model = self_model
agent.conversation_db = conversation_db
agent.context_assembler = context_assembler
agent.longterm_memory = longterm_memory
agent.memory_extractor = memory_extractor
agent.user_id = 'global'

print('=== 第一次对话: 你好 ===')
t0 = time.time()
for chunk in agent.stream('你好'):
    pass
print(f'\n[总耗时] {time.time()-t0:.1f}s')