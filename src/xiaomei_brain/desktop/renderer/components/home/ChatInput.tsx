import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import i18n from "../../i18n";
import { useCoreStore } from "../../store";
import { Icon } from "../ui";
import type {
  ChatArtifactReference,
  ChatAttachment,
  ChatInvocationSelection,
  ModelConfigSnapshot,
  ModelThinkingSelection,
} from "../../types";
import {
  ArtifactMentionMenu,
  type ArtifactMentionMenuHandle,
} from "./ArtifactMentionMenu";
import { ModelQuickMenu } from "./ModelQuickMenu";
import {
  SlashInvocationMenu,
  type SlashInvocationMenuHandle,
} from "./SlashInvocationMenu";
import { VoiceOrb, type VoiceOrbPhase } from "./VoiceOrb";
import {
  DESKTOP_SPEECH_FINISHED,
  DESKTOP_SPEECH_STARTED,
  stopDesktopSpeech,
} from "../../embodiment";
import { setLiveVoiceActive } from "../../message-sound";

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
  onSend: (text: string, artifactReferences?: ChatArtifactReference[]) => void;
  sending: boolean;
  onAbort: () => void;
  continueTurnId?: string;
  onContinue: (turnId: string) => void;
}

export function ChatInput({
  onSend,
  sending,
  onAbort,
  continueTurnId,
  onContinue,
}: ChatInputProps) {
  const { t } = useTranslation();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const slashMenuRef = useRef<SlashInvocationMenuHandle>(null);
  const artifactMentionMenuRef = useRef<ArtifactMentionMenuHandle>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const microphoneStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const vadFrameRef = useRef<number | null>(null);
  const continuousActiveRef = useRef(false);
  const continuousAgentIdRef = useRef("");
  const continuousConversationRef = useRef("");
  const speakingRef = useRef(false);
  const discardRecordingRef = useRef(false);
  const speechStartedAtRef = useRef(0);
  const silenceStartedAtRef = useRef(0);
  const speechFramesRef = useRef(0);
  const noiseFloorRef = useRef(0.006);
  const pendingVoiceRef = useRef(0);
  const voiceLevelRef = useRef(0);
  const bargeInFramesRef = useRef(0);
  const playbackStartedAtRef = useRef(0);
  const lastBargeInAtRef = useRef(0);
  const bargeInCandidateRef = useRef(false);
  const voiceHintTimerRef = useRef<number | null>(null);
  const attentionTimerRef = useRef<number | null>(null);
  const attentionTimeoutSecondsRef = useRef(0);
  const attentionLockedRef = useRef(false);
  const voiceprintEnrolledRef = useRef(false);
  const wakeWordRef = useRef("小美");
  const [dragging, setDragging] = useState(false);
  const [listening, setListening] = useState(false);
  const [mediaBusy, setMediaBusy] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState("");
  const [voiceHint, setVoiceHint] = useState("");
  const [voicePhase, setVoicePhase] = useState<VoiceOrbPhase>("listening");

  useEffect(() => {
    setLiveVoiceActive(listening);
    return () => setLiveVoiceActive(false);
  }, [listening]);
  const [desktopSpeaking, setDesktopSpeaking] = useState(false);
  const [modelSnapshot, setModelSnapshot] = useState<ModelConfigSnapshot | null>(null);
  const [modelBusy, setModelBusy] = useState(false);
  const [modelError, setModelError] = useState("");
  const [commandStatus, setCommandStatus] = useState("");
  const [dismissedSlashInput, setDismissedSlashInput] = useState("");
  const [dismissedMentionInput, setDismissedMentionInput] = useState("");
  const activeAgentId = useCoreStore((s) => s.activeAgentId);
  const activeAgentIsLocal = useCoreStore((s) => (
    s.agents.find((agent) => agent.id === s.activeAgentId)?.source === "local"
  ));
  const activeSessionId = useCoreStore((s) => {
    const agentId = s.activeAgentId || "";
    return agentId ? s.activeSessionByAgent[agentId] || "" : "";
  });
  const agentSpeaking = useCoreStore((s) => Boolean(
    s.activeAgentId && s.speakingByAgent[s.activeAgentId],
  ));
  const input = useCoreStore((s) => {
    const agentId = s.activeAgentId || "";
    const sessionId = agentId ? s.activeSessionByAgent[agentId] : null;
    return s.draftByConversation[`${agentId}\u0000${sessionId || "new"}`] || "";
  });
  const setInput = useCoreStore((s) => s.setDraft);
  const invocation = useCoreStore((s) => {
    const agentId = s.activeAgentId || "";
    const sessionId = agentId ? s.activeSessionByAgent[agentId] : null;
    return s.invocationByConversation[`${agentId}\u0000${sessionId || "new"}`];
  });
  const setInvocation = useCoreStore((s) => s.setInvocation);
  const newSession = useCoreStore((s) => s.newSession);
  const pendingAttachments = useCoreStore((s) => {
    const agentId = s.activeAgentId || "";
    const sessionId = agentId ? s.activeSessionByAgent[agentId] : null;
    return s.attachmentsByConversation[`${agentId}\u0000${sessionId || "new"}`];
  });
  const attachments = pendingAttachments || [];
  const pendingArtifactReferences = useCoreStore((s) => {
    const agentId = s.activeAgentId || "";
    const sessionId = agentId ? s.activeSessionByAgent[agentId] : null;
    return s.artifactReferencesByConversation[`${agentId}\u0000${sessionId || "new"}`];
  });
  const artifactReferences = pendingArtifactReferences || [];
  const attachmentError = useCoreStore((s) => {
    const agentId = s.activeAgentId || "";
    const sessionId = agentId ? s.activeSessionByAgent[agentId] : null;
    return s.attachmentErrorByConversation[`${agentId}\u0000${sessionId || "new"}`] || "";
  });
  const pickAttachments = useCoreStore((s) => s.pickAttachments);
  const addAttachments = useCoreStore((s) => s.addAttachments);
  const addArtifactReference = useCoreStore((s) => s.addArtifactReference);
  const removeArtifactReference = useCoreStore((s) => s.removeArtifactReference);
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

  const showVoiceHint = useCallback((message: string) => {
    setVoiceHint(message);
    if (voiceHintTimerRef.current !== null) {
      window.clearTimeout(voiceHintTimerRef.current);
    }
    voiceHintTimerRef.current = window.setTimeout(() => {
      voiceHintTimerRef.current = null;
      setVoiceHint("");
    }, 3_500);
  }, []);

  const clearAttentionTimer = useCallback(() => {
    if (attentionTimerRef.current !== null) {
      window.clearTimeout(attentionTimerRef.current);
      attentionTimerRef.current = null;
    }
  }, []);

  const showWaitingForWake = useCallback((hint = "") => {
    attentionLockedRef.current = true;
    clearAttentionTimer();
    if (voiceHintTimerRef.current !== null) {
      window.clearTimeout(voiceHintTimerRef.current);
      voiceHintTimerRef.current = null;
    }
    setVoiceStatus(t("home.voiceWaitingWake", { wakeWord: wakeWordRef.current }));
    setVoicePhase("waiting");
    setVoiceHint(
      hint || (!voiceprintEnrolledRef.current ? t("home.voiceprintNotConfigured") : ""),
    );
  }, [clearAttentionTimer, t]);

  const scheduleAttentionTimeout = useCallback(() => {
    clearAttentionTimer();
    const timeoutSeconds = attentionTimeoutSecondsRef.current;
    if (!continuousActiveRef.current || timeoutSeconds <= 0) return;
    attentionTimerRef.current = window.setTimeout(() => {
      attentionTimerRef.current = null;
      if (continuousActiveRef.current && !speakingRef.current) showWaitingForWake();
    }, timeoutSeconds * 1_000);
  }, [clearAttentionTimer, showWaitingForWake]);

  useEffect(() => {
    const onStarted = (event: Event) => {
      const detail = (event as CustomEvent<{ agentId?: string }>).detail;
      if (detail?.agentId !== activeAgentId) return;
      playbackStartedAtRef.current = performance.now();
      setDesktopSpeaking(true);
    };
    const onFinished = (event: Event) => {
      const detail = (event as CustomEvent<{ agentId?: string }>).detail;
      if (detail?.agentId !== activeAgentId) return;
      setDesktopSpeaking(false);
    };
    window.addEventListener(DESKTOP_SPEECH_STARTED, onStarted);
    window.addEventListener(DESKTOP_SPEECH_FINISHED, onFinished);
    return () => {
      window.removeEventListener(DESKTOP_SPEECH_STARTED, onStarted);
      window.removeEventListener(DESKTOP_SPEECH_FINISHED, onFinished);
    };
  }, [activeAgentId]);

  useEffect(() => {
    const speaking = agentSpeaking || desktopSpeaking;
    speakingRef.current = speaking;
    if (!continuousActiveRef.current) return;
    if (speaking) {
      discardRecordingRef.current = true;
      if (recorderRef.current?.state === "recording") recorderRef.current.stop();
      setVoiceStatus(t("home.voicePausedWhileSpeaking"));
      setVoicePhase("speaking");
    } else {
      if (bargeInCandidateRef.current && recorderRef.current?.state === "recording") {
        discardRecordingRef.current = true;
        recorderRef.current.stop();
      }
      bargeInCandidateRef.current = false;
      if (attentionLockedRef.current) {
        setVoiceStatus(t("home.voiceWaitingWake", { wakeWord: wakeWordRef.current }));
        setVoicePhase("waiting");
      } else {
        setVoiceStatus(t("home.voiceListening"));
        setVoicePhase("listening");
      }
    }
  }, [agentSpeaking, desktopSpeaking, t]);

  useEffect(() => window.gateway.onEvent((raw) => {
    if (
      raw.agentId !== activeAgentId
      || raw.event !== "embodiment.audio.input.completed"
    ) return;
    const payload = raw.data as Record<string, unknown>;
    const status = typeof payload.status === "string" ? payload.status : "";
    const reason = typeof payload.reason === "string" ? payload.reason : "";
    if (pendingVoiceRef.current > 0) {
      pendingVoiceRef.current -= 1;
      setMediaBusy(pendingVoiceRef.current > 0);
    }
    if (status === "failed") {
      showVoiceHint(
        typeof payload.error === "string"
          ? payload.error
          : t("home.voiceRecognitionFailed"),
      );
    }
    if (continuousActiveRef.current) {
      if (status === "completed") {
        attentionLockedRef.current = false;
        setVoiceHint("");
        scheduleAttentionTimeout();
      } else if (payload.attention_state === "waiting_wake") {
        showWaitingForWake(
          reason === "voiceprint_unverified" || reason === "voiceprint_mismatch"
            ? t("home.voiceprintRejected")
            : "",
        );
      } else if (status === "ignored" && reason !== "transcript_fragment") {
        scheduleAttentionTimeout();
      }
    }
    if (!continuousActiveRef.current) {
      setVoiceStatus("");
    } else if (attentionLockedRef.current && !recorderRef.current) {
      setVoiceStatus(t("home.voiceWaitingWake", { wakeWord: wakeWordRef.current }));
      setVoicePhase("waiting");
    } else if (speakingRef.current) {
      setVoiceStatus(t("home.voicePausedWhileSpeaking"));
      setVoicePhase("speaking");
    } else if (pendingVoiceRef.current > 0) {
      setVoiceStatus(t("home.voiceProcessing"));
      setVoicePhase("processing");
    } else if (recorderRef.current) {
      setVoiceStatus(t("home.voiceHearing"));
      setVoicePhase("hearing");
    } else {
      setVoiceStatus(t("home.voiceListening"));
      setVoicePhase("listening");
    }
  }), [
    activeAgentId,
    scheduleAttentionTimeout,
    showVoiceHint,
    showWaitingForWake,
    t,
  ]);

  useEffect(() => {
    if (
      !continuousActiveRef.current
      || speakingRef.current
      || pendingVoiceRef.current > 0
      || recorderRef.current
    ) return;
    if (attentionLockedRef.current) {
      setVoiceStatus(t("home.voiceWaitingWake", { wakeWord: wakeWordRef.current }));
      setVoicePhase("waiting");
    } else if (sending) {
      setVoiceStatus(t("home.voiceThinking"));
      setVoicePhase("processing");
    } else {
      setVoiceStatus(t("home.voiceListening"));
      setVoicePhase("listening");
    }
  }, [sending, t]);

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

  const slashMenuOpen = Boolean(
    connected
      && !sending
      && !invocation
      && input.startsWith("/")
      && !input.includes("\n")
      && dismissedSlashInput !== input,
  );
  const slashQuery = slashMenuOpen ? input.slice(1) : "";
  const artifactMention = !slashMenuOpen && !invocation
    ? artifactMentionAtEnd(input)
    : null;
  const artifactMentionMenuOpen = Boolean(
    connected
      && !sending
      && activeAgentId
      && artifactMention
      && dismissedMentionInput !== input,
  );

  useEffect(() => {
    if (!slashMenuOpen && !artifactMentionMenuOpen) return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      const target = event.target;
      if (
        target instanceof Element
        && target.closest(".slash-invocation-menu, .artifact-mention-menu")
      ) return;
      if (slashMenuOpen) setDismissedSlashInput(input);
      if (artifactMentionMenuOpen) setDismissedMentionInput(input);
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer, true);
    return () => document.removeEventListener("pointerdown", closeOnOutsidePointer, true);
  }, [artifactMentionMenuOpen, input, slashMenuOpen]);

  const showCommandStatus = useCallback((message: string) => {
    setCommandStatus(message);
    window.setTimeout(() => {
      setCommandStatus((current) => current === message ? "" : current);
    }, 3_500);
  }, []);

  const handleSend = async () => {
    const text = input.trim();
    if (!text && attachments.length === 0 && artifactReferences.length === 0) return;

    if (
      attachments.length === 0
      && artifactReferences.length === 0
      && slashMenuOpen
      && text !== "/new"
      && text !== "/compact"
    ) return;

    if (attachments.length === 0 && artifactReferences.length === 0 && text === "/new") {
      setInput("");
      setInvocation(undefined);
      await newSession();
      textareaRef.current?.focus();
      return;
    }

    if (attachments.length === 0 && artifactReferences.length === 0 && text === "/compact") {
      if (!activeAgentId || !activeSessionId) {
        showCommandStatus(t("home.noSessionToCompact"));
        return;
      }
      setInput("");
      setInvocation(undefined);
      setCommandStatus(t("home.compacting"));
      try {
        const response = await window.gateway.compactSession({
          agentId: activeAgentId,
          sessionId: activeSessionId,
        });
        if (response.error) throw new Error(response.error.message);
        const result = (response.result || {}) as Record<string, unknown>;
        showCommandStatus(
          result.compacted === false
            ? t("home.nothingToCompact")
            : t("home.compacted"),
        );
      } catch (error) {
        showCommandStatus(error instanceof Error ? error.message : String(error));
      }
      textareaRef.current?.focus();
      return;
    }

    onSend(text, artifactReferences);
    setDismissedSlashInput("");
    setDismissedMentionInput("");
    textareaRef.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (artifactMentionMenuOpen) {
      if (artifactMentionMenuRef.current?.handleKeyDown(
        e as React.KeyboardEvent<HTMLTextAreaElement>,
      )) return;
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        return;
      }
    }
    const hiddenCommand = input.trim() === "/new" || input.trim() === "/compact";
    if (slashMenuOpen && !hiddenCommand) {
      if (slashMenuRef.current?.handleKeyDown(
        e as React.KeyboardEvent<HTMLTextAreaElement>,
      )) return;
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  };

  const selectInvocation = (selection: ChatInvocationSelection) => {
    setInvocation(selection);
    setInput("");
    window.requestAnimationFrame(() => textareaRef.current?.focus());
  };

  const selectArtifactReference = (reference: ChatArtifactReference) => {
    if (!artifactMention) return;
    if (attachments.length + artifactReferences.length >= 4) {
      setAttachmentError(t("home.maxAttachments"));
      setDismissedMentionInput(input);
      return;
    }
    addArtifactReference(reference);
    setInput(input.slice(0, artifactMention.start));
    setDismissedMentionInput("");
    window.requestAnimationFrame(() => textareaRef.current?.focus());
  };

  const handleDrop = async (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    if (!connected || sending) return;
    const files = Array.from(event.dataTransfer.files);
    if (!files.length) return;
    if (attachments.length + files.length > 4) {
      setAttachmentError(t("home.maxAttachments"));
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
      setAttachmentError(t("home.attachmentTotalLimit", { size: totalLimit / 1024 / 1024 }));
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

  const releaseContinuousHearing = useCallback(async (updateUI = true) => {
    const agentId = continuousAgentIdRef.current;
    continuousActiveRef.current = false;
    continuousAgentIdRef.current = "";
    continuousConversationRef.current = "";
    attentionLockedRef.current = false;
    attentionTimeoutSecondsRef.current = 0;
    voiceprintEnrolledRef.current = false;
    wakeWordRef.current = "小美";
    clearAttentionTimer();
    bargeInCandidateRef.current = false;
    bargeInFramesRef.current = 0;
    if (voiceHintTimerRef.current !== null) {
      window.clearTimeout(voiceHintTimerRef.current);
      voiceHintTimerRef.current = null;
    }
    if (vadFrameRef.current !== null) {
      window.cancelAnimationFrame(vadFrameRef.current);
      vadFrameRef.current = null;
    }
    discardRecordingRef.current = true;
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    recorderRef.current = null;
    microphoneStreamRef.current?.getTracks().forEach((track) => track.stop());
    microphoneStreamRef.current = null;
    analyserRef.current = null;
    const audioContext = audioContextRef.current;
    audioContextRef.current = null;
    if (audioContext && audioContext.state !== "closed") {
      await audioContext.close().catch(() => {});
    }
    if (updateUI) {
      setListening(false);
      setVoiceStatus("");
      setVoicePhase("listening");
      setVoiceHint("");
    }
    if (agentId) {
      await window.gateway.setContinuousHearing({ agentId, enabled: false }).catch(() => undefined);
    }
  }, [clearAttentionTimer]);

  useEffect(() => () => {
    void releaseContinuousHearing(false);
  }, [releaseContinuousHearing]);

  useEffect(() => {
    if (!continuousActiveRef.current) return;
    const key = `${activeAgentId || ""}\u0000${activeSessionId}`;
    if (!connected || key !== continuousConversationRef.current) {
      void releaseContinuousHearing();
    }
  }, [activeAgentId, activeSessionId, connected, releaseContinuousHearing]);

  const sendContinuousSegment = useCallback(async (
    blob: Blob,
    agentId: string,
  ) => {
    if (!blob.size || blob.size > MAX_ATTACHMENT_BYTES) {
      if (blob.size > MAX_ATTACHMENT_BYTES) showVoiceHint(t("home.voiceTooLarge"));
      return;
    }
    pendingVoiceRef.current += 1;
    setMediaBusy(true);
    setVoiceStatus(t("home.voiceProcessing"));
    setVoicePhase("processing");
    let accepted = false;
    try {
      const response = await window.gateway.sendVoice({
        agentId,
        dataBase64: await blobToBase64(blob),
        mimeType: (blob.type || "audio/webm").split(";", 1)[0],
        size: blob.size,
        clientRequestId: crypto.randomUUID(),
        continuous: true,
        verifyIdentity: document.documentElement.dataset.desktopLocked === "true",
      });
      if (response.error) throw new Error(response.error.message);
      accepted = true;
    } catch (error) {
      showVoiceHint(error instanceof Error ? error.message : String(error));
    } finally {
      if (!accepted) pendingVoiceRef.current = Math.max(0, pendingVoiceRef.current - 1);
      setMediaBusy(pendingVoiceRef.current > 0);
      if (
        !accepted
        && continuousActiveRef.current
        && !speakingRef.current
        && pendingVoiceRef.current === 0
      ) {
        setVoiceStatus(t("home.voiceListening"));
        setVoicePhase("listening");
      }
    }
  }, [showVoiceHint, t]);

  const startSpeechSegment = useCallback((
    stream: MediaStream,
    duringSpeech = false,
  ) => {
    if (
      !continuousActiveRef.current
      || (speakingRef.current && !duringSpeech)
      || recorderRef.current
    ) return;
    const preferred = [
      "audio/webm;codecs=opus",
      "audio/ogg;codecs=opus",
    ].find((type) => MediaRecorder.isTypeSupported(type));
    const recorder = new MediaRecorder(stream, preferred ? { mimeType: preferred } : undefined);
    const chunks: BlobPart[] = [];
    recorderRef.current = recorder;
    bargeInCandidateRef.current = duringSpeech;
    setVoiceHint("");
    discardRecordingRef.current = false;
    speechStartedAtRef.current = performance.now();
    silenceStartedAtRef.current = 0;
    recorder.addEventListener("dataavailable", (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    });
    recorder.addEventListener("stop", () => {
      if (recorderRef.current === recorder) recorderRef.current = null;
      const discard = discardRecordingRef.current;
      discardRecordingRef.current = false;
      const duration = performance.now() - speechStartedAtRef.current;
      speechStartedAtRef.current = 0;
      if (discard || duration < 450 || chunks.length === 0) return;
      const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      void sendContinuousSegment(blob, continuousAgentIdRef.current);
    }, { once: true });
    recorder.start(250);
    if (!duringSpeech) {
      setVoiceStatus(t("home.voiceHearing"));
      setVoicePhase("hearing");
    }
  }, [sendContinuousSegment, t]);

  const beginVadLoop = useCallback((stream: MediaStream, analyser: AnalyserNode) => {
    const samples = new Float32Array(analyser.fftSize);
    const tick = (now: number) => {
      if (!continuousActiveRef.current) return;
      analyser.getFloatTimeDomainData(samples);
      let squareSum = 0;
      for (const sample of samples) squareSum += sample * sample;
      const rms = Math.sqrt(squareSum / samples.length);
      voiceLevelRef.current = rms;
      if (speakingRef.current) {
        speechFramesRef.current = 0;
        silenceStartedAtRef.current = 0;
        // Give browser echo cancellation time to settle, then require a much
        // stronger and sustained signal than normal VAD before interrupting.
        const bargeInThreshold = Math.max(0.035, noiseFloorRef.current * 5.5);
        const playbackWarmedUp = now - playbackStartedAtRef.current >= 650;
        if (playbackWarmedUp && rms >= bargeInThreshold) {
          bargeInFramesRef.current += 1;
          if (bargeInFramesRef.current === 1 && !recorderRef.current) {
            // Keep the beginning of a possible interruption. The recording is
            // discarded below unless enough consecutive frames confirm speech.
            startSpeechSegment(stream, true);
          }
        } else {
          bargeInFramesRef.current = 0;
          if (bargeInCandidateRef.current && recorderRef.current?.state === "recording") {
            discardRecordingRef.current = true;
            recorderRef.current.stop();
          }
          bargeInCandidateRef.current = false;
        }
        if (
          bargeInFramesRef.current >= 18
          && now - lastBargeInAtRef.current >= 1_500
        ) {
          lastBargeInAtRef.current = now;
          bargeInFramesRef.current = 0;
          bargeInCandidateRef.current = false;
          speakingRef.current = false;
          stopDesktopSpeech(continuousAgentIdRef.current);
          onAbort();
          if (!recorderRef.current) startSpeechSegment(stream);
          else {
            setVoiceStatus(t("home.voiceHearing"));
            setVoicePhase("hearing");
          }
        }
        vadFrameRef.current = window.requestAnimationFrame(tick);
        return;
      }
      bargeInFramesRef.current = 0;
      const threshold = Math.max(0.014, noiseFloorRef.current * 2.8);
      if (rms >= threshold) {
        speechFramesRef.current += 1;
        silenceStartedAtRef.current = 0;
        if (speechFramesRef.current >= 2 && !recorderRef.current) startSpeechSegment(stream);
      } else {
        noiseFloorRef.current = noiseFloorRef.current * 0.97 + rms * 0.03;
        speechFramesRef.current = 0;
        if (recorderRef.current?.state === "recording") {
          if (!silenceStartedAtRef.current) silenceStartedAtRef.current = now;
          if (now - silenceStartedAtRef.current >= 900) recorderRef.current.stop();
        }
      }
      if (
        recorderRef.current?.state === "recording"
        && speechStartedAtRef.current
        && now - speechStartedAtRef.current >= 30_000
      ) {
        recorderRef.current.stop();
      }
      vadFrameRef.current = window.requestAnimationFrame(tick);
    };
    vadFrameRef.current = window.requestAnimationFrame(tick);
  }, [onAbort, startSpeechSegment]);

  const toggleVoiceRecording = async () => {
    if (listening) {
      await releaseContinuousHearing();
      return;
    }
    if (!activeAgentId || !connected || sending) return;
    setAttachmentError("");
    const agentId = activeAgentId;
    const lease = await window.gateway.setContinuousHearing({ agentId, enabled: true });
    if (lease.error) {
      setAttachmentError(lease.error.message);
      return;
    }
    const hearing = lease.result && typeof lease.result === "object"
      ? lease.result as Record<string, unknown>
      : {};
    attentionTimeoutSecondsRef.current = typeof hearing.attention_timeout_seconds === "number"
      ? Math.max(0, hearing.attention_timeout_seconds)
      : 0;
    voiceprintEnrolledRef.current = hearing.voiceprint_enrolled === true;
    const wakeWords = Array.isArray(hearing.wake_words)
      ? hearing.wake_words.filter((word): word is string => typeof word === "string" && Boolean(word))
      : [];
    wakeWordRef.current = wakeWords[0] || "小美";
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      microphoneStreamRef.current = stream;
      const audioContext = new AudioContext();
      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 1024;
      analyser.smoothingTimeConstant = 0.15;
      source.connect(analyser);
      audioContextRef.current = audioContext;
      analyserRef.current = analyser;
      continuousActiveRef.current = true;
      continuousAgentIdRef.current = agentId;
      continuousConversationRef.current = `${agentId}\u0000${activeSessionId}`;
      noiseFloorRef.current = 0.006;
      setListening(true);
      setVoiceStatus(t("home.voiceListening"));
      setVoicePhase("listening");
      scheduleAttentionTimeout();
      beginVadLoop(stream, analyser);
    } catch (error) {
      setVoiceStatus("");
      setAttachmentError(
        error instanceof Error ? error.message : t("home.mediaPermissionDenied"),
      );
      await window.gateway.setContinuousHearing({ agentId, enabled: false }).catch(() => undefined);
    }
  };

  const captureCamera = async () => {
    if (!connected || sending || mediaBusy || attachments.length >= 4) return;
    setAttachmentError("");
    setMediaBusy(true);
    let stream: MediaStream | null = null;
    let cameraLeaseAcquired = false;
    try {
      if (activeAgentIsLocal && activeAgentId) {
        const lease = await window.gateway.setCameraCapture({
          agentId: activeAgentId,
          enabled: true,
        });
        if (lease.error) throw new Error(lease.error.message);
        cameraLeaseAcquired = true;
        // Some Windows camera drivers need a short hand-off interval after
        // OpenCV releases the DirectShow device.
        await new Promise((resolve) => window.setTimeout(resolve, 250));
      }
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
      if (cameraLeaseAcquired && activeAgentId) {
        await window.gateway.setCameraCapture({
          agentId: activeAgentId,
          enabled: false,
        }).catch(() => undefined);
      }
      setMediaBusy(false);
    }
  };

  return (
    <div
      className={`chat-input-container ${dragging ? "drag-active" : ""} ${listening ? "is-listening" : ""} ${sending ? "is-sending" : ""}`}
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
      {dragging && <div className="attachment-drop-hint">{t("home.dropToAttach")}</div>}
      {slashMenuOpen && activeAgentId && (
        <SlashInvocationMenu
          ref={slashMenuRef}
          agentId={activeAgentId}
          query={slashQuery}
          onSelect={selectInvocation}
          onClose={() => setDismissedSlashInput(input)}
        />
      )}
      {artifactMentionMenuOpen && activeAgentId && artifactMention && (
        <ArtifactMentionMenu
          ref={artifactMentionMenuRef}
          agentId={activeAgentId}
          query={artifactMention.query}
          onSelect={selectArtifactReference}
          onClose={() => setDismissedMentionInput(input)}
        />
      )}
      {artifactReferences.length > 0 && (
        <div className="composer-artifact-reference-list">
          {artifactReferences.map((reference) => (
            <div
              className="composer-artifact-reference"
              key={`${reference.sessionId}:${reference.artifactId}`}
            >
              <span className="composer-artifact-at">@</span>
              <span title={reference.name}>{reference.name || t("mentionUi.file")}</span>
              <button
                type="button"
                onClick={() => removeArtifactReference(reference.artifactId, reference.sessionId)}
                title={t("mentionUi.remove")}
                aria-label={t("mentionUi.remove")}
              >
                <Icon name="x" size={13} />
              </button>
            </div>
          ))}
        </div>
      )}
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
      {listening && (
        <div className={`voice-live-panel is-${voicePhase}`} role="status" aria-live="polite">
          <VoiceOrb levelRef={voiceLevelRef} phase={voicePhase} />
          <div className="voice-live-copy">
            <strong>{t("home.voiceConversation")}</strong>
            <span>{voiceStatus}</span>
            {voiceHint && <small>{voiceHint}</small>}
          </div>
          <button
            type="button"
            className="voice-live-stop"
            onClick={() => { void releaseContinuousHearing(); }}
            title={t("home.stopContinuousVoice")}
            aria-label={t("home.stopContinuousVoice")}
          >
            <Icon name="x" size={17} />
          </button>
        </div>
      )}
      {!listening && voiceStatus && <div className="embodiment-media-status">{voiceStatus}</div>}
      {modelError && <div className="chat-model-error">{modelError}</div>}
      {commandStatus && <div className="composer-command-status">{commandStatus}</div>}
      {invocation && (
        <div className="composer-invocation-chip">
          <span className={`slash-invocation-kind is-${invocation.kind}`}>
            {invocation.kind === "capability" ? t("home.kindCapability") : invocation.kind === "skill" ? t("home.kindSkill") : t("home.kindProcess")}
          </span>
          <span>
            {invocation.name}
            {invocation.processName ? ` · ${invocation.processName}` : ""}
          </span>
          <button
            type="button"
            onClick={() => setInvocation(undefined)}
            title={t("home.cancelInvocation")}
            aria-label={t("home.cancelInvocation")}
          >
            <Icon name="x" size={13} />
          </button>
        </div>
      )}
      <textarea
        ref={textareaRef}
        className="chat-input-textarea"
        value={input}
        onChange={(e) => {
          setDismissedSlashInput("");
          setDismissedMentionInput("");
          setInput(e.target.value);
        }}
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
            className={`chat-input-btn ${listening ? "is-recording" : ""}`}
            title={listening ? t("home.stopContinuousVoice") : t("home.startContinuousVoice")}
            onClick={() => { void toggleVoiceRecording(); }}
            disabled={!listening && (!connected || sending)}
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
            <>
              <span className="chat-input-running-state" role="status" aria-live="polite">
                <i aria-hidden="true" />
                {t("home.processing")}
              </span>
              <button className="chat-input-abort" onClick={onAbort}>
                {t("home.abort")}
              </button>
            </>
          ) : continueTurnId
            && !input.trim()
            && attachments.length === 0
            && artifactReferences.length === 0 ? (
            <button
              type="button"
              className="chat-input-continue"
              onClick={() => onContinue(continueTurnId)}
              disabled={!connected}
            >
              {t("home.continue")}
            </button>
          ) : (
            <button
              className="chat-input-send"
              onClick={() => { void handleSend(); }}
              disabled={(
                !input.trim()
                && attachments.length === 0
                && artifactReferences.length === 0
              ) || !connected}
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

function artifactMentionAtEnd(input: string): { start: number; query: string } | null {
  const match = /(^|[\s(（])@([^@\n]*)$/.exec(input);
  if (!match || typeof match.index !== "number") return null;
  return {
    start: match.index + match[1].length,
    query: match[2],
  };
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
    throw new Error(i18n.t("home.unsupportedFile", { name: file.name }));
  }
  if (file.size === 0) throw new Error(i18n.t("home.emptyFile", { name: file.name }));
  const itemLimit = videoMime ? MAX_VIDEO_ATTACHMENT_BYTES : MAX_ATTACHMENT_BYTES;
  if (file.size > itemLimit) {
    throw new Error(i18n.t("home.fileTooLarge", { name: file.name, size: itemLimit / 1024 / 1024 }));
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
    reader.onerror = () => reject(new Error(i18n.t("home.readFileFailed", { name: file.name })));
    reader.onload = () => {
      const result = typeof reader.result === "string" ? reader.result : "";
      const separator = result.indexOf(",");
      if (separator < 0) reject(new Error(i18n.t("home.readFileFailed", { name: file.name })));
      else resolve(result.slice(separator + 1));
    };
    reader.readAsDataURL(file);
  });
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(i18n.t("home.mediaDataFailed")));
    reader.onload = () => {
      const result = typeof reader.result === "string" ? reader.result : "";
      const separator = result.indexOf(",");
      if (separator < 0) reject(new Error(i18n.t("home.mediaDataFailed")));
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
      (blob) => blob ? resolve(blob) : reject(new Error(i18n.t("home.cameraEncodeFailed"))),
      type,
      quality,
    );
  });
}
