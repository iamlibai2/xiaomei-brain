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
  const pendingAttachments = useCoreStore((s) => {
    const agentId = s.activeAgentId || "";
    const sessionId = agentId ? s.activeSessionByAgent[agentId] : null;
    return s.attachmentsByConversation[`${agentId}\u0000${sessionId || "new"}`];
  });
  const attachments = pendingAttachments || [];
  const attachmentError = useCoreStore((s) => {
    const agentId = s.activeAgentId || "";
    const sessionId = agentId ? s.activeSessionByAgent[agentId] : null;
    return s.attachmentErrorByConversation[`${agentId}\u0000${sessionId || "new"}`] || "";
  });
  const pickAttachments = useCoreStore((s) => s.pickAttachments);
  const removeAttachment = useCoreStore((s) => s.removeAttachment);
  const connected = useCoreStore((s) => {
    const agentId = s.activeAgentId;
    if (!agentId) return false;
    return s.connectionByAgent[agentId]?.status === "connected";
  });

  const handleSend = () => {
    const text = input.trim();
    if (!text && attachments.length === 0) return;
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
      {attachments.length > 0 && (
        <div className="attachment-preview-list">
          {attachments.map((attachment) => (
            <div className="attachment-preview" key={attachment.id}>
              {attachment.kind === "image" && attachment.dataBase64 ? (
                <img
                  src={`data:${attachment.mimeType};base64,${attachment.dataBase64}`}
                  alt={attachment.name}
                />
              ) : (
                <span className="attachment-file-icon">{attachment.name.split(".").pop()?.slice(0, 4).toUpperCase() || "FILE"}</span>
              )}
              <div className="attachment-preview-meta">
                <span>{attachment.name}</span>
                <small>{formatFileSize(attachment.size)}</small>
              </div>
              <button type="button" onClick={() => removeAttachment(attachment.id)} title={t("home.removeAttachment")}>×</button>
            </div>
          ))}
        </div>
      )}
      {attachmentError && <div className="attachment-error">{attachmentError}</div>}
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
          <button
            type="button"
            className="chat-input-btn"
            title={t("home.addAttachment")}
            onClick={() => { void pickAttachments(); }}
            disabled={!connected || sending}
          >
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
              disabled={(!input.trim() && attachments.length === 0) || !connected}
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

function formatFileSize(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}
