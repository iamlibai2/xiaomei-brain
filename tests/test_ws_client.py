"""WebSocket 客户端测试脚本 - 与 xiaomei-brain 对话"""

import asyncio
import json
import sys


async def chat(host: str = "127.0.0.1", port: int = 8765, agent_id: str = "xiaomei"):
    """Connect to WebSocket and chat."""
    import websockets

    uri = f"ws://{host}:{port}/ws"
    print(f"Connecting to {uri}...")
    print(f"Agent: {agent_id}")
    print("-" * 50)

    try:
        async with websockets.connect(uri, ping_interval=None) as ws:
            # Start session
            await ws.send(json.dumps({
                "type": "session_start",
                "session_id": "test-session",
                "agent_id": agent_id,
            }))
            response = await ws.recv()
            print(f"[Server] {response[:100]}...")

            print("-" * 50)
            print("Connected! Type your message (or 'quit' to exit):")
            print("-" * 50)

            # Chat loop
            while True:
                # Read user input
                user_input = input("\nYou: ").strip()
                if not user_input:
                    continue
                if user_input.lower() in ("quit", "exit"):
                    break

                # Send message
                await ws.send(json.dumps({
                    "type": "chat",
                    "content": user_input,
                    "session_id": "test-session",
                }))

                # Receive response (streaming)
                full_response = ""
                try:
                    while True:
                        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=60.0))
                        msg_type = msg.get("type")

                        if msg_type == "text_chunk":
                            # Stream chunk
                            chunk = msg.get("content", "")
                            print(chunk, end="", flush=True)
                            sys.stdout.flush()
                            full_response += chunk
                        elif msg_type == "text_done":
                            print()  # New line
                            break
                        elif msg_type == "error":
                            print(f"\n[Error] {msg.get('message')}")
                            break
                        elif msg_type == "tool_call_start":
                            print(f"\n[Tool] {msg.get('name')}() called", flush=True)
                        elif msg_type == "tool_call_result":
                            result = str(msg.get('result', ''))[:100]
                            print(f"[Tool] Result: {result}...", flush=True)
                        elif msg_type == "CHAT_START":
                            # Ignore, waiting for chunks
                            pass
                        elif msg_type == "MsgType.SESSION_STARTED":
                            # Ignore, already started
                            pass
                        else:
                            # Ignore other message types
                            pass

                except asyncio.TimeoutError:
                    print("\n[Timeout waiting for response]")
                except websockets.exceptions.ConnectionClosed:
                    print("\n[Connection closed by server]")
                    break

            # End session
            try:
                await ws.send(json.dumps({
                    "type": "session_end",
                    "session_id": "test-session",
                }))
            except websockets.exceptions.ConnectionClosed:
                pass

    except websockets.exceptions.ConnectionClosed as e:
        print(f"\n[Connection closed: {e}]")
    except KeyboardInterrupt:
        print("\n\nInterrupted!")
    except Exception as e:
        print(f"\n[Error: {e}]")
        raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Chat with xiaomei-brain via WebSocket")
    parser.add_argument("--host", default="127.0.0.1", help="WebSocket host")
    parser.add_argument("--port", type=int, default=8765, help="WebSocket port")
    parser.add_argument("--agent", default="xiaomei", help="Agent ID (xiaomei, xiaoming, default)")
    parser.add_argument("--no-input", action="store_true", help="Non-interactive mode (for testing)")

    args = parser.parse_args()

    if args.no_input:
        print("Non-interactive mode not implemented. Run without --no-input.")
        sys.exit(1)

    try:
        asyncio.run(chat(args.host, args.port, args.agent))
    except KeyboardInterrupt:
        print("\n\nBye!")
