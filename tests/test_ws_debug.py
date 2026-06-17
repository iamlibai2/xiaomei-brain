"""Debug WebSocket - print raw messages"""

import asyncio
import json
import websockets


async def test():
    uri = "ws://127.0.0.1:8765/ws"
    async with websockets.connect(uri) as ws:
        # Session
        await ws.send(json.dumps({"type": "session_start", "session_id": "test", "agent_id": "xiaomei"}))
        print(f"S: {await ws.recv()}")

        # Chat
        await ws.send(json.dumps({"type": "chat", "content": "你好", "session_id": "test"}))

        # Collect all
        for i in range(20):
            msg = await asyncio.wait_for(ws.recv(), timeout=10.0)
            data = json.loads(msg)
            print(f"[{i}] type={data.get('type')}, content={repr(data.get('content', '')[:100] if data.get('content') else '')}")

        # End
        await ws.send(json.dumps({"type": "session_end", "session_id": "test"}))


if __name__ == "__main__":
    asyncio.run(test())
