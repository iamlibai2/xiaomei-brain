"""WebSocket 客户端自动测试脚本"""

import asyncio
import json
import sys
import websockets


async def test_chat(host: str = "127.0.0.1", port: int = 8765):
    """Auto test chat with predefined messages."""
    uri = f"ws://{host}:{port}/ws"
    print(f"Connecting to {uri}...")

    async with websockets.connect(uri) as websocket:
        # Start session
        await websocket.send(json.dumps({
            "type": "session_start",
            "session_id": "test-session",
            "agent_id": "xiaomei",
        }))
        response = await websocket.recv()
        print(f"Session started: {json.loads(response)['type']}")

        # Test messages
        test_messages = [
            "你好",
            "你能帮我做什么？",
            "1 + 1 = ?",
            "再见"
        ]

        for msg in test_messages:
            print(f"\n>>> Sending: {msg}")
            await websocket.send(json.dumps({
                "type": "chat",
                "content": msg,
                "session_id": "test-session",
            }))

            # Collect response chunks
            full_response = ""
            chunk_count = 0
            while True:
                try:
                    response = await websocket.recv()
                    msg_data = json.loads(response)
                    msg_type = msg_data.get("type")

                    if msg_type == "text_chunk":
                        chunk = msg_data.get("content", "")
                        print(chunk, end="", flush=True)
                        full_response += chunk
                        chunk_count += 1
                    elif msg_type == "text_done":
                        print(f"\n[Received {chunk_count} chunks]")
                        break
                    elif msg_type == "error":
                        print(f"\n[Error] {msg_data.get('message')}")
                        break
                except websockets.exceptions.ConnectionClosed:
                    print("\n[Connection closed]")
                    break

        # End session
        print("\n>>> Ending session...")
        await websocket.send(json.dumps({
            "type": "session_end",
            "session_id": "test-session",
        }))

        print("✅ Test completed!")


if __name__ == "__main__":
    try:
        asyncio.run(test_chat())
    except KeyboardInterrupt:
        print("\nTest interrupted.")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)