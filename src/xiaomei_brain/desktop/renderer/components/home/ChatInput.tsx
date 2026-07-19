import { useRef } from "react";
import { useTranslation } from "react-i18next";
import { useCoreStore } from "../../store";
import { Icon } from "../ui";

interface ChatInputProps {
  onSend: (text: string) => void;
  sending: boolean;
  onAbort: () => void;
}

export function ChatInput({ onSend, sending, onAbort }: ChatInputProps) {
  const { t } = useTranslation();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const input = useCoreStore((s) => s.draftByAgent[s.activeAgentId || ""] || "");
  const setInput = useCoreStore((s) => s.setDraft);
  const connected = useCoreStore((s) => {
    const agentId = s.activeAgentId;
    if (!agentId) return false;
    return s.connectionByAgent[agentId]?.status === "connected";
  });

  const handleSend = () => {
    const text = input.trim();
    if (!text) return;
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
        placeholder={t("home.inputPlaceholder")}
        rows={2}
        disabled={!connected}
      />
      <div className="chat-input-toolbar">
        <div className="chat-input-toolbar-left">
          <button className="chat-input-btn" title={t("home.addAttachment")}>
            <Icon name="plus" size={18} />
          </button>
        </div>
        <div className="chat-input-toolbar-right">
          <button className="chat-input-dropdown" title={t("home.mode")}>
            {t("home.modeAuto")}
          </button>
          <button className="chat-input-btn" title={t("home.voiceInput")}>
            <Icon name="microphone" size={18} />
          </button>
          {sending ? (
            <button className="chat-input-abort" onClick={onAbort}>
              {t("home.abort")}
            </button>
          ) : (
            <button
              className="chat-input-send"
              onClick={handleSend}
              disabled={!input.trim() || !connected}
              title={t("home.send")}
            >
              <Icon name="arrow-up" size={16} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
