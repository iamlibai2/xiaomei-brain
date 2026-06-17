"""WebSocket 客户端测试 - 等待完整响应"""

import asyncio
import json
import websockets


async def test():
    uri = "ws://127.0.0.1:8765/ws"
    print(f"Connecting to {uri}...")

    async with websockets.connect(uri) as ws:
        # Session start
        await ws.send(json.dumps({
            "type": "session_start",
            "session_id": "test",
            "agent_id": "xiaomei"
        }))
        resp = await ws.recv()
        print(f"[Session] {resp[:80]}...")

        # Chat
        await ws.send(json.dumps({
            "type": "chat",
            "content": "你好，你叫什么名字？",
            "session_id": "test"
        }))

        # Collect response
        full = ""
        while True:
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=30.0)
                data = json.loads(resp)
                t = data.get("type")

                if t == "text_chunk":
                    full += data.get("content", "")
                    print(f"[chunk] {data.get('content', '')}", end="", flush=True)
                elif t == "text_done":
                    print(f"\n[Done] Total: {len(full)} chars")
                    print(f"[Response] {full[:200]}...")
                    break
                elif t == "error":
                    print(f"\n[Error] {data.get('message')}")
                    break
                else:
                    print(f"[{t}]", end="", flush=True)
            except asyncio.TimeoutError:
                print(f"\n[Timeout] Received: {full[:100]}...")
                break

        # End
        await ws.send(json.dumps({"type": "session_end", "session_id": "test"}))
        print("\n✅ Done!")


if __name__ == "__main__":
    asyncio.run(test())
