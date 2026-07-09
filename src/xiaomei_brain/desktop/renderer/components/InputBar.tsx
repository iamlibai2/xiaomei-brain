import React, { useState, useRef } from "react";
import { useGateway } from "../hooks/useGateway";

interface Props {
  gateway: ReturnType<typeof useGateway>;
}

export function InputBar({ gateway }: Props) {
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const handleSend = async () => {
    const text = input.trim();
    if (!text) return;

    setInput("");
    setSending(true);
    await gateway.sendMessage(text);
    setSending(false);
    inputRef.current?.focus();
  };

  const handleAbort = async () => {
    await gateway.abortMessage();
    setSending(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="input-bar">
      <textarea
        ref={inputRef}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"
        rows={2}
        disabled={gateway.conn.status !== "connected"}
      />
      <div className="input-buttons">
        {sending ? (
          <button className="btn-abort" onClick={handleAbort}>
            中断
          </button>
        ) : (
          <button
            className="btn-send"
            onClick={handleSend}
            disabled={!input.trim() || gateway.conn.status !== "connected"}
          >
            发送
          </button>
        )}
      </div>
    </div>
  );
}
