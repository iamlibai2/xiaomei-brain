"""简单的 WebSocket 测试脚本"""

import asyncio
import json
import websockets


async def test_simple():
    uri = "ws://127.0.0.1:8765/ws"
    print(f"Connecting to {uri}")

    try:
        async with websockets.connect(uri) as websocket:
            # 发送 session_start
            start_msg = {
                "type": "session_start",
                "session_id": "test-session",
                "agent_id": "xiaomei"
            }
            await websocket.send(json.dumps(start_msg))
            print("Sent session_start")

            # 接收响应
            try:
                response = await websocket.recv()
                print(f"Received: {response}")
            except websockets.exceptions.ConnectionClosed:
                print("Connection closed after session_start")
                return

            # 发送聊天消息
            chat_msg = {
                "type": "chat",
                "content": "你好",
                "session_id": "test-session"
            }
            await websocket.send(json.dumps(chat_msg))
            print("Sent chat message")

            # 接收响应
            try:
                response = await websocket.recv()
                print(f"Received: {response}")
            except websockets.exceptions.ConnectionClosed:
                print("Connection closed after chat")
                return

            # 发送 session_end
            end_msg = {
                "type": "session_end",
                "session_id": "test-session"
            }
            await websocket.send(json.dumps(end_msg))
            print("Sent session_end")

            # 等待最后响应
            try:
                response = await websocket.recv()
                print(f"Received: {response}")
            except websockets.exceptions.ConnectionClosed:
                print("Connection closed normally")

            print("✅ Test completed!")

    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    asyncio.run(test_simple())