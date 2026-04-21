import os, logging, time, sys
os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')
os.environ.setdefault('HF_HUB_OFFLINE', '1')
logging.basicConfig(level=logging.INFO, format='%(message)s')

# Redirect stdout to a file
sys.stdout = open('/home/iamlibai/workspace/claude-project/xiaomei-brain/test_result.txt', 'w')

from xiaomei_brain.config import Config
from xiaomei_brain.llm import LLMClient
from xiaomei_brain.memory.conversation_db import ConversationDB
from xiaomei_brain.memory.longterm import LongTermMemory
from xiaomei_brain.memory.extractor import MemoryExtractor

config = Config.from_json()
llm = LLMClient(config.model, config.api_key, config.base_url, config.provider)

db_path = '/tmp/t_fast.db'
import shutil; shutil.rmtree(os.path.dirname(db_path), ignore_errors=True)
os.makedirs(os.path.dirname(db_path), exist_ok=True)

conversation_db = ConversationDB(db_path)
longterm_memory = LongTermMemory(db_path)
memory_extractor = MemoryExtractor(llm, longterm_memory, conversation_db)

longterm_memory.store('用户叫张三', source='manual', user_id='test')
longterm_memory.store('用户喜欢吃川菜', source='manual', user_id='test')

print('=== 测试开始 ===')
t0 = time.time()
ids = memory_extractor.extract_every_turn('我叫李四，我喜欢游泳', '好的李四！', user_id='test')
t1 = time.time()
print(f'总耗时: {t1-t0:.1f}s, 提取了 {len(ids)} 条')
print('记忆列表:')
for r in longterm_memory.get_recent(10, user_id='test'):
    print(f'  {r["content"]}')
sys.stdout.flush()
sys.stdout.close()