import { useState, useRef } from "react";
import { useCoreStore } from "../../store";

interface ChatInputProps {
  onSend: (text: string) => void;
  sending: boolean;
  onAbort: () => void;
}

export function ChatInput({ onSend, sending, onAbort }: ChatInputProps) {
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const connected = useCoreStore((s) => s.connection.status === "connected");

  const handleSend = () => {
    const text = input.trim();
    if (!text) return;
    setInput("");
    onSend(text);
    textareaRef.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="chat-input-container">
      <textarea
        ref={textareaRef}
        className="chat-input-textarea"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="今天帮你做些什么？ @ 引用对话文件，/ 调用技能与指令"
        rows={2}
        disabled={!connected}
      />
      <div className="chat-input-toolbar">
        <div className="chat-input-toolbar-left">
          <button className="chat-input-btn" title="添加附件">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
          </button>
        </div>
        <div className="chat-input-toolbar-right">
          <button className="chat-input-dropdown" title="模式">
            自动 ▾
          </button>
          <button className="chat-input-btn" title="语音输入">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="9" y="2" width="6" height="12" rx="3" />
              <path d="M19 10v1a7 7 0 0 1-14 0v-1" />
              <line x1="12" y1="19" x2="12" y2="22" />
            </svg>
          </button>
          {sending ? (
            <button className="chat-input-abort" onClick={onAbort}>
              中断
            </button>
          ) : (
            <button
              className="chat-input-send"
              onClick={handleSend}
              disabled={!input.trim() || !connected}
              title="发送"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="12" y1="19" x2="12" y2="5" />
                <polyline points="5 12 12 5 19 12" />
              </svg>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
