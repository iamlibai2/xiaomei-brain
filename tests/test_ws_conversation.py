"""测试多轮对话"""

import asyncio
import json
import websockets


async def test_conversation():
    uri = "ws://127.0.0.1:8765/ws"
    print(f"Connecting to {uri}...")

    try:
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
                "你好，我是小明",
                "你叫什么名字？",
                "1+1等于几？",
                "再见"
            ]

            for msg in conversation:
                print(f"\n>>> 发送: {msg}")
                await websocket.send(json.dumps({
                    "type": "chat",
                    "content": msg,
                    "session_id": "test-session",
                }))

                # 收集所有响应
                full = ""
                try:
                    while True:
                        resp = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                        data = json.loads(resp)
                        msg_type = data.get("type")

                        if msg_type == "text_chunk":
                            chunk = data.get("content", "")
                            full += chunk
                            # 不打印流式输出，等完成
                        elif msg_type == "text_done":
                            print(f"<<< 回复: {full[:100]}...")
                            print(f"    (共 {len(full)} 字符)")
                            break
                        elif msg_type == "error":
                            print(f"[Error] {data.get('message')}")
                            break
                        elif msg_type == "tool_call_start":
                            print(f"   [调用工具: {data.get('name')}]")
                        elif msg_type == "tool_call_result":
                            result = data.get("result", "")
                            print(f"   [工具返回: {str(result)[:50]}...]")

                except asyncio.TimeoutError:
                    print("   (5秒内无响应，继续)")
                except websockets.exceptions.ConnectionClosed:
                    print("   (连接已关闭)")
                    break

                # 下一轮之间稍微等待
                await asyncio.sleep(0.5)

            # session_end
            await websocket.send(json.dumps({
                "type": "session_end",
                "session_id": "test-session",
            }))

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_conversation())
