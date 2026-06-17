"""测试多轮对话 - 增加超时等待"""

import asyncio
import json
import websockets


async def test_conversation():
    uri = "ws://127.0.0.1:8765/ws"
    print(f"Connecting to {uri}...")

    async with websockets.connect(uri) as websocket:
        # session_start
        await websocket.send(json.dumps({
            "type": "session_start",
            "session_id": "test-session",
            "agent_id": "xiaomei",
        }))
        resp = await websocket.recv()
        print(f"[Session] {json.loads(resp)['type']}")

        conversation = [
            "你好",
            "你叫什么名字？",
            "1+1等于几？",
        ]

        for msg in conversation:
            print(f"\n>>> 发送: {msg}")
            await websocket.send(json.dumps({
                "type": "chat",
                "content": msg,
                "session_id": "test-session",
            }))

            # 收集所有响应，增加超时
            full = ""
            try:
                while True:
                    resp = await asyncio.wait_for(websocket.recv(), timeout=30.0)
                    data = json.loads(resp)
                    msg_type = data.get("type")

                    if msg_type == "text_chunk":
                        chunk = data.get("content", "")
                        full += chunk
                    elif msg_type == "text_done":
                        print(f"<<< 回复: {full[:200]}...")
                        print(f"    (共 {len(full)} 字符)")
                        break
                    elif msg_type == "error":
                        print(f"[Error] {data.get('message')}")
                        break
                    elif msg_type == "tool_call_start":
                        print(f"   [调用工具: {data.get('name')}]")
                    elif msg_type == "CHAT_START":
                        print(f"   [Chat Start: {data.get('message_id')}]")
                    else:
                        print(f"   [Other: {msg_type}]")

            except asyncio.TimeoutError:
                print(f"   (30秒内无响应，已接收: {full[:100]}...)")
            except websockets.exceptions.ConnectionClosed:
                print("   (连接已关闭)")
                break

            await asyncio.sleep(0.5)

        # session_end
        await websocket.send(json.dumps({
            "type": "session_end",
            "session_id": "test-session",
        }))
        print("\n✅ Test completed!")


if __name__ == "__main__":
    asyncio.run(test_conversation())
