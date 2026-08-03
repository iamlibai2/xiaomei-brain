import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useCoreStore } from "../../store";
import { Icon } from "../ui";
import type {
  ChatAttachment,
  ModelConfigSnapshot,
  ModelThinkingSelection,
} from "../../types";
import { ModelQuickMenu } from "./ModelQuickMenu";

const MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024;
const MAX_TOTAL_ATTACHMENT_BYTES = 8 * 1024 * 1024;
const MAX_VIDEO_ATTACHMENT_BYTES = 20 * 1024 * 1024;
const MAX_VIDEO_TOTAL_ATTACHMENT_BYTES = 32 * 1024 * 1024;
const IMAGE_TYPES: Record<string, string> = {
  ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
  ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
};
const VIDEO_TYPES: Record<string, string> = {
  ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
  ".webm": "video/webm", ".mkv": "video/x-matroska",
  ".avi": "video/x-msvideo", ".mpeg": "video/mpeg", ".mpg": "video/mpeg",
};
const OFFICE_TYPES: Record<string, string> = {
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  ".pdf": "application/pdf",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
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
  const recorderRef = useRef<MediaRecorder | null>(null);
  const microphoneStreamRef = useRef<MediaStream | null>(null);
  const [dragging, setDragging] = useState(false);
  const [recording, setRecording] = useState(false);
  const [mediaBusy, setMediaBusy] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState("");
  const [modelSnapshot, setModelSnapshot] = useState<ModelConfigSnapshot | null>(null);
  const [modelBusy, setModelBusy] = useState(false);
  const [modelError, setModelError] = useState("");
  const activeAgentId = useCoreStore((s) => s.activeAgentId);
  const input = useCoreStore((s) => {
    const agentId = s.activeAgentId || "";
    const sessionId = agentId ? s.activeSessionByAgent[agentId] : null;
    return s.draftByConversation[`${agentId}\u0000${sessionId || "new"}`] || "";
  });
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

  useEffect(() => () => {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    microphoneStreamRef.current?.getTracks().forEach((track) => track.stop());
  }, []);

  useEffect(() => window.gateway.onEvent((raw) => {
    if (
      raw.agentId !== activeAgentId
      || raw.event !== "embodiment.audio.input.completed"
    ) return;
    const payload = raw.data as Record<string, unknown>;
    if (payload.status === "failed") {
      setAttachmentError(
        typeof payload.error === "string"
          ? payload.error
          : t("home.voiceRecognitionFailed"),
      );
    }
    setVoiceStatus("");
  }), [activeAgentId, setAttachmentError, t]);

  useEffect(() => {
    const handleModelChange = (event: Event) => {
      const detail = (event as CustomEvent<{ agentId?: string }>).detail;
      if (!detail?.agentId || detail.agentId === activeAgentId) void loadModels();
    };
    window.addEventListener("xiaomei:model-selection-changed", handleModelChange);
    return () => window.removeEventListener("xiaomei:model-selection-changed", handleModelChange);
  }, [activeAgentId, loadModels]);

  const selectModel = async (
    primary: string,
    thinking?: ModelThinkingSelection,
  ) => {
    if (!activeAgentId || !modelSnapshot || !primary) return;
    setModelBusy(true);
    setModelError("");
    try {
      const response = await window.gateway.setModelSelection({
        agentId: activeAgentId,
        primary,
        vision: modelSnapshot.selection.vision || "",
        thinking,
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
    const hasVideo = attachments.some((item) => item.kind === "video")
      || files.some((file) => VIDEO_TYPES[fileExtension(file.name)]);
    const totalLimit = hasVideo
      ? MAX_VIDEO_TOTAL_ATTACHMENT_BYTES
      : MAX_TOTAL_ATTACHMENT_BYTES;
    if (totalSize > totalLimit) {
      setAttachmentError(`附件合计不能超过 ${totalLimit / 1024 / 1024} MB`);
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

  const toggleVoiceRecording = async () => {
    if (recording) {
      recorderRef.current?.stop();
      return;
    }
    if (!activeAgentId || !connected || sending || mediaBusy) return;
    setAttachmentError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      const preferred = [
        "audio/webm;codecs=opus",
        "audio/ogg;codecs=opus",
      ].find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(
        stream,
        preferred ? { mimeType: preferred } : undefined,
      );
      const chunks: BlobPart[] = [];
      microphoneStreamRef.current = stream;
      recorderRef.current = recorder;
      recorder.addEventListener("dataavailable", (event) => {
        if (event.data.size > 0) chunks.push(event.data);
      });
      recorder.addEventListener("stop", () => {
        setRecording(false);
        stream.getTracks().forEach((track) => track.stop());
        microphoneStreamRef.current = null;
        recorderRef.current = null;
        const blob = new Blob(chunks, {
          type: recorder.mimeType || "audio/webm",
        });
        if (!blob.size) {
          setAttachmentError(t("home.voiceEmpty"));
          return;
        }
        if (blob.size > MAX_ATTACHMENT_BYTES) {
          setAttachmentError(t("home.voiceTooLarge"));
          return;
        }
        setVoiceStatus(t("home.voiceProcessing"));
        setMediaBusy(true);
        void blobToBase64(blob)
          .then((dataBase64) => window.gateway.sendVoice({
            agentId: activeAgentId,
            dataBase64,
            mimeType: (blob.type || "audio/webm").split(";", 1)[0],
            size: blob.size,
            clientRequestId: crypto.randomUUID(),
          }))
          .then((response) => {
            if (response.error) throw new Error(response.error.message);
          })
          .catch((error) => {
            setVoiceStatus("");
            setAttachmentError(
              error instanceof Error ? error.message : String(error),
            );
          })
          .finally(() => setMediaBusy(false));
      }, { once: true });
      recorder.start(250);
      setRecording(true);
      setVoiceStatus(t("home.voiceRecording"));
    } catch (error) {
      setVoiceStatus("");
      setAttachmentError(
        error instanceof Error ? error.message : t("home.mediaPermissionDenied"),
      );
    }
  };

  const captureCamera = async () => {
    if (!connected || sending || mediaBusy || attachments.length >= 4) return;
    setAttachmentError("");
    setMediaBusy(true);
    let stream: MediaStream | null = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 } },
      });
      const video = document.createElement("video");
      video.srcObject = stream;
      video.muted = true;
      video.playsInline = true;
      await video.play();
      if (!video.videoWidth || !video.videoHeight) {
        throw new Error(t("home.cameraUnavailable"));
      }
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      const context = canvas.getContext("2d");
      if (!context) throw new Error(t("home.cameraUnavailable"));
      context.drawImage(video, 0, 0);
      const blob = await canvasToBlob(canvas, "image/jpeg", 0.9);
      if (blob.size > MAX_ATTACHMENT_BYTES) {
        throw new Error(t("home.cameraImageTooLarge"));
      }
      addAttachments([{
        id: crypto.randomUUID(),
        name: `camera-${new Date().toISOString().replace(/[:.]/g, "-")}.jpg`,
        mimeType: "image/jpeg",
        size: blob.size,
        kind: "image",
        dataBase64: await blobToBase64(blob),
      }]);
    } catch (error) {
      setAttachmentError(
        error instanceof Error ? error.message : t("home.mediaPermissionDenied"),
      );
    } finally {
      stream?.getTracks().forEach((track) => track.stop());
      setMediaBusy(false);
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
      {voiceStatus && <div className="embodiment-media-status">{voiceStatus}</div>}
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
          <ModelQuickMenu
            snapshot={modelSnapshot}
            busy={modelBusy}
            disabled={!connected || sending || modelBusy}
            onApply={selectModel}
          />
          <button
            type="button"
            className={`chat-input-btn ${recording ? "is-recording" : ""}`}
            title={recording ? t("home.stopVoiceInput") : t("home.voiceInput")}
            onClick={() => { void toggleVoiceRecording(); }}
            disabled={!recording && (!connected || sending || mediaBusy)}
          >
            <Icon name="microphone" size={18} />
          </button>
          <button
            type="button"
            className="chat-input-btn"
            title={t("home.cameraCapture")}
            onClick={() => { void captureCamera(); }}
            disabled={!connected || sending || mediaBusy || attachments.length >= 4}
          >
            <Icon name="camera" size={18} />
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
  const extension = fileExtension(file.name);
  const imageMime = IMAGE_TYPES[extension];
  const videoMime = VIDEO_TYPES[extension];
  const officeMime = OFFICE_TYPES[extension];
  if (!imageMime && !videoMime && !officeMime && !TEXT_EXTENSIONS.has(extension)) {
    throw new Error(`暂不支持 ${file.name} 的文件类型`);
  }
  if (file.size === 0) throw new Error(`${file.name} 是空文件`);
  const itemLimit = videoMime ? MAX_VIDEO_ATTACHMENT_BYTES : MAX_ATTACHMENT_BYTES;
  if (file.size > itemLimit) {
    throw new Error(`${file.name} 超过 ${itemLimit / 1024 / 1024} MB`);
  }
  const dataBase64 = await readFileBase64(file);
  return {
    id: crypto.randomUUID(),
    name: file.name,
    mimeType: imageMime || videoMime || officeMime || "text/plain",
    size: file.size,
    kind: imageMime ? "image" : videoMime ? "video" : officeMime ? "document" : "text",
    dataBase64,
  };
}

function fileExtension(name: string): string {
  const index = name.lastIndexOf(".");
  return index >= 0 ? name.slice(index).toLowerCase() : "";
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

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("无法读取媒体数据"));
    reader.onload = () => {
      const result = typeof reader.result === "string" ? reader.result : "";
      const separator = result.indexOf(",");
      if (separator < 0) reject(new Error("无法读取媒体数据"));
      else resolve(result.slice(separator + 1));
    };
    reader.readAsDataURL(blob);
  });
}

function canvasToBlob(
  canvas: HTMLCanvasElement,
  type: string,
  quality: number,
): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => blob ? resolve(blob) : reject(new Error("摄像头画面编码失败")),
      type,
      quality,
    );
  });
}
