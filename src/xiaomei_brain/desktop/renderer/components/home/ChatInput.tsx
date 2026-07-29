import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useCoreStore } from "../../store";
import { Icon, SelectMenu } from "../ui";
import type { ChatAttachment, ModelConfigSnapshot } from "../../types";

const MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024;
const MAX_TOTAL_ATTACHMENT_BYTES = 8 * 1024 * 1024;
const IMAGE_TYPES: Record<string, string> = {
  ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
  ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
};
const OFFICE_TYPES: Record<string, string> = {
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
};
const TEXT_EXTENSIONS = new Set([
  ".txt", ".md", ".markdown", ".json", ".jsonl", ".yaml", ".yml", ".toml",
  ".csv", ".tsv", ".xml", ".html", ".htm", ".css", ".js", ".jsx", ".ts",
  ".tsx", ".py", ".java", ".kt", ".kts", ".c", ".h", ".cc", ".cpp", ".hpp",
  ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".sql", ".sh", ".bash", ".zsh",
  ".ps1", ".bat", ".cmd", ".ini", ".cfg", ".conf", ".log",
]);

interface ChatInputProps {
  onSend: (text: string) => void;
  sending: boolean;
  onAbort: () => void;
}

export function ChatInput({ onSend, sending, onAbort }: ChatInputProps) {
  const { t } = useTranslation();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [dragging, setDragging] = useState(false);
  const [modelSnapshot, setModelSnapshot] = useState<ModelConfigSnapshot | null>(null);
  const [modelBusy, setModelBusy] = useState(false);
  const [modelError, setModelError] = useState("");
  const activeAgentId = useCoreStore((s) => s.activeAgentId);
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
  const addAttachments = useCoreStore((s) => s.addAttachments);
  const setAttachmentError = useCoreStore((s) => s.setAttachmentError);
  const removeAttachment = useCoreStore((s) => s.removeAttachment);
  const connected = useCoreStore((s) => {
    const agentId = s.activeAgentId;
    if (!agentId) return false;
    return s.connectionByAgent[agentId]?.status === "connected";
  });

  const loadModels = useCallback(async () => {
    if (!activeAgentId || !connected) {
      setModelSnapshot(null);
      return;
    }
    try {
      const response = await window.gateway.getModelConfig({ agentId: activeAgentId });
      if (response.error) throw new Error(response.error.message);
      setModelSnapshot(response.result as unknown as ModelConfigSnapshot);
      setModelError("");
    } catch (error) {
      setModelError(String(error instanceof Error ? error.message : error));
    }
  }, [activeAgentId, connected]);

  useEffect(() => {
    void loadModels();
  }, [loadModels]);

  useEffect(() => {
    const handleModelChange = (event: Event) => {
      const detail = (event as CustomEvent<{ agentId?: string }>).detail;
      if (!detail?.agentId || detail.agentId === activeAgentId) void loadModels();
    };
    window.addEventListener("xiaomei:model-selection-changed", handleModelChange);
    return () => window.removeEventListener("xiaomei:model-selection-changed", handleModelChange);
  }, [activeAgentId, loadModels]);

  const modelOptions = useMemo(() => (
    modelSnapshot?.providers.flatMap((provider) => provider.models.map((model) => ({
      value: `${provider.id}/${model.id}`,
      label: model.name || model.id,
      description: provider.id,
    }))) || []
  ), [modelSnapshot]);

  const selectModel = async (primary: string) => {
    if (!activeAgentId || !modelSnapshot || !primary) return;
    setModelBusy(true);
    setModelError("");
    try {
      const response = await window.gateway.setModelSelection({
        agentId: activeAgentId,
        primary,
        vision: modelSnapshot.selection.vision || "",
        baseHash: modelSnapshot.hashes.agent,
      });
      if (response.error) throw new Error(response.error.message);
      await loadModels();
      window.dispatchEvent(new CustomEvent(
        "xiaomei:model-selection-changed",
        { detail: { agentId: activeAgentId } },
      ));
    } catch (error) {
      setModelError(String(error instanceof Error ? error.message : error));
    } finally {
      setModelBusy(false);
    }
  };

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

  const handleDrop = async (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    if (!connected || sending) return;
    const files = Array.from(event.dataTransfer.files);
    if (!files.length) return;
    if (attachments.length + files.length > 4) {
      setAttachmentError("一次最多添加 4 个附件");
      return;
    }
    const totalSize = attachments.reduce((sum, item) => sum + item.size, 0)
      + files.reduce((sum, file) => sum + file.size, 0);
    if (totalSize > MAX_TOTAL_ATTACHMENT_BYTES) {
      setAttachmentError("附件合计不能超过 8 MB");
      return;
    }
    try {
      const dropped: ChatAttachment[] = [];
      for (const file of files) dropped.push(await droppedAttachment(file));
      addAttachments(dropped);
    } catch (error) {
      setAttachmentError(error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <div
      className={`chat-input-container ${dragging ? "drag-active" : ""}`}
      onDragEnter={(event) => {
        if (!connected || sending || !event.dataTransfer.types.includes("Files")) return;
        event.preventDefault();
        setDragging(true);
      }}
      onDragOver={(event) => {
        if (!connected || sending || !event.dataTransfer.types.includes("Files")) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
      }}
      onDragLeave={(event) => {
        if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
        setDragging(false);
      }}
      onDrop={(event) => { void handleDrop(event); }}
    >
      {dragging && <div className="attachment-drop-hint">松开以添加附件</div>}
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
      {modelError && <div className="chat-model-error">{modelError}</div>}
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
          <SelectMenu
            className="chat-model-select"
            placement="up"
            value={modelSnapshot?.selection.primary || ""}
            options={modelOptions}
            placeholder={modelBusy ? "切换中…" : "选择模型"}
            searchable={modelOptions.length > 6}
            searchPlaceholder="搜索模型"
            emptyText="没有可用模型"
            disabled={!connected || sending || modelBusy || modelOptions.length === 0}
            onChange={(value) => void selectModel(value)}
          />
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

async function droppedAttachment(file: File): Promise<ChatAttachment> {
  const extensionIndex = file.name.lastIndexOf(".");
  const extension = extensionIndex >= 0 ? file.name.slice(extensionIndex).toLowerCase() : "";
  const imageMime = IMAGE_TYPES[extension];
  const officeMime = OFFICE_TYPES[extension];
  if (!imageMime && !officeMime && !TEXT_EXTENSIONS.has(extension)) {
    throw new Error(`暂不支持 ${file.name} 的文件类型`);
  }
  if (file.size === 0) throw new Error(`${file.name} 是空文件`);
  if (file.size > MAX_ATTACHMENT_BYTES) throw new Error(`${file.name} 超过 5 MB`);
  const dataBase64 = await readFileBase64(file);
  return {
    id: crypto.randomUUID(),
    name: file.name,
    mimeType: imageMime || officeMime || "text/plain",
    size: file.size,
    kind: imageMime ? "image" : officeMime ? "document" : "text",
    dataBase64,
  };
}

function readFileBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(`无法读取 ${file.name}`));
    reader.onload = () => {
      const result = typeof reader.result === "string" ? reader.result : "";
      const separator = result.indexOf(",");
      if (separator < 0) reject(new Error(`无法读取 ${file.name}`));
      else resolve(result.slice(separator + 1));
    };
    reader.readAsDataURL(file);
  });
}
