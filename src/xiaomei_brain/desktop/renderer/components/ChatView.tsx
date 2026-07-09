import React, { useEffect, useRef, useState } from "react";
import { useGateway } from "../hooks/useGateway";
import { MessageBubble } from "./MessageBubble";

interface Props {
  gateway: ReturnType<typeof useGateway>;
  sessionId: string;
}

interface DisplayMessage {
  id: string;
  role: "user" | "agent" | "tool";
  content: string;
  streaming: boolean;
}

export function ChatView({ gateway, sessionId }: Props) {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);
  const streamRef = useRef("");
  const streamingMsgRef = useRef<DisplayMessage | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    const handler = (event: string, data: unknown) => {
      const d = data as Record<string, unknown>;
      const text = (d["text"] || "") as string;

      if (event === "chat.chunk") {
        streamRef.current += text;
        if (!streamingMsgRef.current) {
          streamingMsgRef.current = {
            id: "streaming-" + Date.now(),
            role: "agent",
            content: streamRef.current,
            streaming: true,
          };
        } else {
          streamingMsgRef.current.content = streamRef.current;
        }
        setMessages((prev) => {
          const filtered = prev.filter((m) => m.id !== streamingMsgRef.current?.id);
          return [...filtered, { ...streamingMsgRef.current! }];
        });
      } else if (event === "session.message") {
        if (streamingMsgRef.current) {
          streamingMsgRef.current.streaming = false;
          streamingMsgRef.current.content = text || streamRef.current;
          streamRef.current = "";
          streamingMsgRef.current = null;
        } else if (text) {
          setMessages((prev) => [
            ...prev,
            { id: "msg-" + Date.now(), role: "agent", content: text, streaming: false },
          ]);
        }
      } else if (event === "chat.error") {
        const err = (d["text"] || "Unknown error") as string;
        setMessages((prev) => [
          ...prev,
          { id: "err-" + Date.now(), role: "agent", content: `Error: ${err}`, streaming: false },
        ]);
        streamRef.current = "";
        streamingMsgRef.current = null;
      }
    };

    window.gateway.onEvent(handler);
    return () => {};
  }, []);

  return (
    <div className="chat-view">
      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-empty">
            <p>开始和 xiaomei-brain 对话</p>
          </div>
        )}
        {messages.map((m) => (
          <MessageBubble key={m.id} role={m.role} content={m.content} />
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
