import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  useCoreStore,
  AssignmentSnapshot,
  ArtifactSnapshot,
  DisplayMessage,
  MemoryReference,
} from "../../store";
import { Button, Icon } from "../ui";
import { ChatInput } from "./ChatInput";
import { ChatTopbar } from "./ChatTopbar";
import {
  CAPABILITY_STATUS_CHANGED_EVENT,
  openSettingsCenter,
  type SettingsSection,
} from "../settings/events";
import { AssignmentCard } from "./AssignmentCard";
import { ActivitySidebar } from "../right-sidebar/ActivitySidebar";
import { TerminalPanel } from "../terminal/TerminalPanel";
import { MarkdownMessage } from "./MarkdownMessage";
import { ArtifactWorkspace } from "../artifact-workspace/ArtifactWorkspace";
import { supportsArtifactPreview } from "../../artifacts/preview-capability";
import { registerEmbodimentCommand } from "../../embodiment/command-registry";
import { enqueueMediaFilePlayback } from "../../embodiment";
import { MusicPlayer } from "../music-player/MusicPlayer";
import { VisualizationPreview } from "../visualization/VisualizationPreview";
import {
  ArtifactPresentationStage,
  type PresentationMediaCommand,
} from "../presentation-stage/ArtifactPresentationStage";
import type { PresentationStageLayout } from "../presentation-stage/PresentationStage";
import type {
  ChatArtifactReference,
  ContextTokenPressure,
  TokenUsageTurn,
} from "../../types";
import { formatTokens, useTokenUsage } from "../../usage";

const EMPTY_MSGS: DisplayMessage[] = [];
const EMPTY_ASSIGNMENTS: AssignmentSnapshot[] = [];
const EMPTY_ARTIFACTS: ArtifactSnapshot[] = [];
type RightSidebarSection = "activity" | "state" | "project" | "assignment" | "artifact" | "memory" | "context";
type FullscreenVisualizationRequest = {
  artifactId: string;
  sessionId: string;
  sentAt: number;
};
type PresentationStageState = {
  artifactKeys: string[];
  layout: PresentationStageLayout;
  activeIndex: number;
  mediaCommand?: PresentationMediaCommand;
};

function displayMessageTurnId(message: DisplayMessage): string {
  return message.turnId
    || message.interaction?.turnId
    || message.capabilitySetup?.turnId
    || message.action?.turnId
    || message.artifact?.turnId
    || "";
}

function messageHasAgentHeader(message: DisplayMessage): boolean {
  return message.role === "agent" && !message.tool && !message.serviceError;
}

type ConversationRenderItem =
  | { type: "message"; message: DisplayMessage }
  | { type: "tools"; messages: DisplayMessage[]; turnId: string };

function groupConversationMessages(messages: DisplayMessage[]): ConversationRenderItem[] {
  const items: ConversationRenderItem[] = [];
  for (const message of messages) {
    const turnId = displayMessageTurnId(message);
    const previous = items[items.length - 1];
    if (message.tool && turnId && previous?.type === "tools" && previous.turnId === turnId) {
      previous.messages.push(message);
    } else if (message.tool) {
      items.push({ type: "tools", messages: [message], turnId });
    } else {
      items.push({ type: "message", message });
    }
  }
  return items;
}

export function HomePage({
  leftSidebarCollapsed,
  onLeftSidebarCollapsedChange,
}: {
  leftSidebarCollapsed: boolean;
  onLeftSidebarCollapsedChange: (collapsed: boolean) => void;
}) {
  const { t } = useTranslation();
  const activeAgentId = useCoreStore((s) => s.activeAgentId);
  const messages = useCoreStore((s) => s.messagesByAgent[s.activeAgentId || ""] || EMPTY_MSGS);
  const continueTurn = useCoreStore((s) => s.continueTurn);
  const latestUserMessage = [...messages]
    .reverse()
    .find((message) => message.role === "user");
  const continueTurnId = latestUserMessage?.deliveryStatus === "interrupted"
    ? latestUserMessage.turnId
    : undefined;
  const sending = useCoreStore((s) => {
    const agentId = s.activeAgentId || "";
    const sessionId = agentId ? s.activeSessionByAgent[agentId] : null;
    return s.sendingByConversation[`${agentId}\u0000${sessionId || "new"}`] || false;
  });
  const agentName = useCoreStore((s) => {
    const agentId = s.activeAgentId;
    if (!agentId) return t("home.defaultAgentName");
    return s.connectionByAgent[agentId]?.agentName
      || s.agents.find((agent) => agent.id === agentId)?.name
      || t("home.defaultAgentName");
  });
  const activeAgent = useCoreStore((s) => s.agents.find((agent) => agent.id === s.activeAgentId));
  const activeAgentOnline = useCoreStore((s) => (
    s.activeAgentId ? s.localAvailabilityByAgent[s.activeAgentId] : undefined
  ));
  const activeAgentInfo = useCoreStore((s) => (
    s.activeAgentId ? s.localInfoByAgent[s.activeAgentId] : undefined
  ));
  const activeAgentLifecycle = useCoreStore((s) => (
    s.activeAgentId ? s.lifecycleByAgent[s.activeAgentId] : undefined
  ));
  const controlLocalAgent = useCoreStore((s) => s.controlLocalAgent);
  const terminalOpen = useCoreStore((s) => s.terminalOpen);
  const terminalAgentId = useCoreStore((s) => s.terminalAgentId);
  const sendMessage = useCoreStore((s) => s.sendMessage);
  const abortMessage = useCoreStore((s) => s.abortMessage);
  const activeSessionId = useCoreStore((s) => s.activeSessionByAgent[s.activeAgentId || ""] || null);
  const { summary: tokenUsageSummary } = useTokenUsage(
    activeAgentId || "",
    activeSessionId || "",
    Boolean(activeAgentId && activeSessionId),
  );
  const sessionsByAgent = useCoreStore((s) => s.sessionsByAgent);
  const historyPage = useCoreStore((s) => {
    const agentId = s.activeAgentId;
    const sessionId = agentId ? s.activeSessionByAgent[agentId] : null;
    return agentId && sessionId ? s.historyPaginationByAgent[agentId]?.[sessionId] : undefined;
  });
  const loadOlderMessages = useCoreStore((s) => s.loadOlderMessages);
  const assignments = useCoreStore((s) => s.assignmentsByAgent[s.activeAgentId || ""] || EMPTY_ASSIGNMENTS);
  const connectionStatus = useCoreStore((s) => s.connectionByAgent[s.activeAgentId || ""]?.status);
  const refreshAssignments = useCoreStore((s) => s.refreshAssignments);
  const refreshActivities = useCoreStore((s) => s.refreshActivities);
  const refreshArtifacts = useCoreStore((s) => s.refreshArtifacts);
  const refreshPersonMemories = useCoreStore((s) => s.refreshPersonMemories);
  const refreshAgentState = useCoreStore((s) => s.refreshAgentState);
  const activeArtifacts = useCoreStore((s) => s.artifactsByAgent[s.activeAgentId || ""] || EMPTY_ARTIFACTS);
  const agentState = useCoreStore((s) => s.agentStateByAgent[s.activeAgentId || ""]);
  const speaking = useCoreStore((s) => Boolean(s.speakingByAgent[s.activeAgentId || ""]));
  const currentActivity = useCoreStore((s) => (
    s.activitiesByAgent[s.activeAgentId || ""] || []
  ).find((item) => ["queued", "running", "paused"].includes(item.status)));

  const [activityPanelOpen, setActivityPanelOpen] = useState(false);
  const [rightSidebarSection, setRightSidebarSection] = useState<RightSidebarSection>("activity");
  const [focusedArtifactKey, setFocusedArtifactKey] = useState("");
  const [presentationStage, setPresentationStage] = useState<PresentationStageState | null>(null);
  const [fullscreenVisualizationRequest, setFullscreenVisualizationRequest] = useState<FullscreenVisualizationRequest | null>(null);
  const [focusedMemories, setFocusedMemories] = useState<MemoryReference[]>([]);
  const [selectedAssignmentId, setSelectedAssignmentId] = useState<string | null>(null);
  const [historyTraversalStarted, setHistoryTraversalStarted] = useState<Set<string>>(() => new Set());
  const [followingLatest, setFollowingLatest] = useState(true);
  const [unreadWhileAway, setUnreadWhileAway] = useState(false);
  const [focusedSearchMessageId, setFocusedSearchMessageId] = useState("");
  const autoCollapsedLeftSidebarRef = useRef(false);
  const conversationItems = useMemo(() => groupConversationMessages(messages), [messages]);
  const turnUsageById = useMemo(() => new Map(
    (tokenUsageSummary?.turns || []).map((item) => [item.turn_id, item]),
  ), [tokenUsageSummary]);
  const finalAgentMessageByTurn = useMemo(() => {
    const result = new Map<string, string>();
    for (const message of messages) {
      const turnId = displayMessageTurnId(message);
      if (
        turnId
        && message.role === "agent"
        && !message.tool
        && !message.action
        && !message.interaction
        && !message.capabilitySetup
        && !message.artifact
        && !message.serviceError
        && message.content.trim()
      ) {
        result.set(turnId, message.id);
      }
    }
    return result;
  }, [messages]);
  const latestFinalAgentMessageId = useMemo(() => {
    let latest = "";
    for (const message of messages) {
      const turnId = displayMessageTurnId(message);
      if (turnId && finalAgentMessageByTurn.get(turnId) === message.id) {
        latest = message.id;
      }
    }
    return latest;
  }, [finalAgentMessageByTurn, messages]);
  const activePresentationKey = presentationStage?.artifactKeys[
    Math.min(presentationStage.activeIndex, Math.max(0, presentationStage.artifactKeys.length - 1))
  ] || "";
  const bottomRef = useRef<HTMLDivElement>(null);
  const topRef = useRef<HTMLDivElement>(null);
  const messageListRef = useRef<HTMLDivElement>(null);
  const previousFirstMessageId = useRef<string | null>(null);
  const followLatestRef = useRef(true);
  const scrollFrameRef = useRef<number>();

  const openArtifactWorkspace = useCallback((artifactId: string, sessionId: string) => {
    if (!leftSidebarCollapsed) {
      autoCollapsedLeftSidebarRef.current = true;
      onLeftSidebarCollapsedChange(true);
    }
    setFocusedArtifactKey(`${sessionId}:${artifactId}`);
    setActivityPanelOpen(false);
  }, [leftSidebarCollapsed, onLeftSidebarCollapsedChange]);

  const closeArtifactWorkspace = useCallback(() => {
    setFocusedArtifactKey("");
    if (autoCollapsedLeftSidebarRef.current && leftSidebarCollapsed) {
      onLeftSidebarCollapsedChange(false);
    }
    autoCollapsedLeftSidebarRef.current = false;
  }, [leftSidebarCollapsed, onLeftSidebarCollapsedChange]);

  useEffect(() => {
    const toggleRightSidebar = () => {
      if (focusedArtifactKey) {
        closeArtifactWorkspace();
        setActivityPanelOpen(true);
      } else {
        setActivityPanelOpen((open) => !open);
      }
    };
    window.addEventListener("xiaomei:right-sidebar-toggle", toggleRightSidebar);
    return () => window.removeEventListener("xiaomei:right-sidebar-toggle", toggleRightSidebar);
  }, [closeArtifactWorkspace, focusedArtifactKey]);

  useEffect(() => {
    const closeRightSidebar = () => {
      if (focusedArtifactKey) closeArtifactWorkspace();
      setActivityPanelOpen(false);
    };
    window.addEventListener("xiaomei:right-sidebar-close", closeRightSidebar);
    return () => window.removeEventListener("xiaomei:right-sidebar-close", closeRightSidebar);
  }, [closeArtifactWorkspace, focusedArtifactKey]);

  const activateArtifact = useCallback((artifactId: string, sessionId: string) => {
    const artifact = activeArtifacts.find((item) => item.id === artifactId && item.sessionId === sessionId);
    if (!artifact || supportsArtifactPreview(artifact)) {
      openArtifactWorkspace(artifactId, sessionId);
      return;
    }
    void window.gateway.openArtifact({
      agentId: activeAgentId || "",
      sessionId,
      artifactId,
    });
  }, [activeAgentId, activeArtifacts, openArtifactWorkspace]);

  useEffect(() => {
    const validSections = new Set<RightSidebarSection>([
      "activity", "state", "project", "assignment", "artifact", "memory", "context",
    ]);
    const belongsToVisibleConversation = (agentId: string, sessionId: string) => (
      agentId === activeAgentId && sessionId === activeSessionId
    );
    const currentArtifact = (artifactId: string) => activeArtifacts.find((artifact) => (
      artifact.sessionId === activeSessionId && (!artifactId || artifact.id === artifactId)
    ));
    const requestedArtifactIds = (args: Record<string, unknown>) => [
        ...(Array.isArray(args.artifact_ids) ? args.artifact_ids : []),
        args.artifact_id,
      ].map((value) => String(value || "").trim()).filter(Boolean);
    const requestedArtifacts = (args: Record<string, unknown>) => {
      const ids = [...new Set(requestedArtifactIds(args))];
      const candidates = activeArtifacts
        .filter((artifact) => artifact.sessionId === activeSessionId)
        .sort((left, right) => right.updatedAt - left.updatedAt);
      if (!ids.length) {
        const layout = String(args.layout || "single");
        const limit = layout === "gallery" ? 6 : layout === "split" || layout === "media_with_details" ? 2 : 1;
        return candidates.slice(0, limit);
      }
      const byId = new Map(candidates.map((artifact) => [artifact.id, artifact]));
      return ids.flatMap((id) => {
        const artifact = byId.get(id);
        return artifact ? [artifact] : [];
      }).slice(0, 6);
    };

    const disposers = [
      registerEmbodimentCommand("ui.right_sidebar.set", ({ agentId, sessionId, arguments: args }) => {
        if (!belongsToVisibleConversation(agentId, sessionId)) {
          return { status: "rejected", error: "发起命令的会话当前不可见" };
        }
        const state = String(args.state || "");
        if (!["open", "closed", "toggle"].includes(state)) {
          return { status: "rejected", error: "无效的右侧栏状态" };
        }
        setFocusedArtifactKey("");
        setActivityPanelOpen((open) => state === "toggle" ? !open : state === "open");
        return { status: "completed" };
      }),
      registerEmbodimentCommand("ui.right_sidebar.section.open", ({ agentId, sessionId, arguments: args }) => {
        if (!belongsToVisibleConversation(agentId, sessionId)) {
          return { status: "rejected", error: "发起命令的会话当前不可见" };
        }
        const section = String(args.section || "") as RightSidebarSection;
        if (!validSections.has(section)) {
          return { status: "rejected", error: "未知的右侧栏栏目" };
        }
        setFocusedArtifactKey("");
        setRightSidebarSection(section);
        setActivityPanelOpen(true);
        return { status: "completed" };
      }),
      registerEmbodimentCommand("ui.artifact.open", ({ agentId, sessionId, arguments: args }) => {
        if (!belongsToVisibleConversation(agentId, sessionId)) {
          return { status: "rejected", error: "发起命令的会话当前不可见" };
        }
        const artifact = currentArtifact(String(args.artifact_id || ""));
        if (!artifact) return { status: "failed", error: "当前会话没有可打开的产物" };
        activateArtifact(artifact.id, artifact.sessionId);
        return { status: "completed", result: { artifact_id: artifact.id } };
      }),
      registerEmbodimentCommand("file.artifact.open_external", async ({ agentId, sessionId, arguments: args }) => {
        if (!belongsToVisibleConversation(agentId, sessionId)) {
          return { status: "rejected", error: "发起命令的会话当前不可见" };
        }
        const artifact = currentArtifact(String(args.artifact_id || ""));
        if (!artifact) return { status: "failed", error: "当前会话没有可打开的产物" };
        const response = await window.gateway.openArtifact({
          agentId,
          sessionId: artifact.sessionId,
          artifactId: artifact.id,
        });
        return response.ok
          ? { status: "completed", result: { artifact_id: artifact.id } }
          : { status: "failed", error: response.error || "无法打开产物" };
      }),
      registerEmbodimentCommand("stage.open", ({ agentId, sessionId, arguments: args }) => {
        if (!belongsToVisibleConversation(agentId, sessionId)) {
          return { status: "rejected", error: "发起命令的会话当前不可见" };
        }
        const artifacts = requestedArtifacts(args);
        if (!artifacts.length) return { status: "failed", error: "当前会话没有可演示的产物" };
        const requestedIds = [...new Set(requestedArtifactIds(args))];
        if (requestedIds.length && artifacts.length !== requestedIds.length) {
          return { status: "failed", error: "部分指定产物不属于当前会话或尚未完成登记" };
        }
        const requestedLayout = String(args.layout || "single") as PresentationStageLayout;
        const allowedLayouts: PresentationStageLayout[] = ["single", "split", "gallery", "media_with_details"];
        const layout = allowedLayouts.includes(requestedLayout) ? requestedLayout : "single";
        setFocusedArtifactKey("");
        setActivityPanelOpen(false);
        setPresentationStage({
          artifactKeys: artifacts.map((artifact) => `${artifact.sessionId}:${artifact.id}`),
          layout,
          activeIndex: 0,
        });
        return {
          status: "completed",
          result: { artifact_ids: artifacts.map((artifact) => artifact.id), layout },
        };
      }),
      registerEmbodimentCommand("stage.close", ({ agentId, sessionId }) => {
        if (!belongsToVisibleConversation(agentId, sessionId)) {
          return { status: "rejected", error: "发起命令的会话当前不可见" };
        }
        setPresentationStage(null);
        return { status: "completed" };
      }),
      registerEmbodimentCommand("stage.next", ({ agentId, sessionId }) => {
        if (!belongsToVisibleConversation(agentId, sessionId)) {
          return { status: "rejected", error: "发起命令的会话当前不可见" };
        }
        if (!activePresentationKey) return { status: "failed", error: "演示台尚未打开" };
        setPresentationStage((current) => current && current.artifactKeys.length
          ? { ...current, activeIndex: (current.activeIndex + 1) % current.artifactKeys.length }
          : current);
        return { status: "completed" };
      }),
      registerEmbodimentCommand("stage.previous", ({ agentId, sessionId }) => {
        if (!belongsToVisibleConversation(agentId, sessionId)) {
          return { status: "rejected", error: "发起命令的会话当前不可见" };
        }
        if (!activePresentationKey) return { status: "failed", error: "演示台尚未打开" };
        setPresentationStage((current) => current && current.artifactKeys.length
          ? { ...current, activeIndex: (current.activeIndex - 1 + current.artifactKeys.length) % current.artifactKeys.length }
          : current);
        return { status: "completed" };
      }),
      registerEmbodimentCommand("stage.layout.set", ({ agentId, sessionId, arguments: args }) => {
        if (!belongsToVisibleConversation(agentId, sessionId)) {
          return { status: "rejected", error: "发起命令的会话当前不可见" };
        }
        const requestedLayout = String(args.layout || "") as PresentationStageLayout;
        const allowedLayouts: PresentationStageLayout[] = ["single", "split", "gallery", "media_with_details"];
        if (!allowedLayouts.includes(requestedLayout)) {
          return { status: "rejected", error: "未知的演示布局" };
        }
        if (!activePresentationKey) return { status: "failed", error: "演示台尚未打开" };
        const requestedIds = [...new Set(requestedArtifactIds(args))];
        const hasRequestedArtifacts = requestedIds.length > 0;
        const artifacts = hasRequestedArtifacts ? requestedArtifacts(args) : [];
        if (hasRequestedArtifacts && !artifacts.length) {
          return { status: "failed", error: "没有找到指定的会话产物" };
        }
        if (hasRequestedArtifacts && artifacts.length !== requestedIds.length) {
          return { status: "failed", error: "部分指定产物不属于当前会话或尚未完成登记" };
        }
        setPresentationStage((current) => current ? {
          ...current,
          layout: requestedLayout,
          artifactKeys: hasRequestedArtifacts
            ? artifacts.map((artifact) => `${artifact.sessionId}:${artifact.id}`)
            : current.artifactKeys,
          activeIndex: hasRequestedArtifacts ? 0 : current.activeIndex,
        } : current);
        return {
          status: "completed",
          result: {
            layout: requestedLayout,
            artifact_ids: hasRequestedArtifacts
              ? artifacts.map((artifact) => artifact.id)
              : undefined,
          },
        };
      }),
      registerEmbodimentCommand("stage.state.get", ({ agentId, sessionId }) => {
        if (!belongsToVisibleConversation(agentId, sessionId)) {
          return { status: "rejected", error: "发起命令的会话当前不可见" };
        }
        if (!presentationStage) {
          return {
            status: "completed",
            result: { open: false, artifact_ids: [] },
          };
        }
        const artifacts = presentationStage.artifactKeys.flatMap((key) => {
          const artifact = activeArtifacts.find((item) => `${item.sessionId}:${item.id}` === key);
          return artifact ? [artifact] : [];
        });
        return {
          status: "completed",
          result: {
            open: true,
            layout: presentationStage.layout,
            active_index: presentationStage.activeIndex,
            artifact_ids: artifacts.map((artifact) => artifact.id),
            artifacts: artifacts.map((artifact) => ({
              artifact_id: artifact.id,
              name: artifact.name,
              kind: artifact.kind,
              mime_type: artifact.mimeType,
            })),
          },
        };
      }),
      ...(["play", "pause"] as const).map((action) => registerEmbodimentCommand(`stage.${action}`, ({ agentId, sessionId }) => {
        if (!belongsToVisibleConversation(agentId, sessionId)) {
          return { status: "rejected" as const, error: "发起命令的会话当前不可见" };
        }
        if (!activePresentationKey) {
          return { status: "failed" as const, error: "演示台尚未打开" };
        }
        setPresentationStage((current) => current ? {
          ...current,
          mediaCommand: { type: action, revision: Date.now() },
        } : current);
        return { status: "completed" as const };
      })),
    ];
    return () => disposers.forEach((dispose) => dispose());
  }, [activeAgentId, activeArtifacts, activePresentationKey, activeSessionId, activateArtifact, presentationStage]);

  useEffect(() => {
    if (focusedArtifactKey && !leftSidebarCollapsed) {
      autoCollapsedLeftSidebarRef.current = false;
    }
  }, [focusedArtifactKey, leftSidebarCollapsed]);

  useEffect(() => {
    let active = true;
    void window.desktop.getSettings().then((settings) => {
      if (active) setActivityPanelOpen(settings.openRightSidebarByDefault);
    });
    const handleSettings = (event: Event) => {
      const settings = (event as CustomEvent<import("../../types").DesktopSettings>).detail;
      setActivityPanelOpen(settings.openRightSidebarByDefault);
    };
    window.addEventListener("xiaomei:desktop-settings-changed", handleSettings);
    return () => {
      active = false;
      window.removeEventListener("xiaomei:desktop-settings-changed", handleSettings);
    };
  }, []);

  useEffect(() => {
    const openArtifact = (event: Event) => {
      const detail = (event as CustomEvent<{ sessionId?: string; artifactId?: string }>).detail;
      if (!detail?.sessionId || !detail.artifactId) return;
      activateArtifact(detail.artifactId, detail.sessionId);
    };
    const openAssignmentFromSearch = (event: Event) => {
      const detail = (event as CustomEvent<{ assignmentId?: string }>).detail;
      if (!detail?.assignmentId) return;
      setSelectedAssignmentId(detail.assignmentId);
      setRightSidebarSection("assignment");
      setActivityPanelOpen(true);
    };
    const focusMessageFromSearch = (event: Event) => {
      const detail = (event as CustomEvent<{ messageKey?: string }>).detail;
      if (!detail?.messageKey) return;
      followLatestRef.current = false;
      setFollowingLatest(false);
      setFocusedSearchMessageId(detail.messageKey);
    };
    window.addEventListener("xiaomei:open-search-artifact", openArtifact);
    window.addEventListener("xiaomei:open-search-assignment", openAssignmentFromSearch);
    window.addEventListener("xiaomei:focus-search-message", focusMessageFromSearch);
    return () => {
      window.removeEventListener("xiaomei:open-search-artifact", openArtifact);
      window.removeEventListener("xiaomei:open-search-assignment", openAssignmentFromSearch);
      window.removeEventListener("xiaomei:focus-search-message", focusMessageFromSearch);
    };
  }, [activateArtifact]);

  useEffect(() => {
    if (!focusedSearchMessageId) return;
    const frame = window.requestAnimationFrame(() => {
      const element = document.getElementById(`conversation-message-${focusedSearchMessageId}`);
      if (!element) return;
      element.scrollIntoView({ block: "center", behavior: "smooth" });
    });
    const timer = window.setTimeout(() => setFocusedSearchMessageId(""), 2400);
    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timer);
    };
  }, [focusedSearchMessageId, messages]);

  useEffect(() => {
    if (activeAgentId && connectionStatus === "connected") {
      void refreshAssignments(activeAgentId);
      void refreshActivities(activeAgentId);
      void refreshArtifacts(activeAgentId);
      void refreshPersonMemories(activeAgentId);
      void refreshAgentState(activeAgentId);
    }
  }, [
    activeAgentId,
    connectionStatus,
    refreshActivities,
    refreshAgentState,
    refreshArtifacts,
    refreshPersonMemories,
    refreshAssignments,
  ]);

  useEffect(() => {
    if (autoCollapsedLeftSidebarRef.current && leftSidebarCollapsed) {
      onLeftSidebarCollapsedChange(false);
    }
    setActivityPanelOpen(false);
    setSelectedAssignmentId(null);
    setFocusedMemories([]);
    setFocusedArtifactKey("");
    autoCollapsedLeftSidebarRef.current = false;
  }, [activeAgentId]);

  const scrollToLatest = useCallback(() => {
    const list = messageListRef.current;
    followLatestRef.current = true;
    setFollowingLatest(true);
    setUnreadWhileAway(false);
    if (list) list.scrollTop = list.scrollHeight;
  }, []);

  const scheduleScrollToLatest = useCallback(() => {
    window.cancelAnimationFrame(scrollFrameRef.current || 0);
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      if (followLatestRef.current) scrollToLatest();
    });
  }, [scrollToLatest]);

  useEffect(() => () => window.cancelAnimationFrame(scrollFrameRef.current || 0), []);

  useEffect(() => {
    followLatestRef.current = true;
    setFollowingLatest(true);
    setUnreadWhileAway(false);
    previousFirstMessageId.current = null;
    scheduleScrollToLatest();
  }, [activeAgentId, activeSessionId, scheduleScrollToLatest]);

  useEffect(() => {
    const firstMessageId = messages[0]?.id || null;
    const previousFirst = previousFirstMessageId.current;
    const historyWasPrepended = Boolean(
      previousFirst
      && firstMessageId !== previousFirst
      && messages.some((message) => message.id === previousFirst),
    );
    if (!historyWasPrepended) {
      if (followLatestRef.current) {
        scheduleScrollToLatest();
      } else {
        setUnreadWhileAway(true);
      }
    }
    previousFirstMessageId.current = firstMessageId;
  }, [messages, scheduleScrollToLatest]);

  const handleMessageListScroll = useCallback(() => {
    const list = messageListRef.current;
    if (!list) return;
    const distanceToBottom = list.scrollHeight - list.clientHeight - list.scrollTop;
    const nearBottom = distanceToBottom <= 72;
    followLatestRef.current = nearBottom;
    setFollowingLatest(nearBottom);
    if (nearBottom) setUnreadWhileAway(false);
  }, []);

  const loadOlderPreservingPosition = useCallback(async () => {
    const historyKey = activeAgentId && activeSessionId
      ? `${activeAgentId}:${activeSessionId}`
      : "";
    if (historyKey && historyPage?.hasMore) {
      setHistoryTraversalStarted((current) => {
        if (current.has(historyKey)) return current;
        const next = new Set(current);
        next.add(historyKey);
        return next;
      });
    }
    const list = messageListRef.current;
    const previousHeight = list?.scrollHeight || 0;
    await loadOlderMessages();
    requestAnimationFrame(() => {
      if (list) list.scrollTop += list.scrollHeight - previousHeight;
    });
  }, [activeAgentId, activeSessionId, historyPage?.hasMore, loadOlderMessages]);

  useEffect(() => {
    const sentinel = topRef.current;
    const list = messageListRef.current;
    if (!sentinel || !list || !historyPage?.hasMore || historyPage.loading || historyPage.error) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) void loadOlderPreservingPosition();
    }, { root: list, threshold: 0.1 });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [activeAgentId, activeSessionId, historyPage?.hasMore, historyPage?.loading, historyPage?.error, loadOlderPreservingPosition]);

  const hasMessages = messages.length > 0;
  const activeHistoryKey = activeAgentId && activeSessionId
    ? `${activeAgentId}:${activeSessionId}`
    : "";
  const showOldestReached = Boolean(
    activeHistoryKey
    && historyTraversalStarted.has(activeHistoryKey)
    && historyPage
    && !historyPage.hasMore
    && !historyPage.loading
    && !historyPage.error,
  );
  const visibleAgentState = connectionStatus === "connected" ? agentState : undefined;
  const isDreaming = visibleAgentState?.living === "dreaming";
  // Keep the normal conversation surface intact once a session has history.
  // The full start screen belongs only to an empty, unavailable local Agent;
  // otherwise it would be rendered above cached messages during every restart.
  const showAgentStart = !hasMessages
    && activeAgent?.source === "local"
    && activeAgentOnline === false;
  const agentStarting = activeAgentLifecycle?.status === "starting"
    || activeAgentLifecycle?.status === "restarting";
  const agentNeedsRestart = Boolean(activeAgentInfo?.pid);
  const visibleAssignments = assignments
    .filter((assignment) => (
      assignment.originSessionId === activeSessionId
      && !["declined", "cancelled"].includes(assignment.status)
    ))
    .slice(0, 2);
  const openAssignment = (assignmentId: string) => {
    setSelectedAssignmentId(assignmentId);
    setActivityPanelOpen(true);
  };
  const showArtifact = useCallback((artifactId: string, sessionId: string) => {
    openArtifactWorkspace(artifactId, sessionId);
  }, [openArtifactWorkspace]);
  const maximizeVisualization = useCallback(() => {
    // Visualizations already live in the primary conversation surface. Give
    // that surface the available width instead of duplicating the preview in
    // the artifact/right-side workspace.
    autoCollapsedLeftSidebarRef.current = false;
    setFocusedArtifactKey("");
    setActivityPanelOpen(false);
    if (!leftSidebarCollapsed) onLeftSidebarCollapsedChange(true);
  }, [leftSidebarCollapsed, onLeftSidebarCollapsedChange]);
  const toggleArtifactPresentation = useCallback((artifactKey: string) => {
    setPresentationStage((current) => current?.artifactKeys.includes(artifactKey)
      ? null
      : { artifactKeys: [artifactKey], layout: "single", activeIndex: 0 });
  }, []);

  const sendComposerMessage = useCallback((
    text: string,
    artifactReferences: ChatArtifactReference[] = [],
  ) => {
    if (!activePresentationKey) {
      sendMessage(text, artifactReferences);
      return;
    }
    const current = activeArtifacts.find((artifact) => (
      `${artifact.sessionId}:${artifact.id}` === activePresentationKey
    ));
    if (!current) {
      sendMessage(text, artifactReferences);
      return;
    }
    const implicitReference: ChatArtifactReference = {
      artifactId: current.id,
      sessionId: current.sessionId,
      name: current.name,
      mimeType: current.mimeType,
      size: current.size,
      kind: current.kind,
      presentationMode: "presentation_stage",
    };
    const references = artifactReferences.some((reference) => (
      reference.artifactId === current.id && reference.sessionId === current.sessionId
    ))
      ? artifactReferences
      : [...artifactReferences, implicitReference];
    if (current.kind === "visualization") {
      setFullscreenVisualizationRequest({
        artifactId: current.id,
        sessionId: current.sessionId,
        sentAt: Date.now(),
      });
    }
    sendMessage(text, references);
  }, [activeArtifacts, activePresentationKey, sendMessage]);

  useEffect(() => {
    if (!activePresentationKey) return undefined;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPresentationStage(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [activePresentationKey]);

  useEffect(() => {
    setPresentationStage(null);
    setFullscreenVisualizationRequest(null);
  }, [activeAgentId, activeSessionId]);

  useEffect(() => {
    const request = fullscreenVisualizationRequest;
    if (!request || !activePresentationKey) return;
    const userMessage = [...messages].reverse().find((message) => (
      message.role === "user"
      && (message.createdAt || 0) >= request.sentAt - 250
      && message.attachments?.some((attachment) => attachment.id === request.artifactId)
    ));
    if (!userMessage?.turnId) return;
    const replacement = activeArtifacts.find((artifact) => (
      artifact.sessionId === request.sessionId
      && artifact.kind === "visualization"
      && artifact.turnId === userMessage.turnId
    ));
    if (replacement) {
      setPresentationStage((current) => current ? {
        ...current,
        artifactKeys: current.artifactKeys.map((key) => (
          key === `${request.sessionId}:${request.artifactId}`
            ? `${replacement.sessionId}:${replacement.id}`
            : key
        )),
      } : current);
      setFullscreenVisualizationRequest(null);
      return;
    }
    if (!sending) setFullscreenVisualizationRequest(null);
  }, [activeArtifacts, activePresentationKey, fullscreenVisualizationRequest, messages, sending]);
  const showMemories = useCallback((references: MemoryReference[]) => {
    setFocusedMemories(references);
    setRightSidebarSection("context");
    setActivityPanelOpen(true);
  }, []);

  const taskName = (() => {
    if (activeSessionId && activeAgentId) {
      const sessions = sessionsByAgent[activeAgentId] || [];
      const s = sessions.find((x) => x.id === activeSessionId);
      if (s) return s.name;
    }
    return agentName || t("home.defaultAgentName");
  })();
  const presentationArtifacts = presentationStage
    ? presentationStage.artifactKeys.flatMap((key) => {
      const artifact = activeArtifacts.find((item) => `${item.sessionId}:${item.id}` === key);
      return artifact ? [artifact] : [];
    })
    : [];

  return (
    <div className={`main-content ${focusedArtifactKey ? "has-artifact-workspace" : ""} ${activePresentationKey ? "presentation-stage-mode" : ""}`}>
      <div className="main-content-primary">
      {activeAgentId && !showAgentStart && (
        <ChatTopbar
          taskName={taskName}
          onToggleRightPanel={() => {
            if (focusedArtifactKey) {
              closeArtifactWorkspace();
              setActivityPanelOpen(true);
            } else {
              setActivityPanelOpen((open) => !open);
            }
          }}
          rightPanelOpen={activityPanelOpen || Boolean(focusedArtifactKey)}
          onOpenAgentSettings={() => openSettingsCenter("overview")}
          agentState={visibleAgentState}
          speaking={speaking}
          activitySummary={currentActivity?.progressSummary || currentActivity?.title || ""}
        />
      )}
      <div className={`wb-home-page ${hasMessages ? "is-conversation" : "is-empty"}`}>
        {showAgentStart && activeAgent && activeAgentId && (
          <div className="agent-start-state">
            <div className="agent-start-avatar">{activeAgent.name.charAt(0)}</div>
            <h1>
              {agentNeedsRestart
                ? t("home.agentDisconnectedTitle", { name: activeAgent.name })
                : t("home.agentCreatedTitle", { name: activeAgent.name })}
            </h1>
            <p className="agent-start-role">
              <span>{t("home.agentResponsibility")}</span>
              {activeAgent.description || t("home.agentResponsibilityFallback")}
            </p>
            {agentNeedsRestart && (
              <p className="agent-start-status-hint">{t("home.agentDisconnectedHint")}</p>
            )}
            <Button
              variant="primary"
              size="lg"
              icon={agentStarting ? "refresh" : "play"}
              disabled={agentStarting}
              onClick={() => {
                void controlLocalAgent(activeAgentId, agentNeedsRestart ? "restart" : "start");
              }}
            >
              {agentStarting
                ? t("home.agentStarting")
                : agentNeedsRestart
                  ? t("home.restartAgent", { name: activeAgent.name })
                  : t("home.startAgent", { name: activeAgent.name })}
            </Button>
            {activeAgentLifecycle?.status === "error" && (
              <div className="agent-start-error">{activeAgentLifecycle.error}</div>
            )}
          </div>
        )}
        {!hasMessages && !showAgentStart && (
          <>
            {activeAgent && (
              <div className="agent-empty-profile">
                <div className="agent-empty-avatar">{agentName.charAt(0)}</div>
                <h1>{agentName}</h1>
                <p>{activeAgent.description || t("home.agentResponsibilityFallback")}</p>
                <span className={`agent-empty-presence ${visibleAgentState?.living || "idle"}`}>
                  <i />
                  {connectionStatus === "connecting"
                    ? t("home.connecting")
                    : visibleAgentState?.focusSummary
                      || (visibleAgentState ? livingStateName(visibleAgentState.living, t) : t("home.agentReady"))}
                </span>
              </div>
            )}
            {visibleAssignments.length > 0 && (
              <div className="assignment-home-cards">
                {visibleAssignments.map((assignment) => (
                  <AssignmentCard key={assignment.id} assignment={assignment} onOpen={openAssignment} />
                ))}
              </div>
            )}
            {isDreaming && <DreamingNotice agentName={agentName} />}
          </>
        )}
        {hasMessages && (
          <>
            {isDreaming && <DreamingNotice agentName={agentName} />}
            {visibleAssignments.length > 0 && (
              <div className="assignment-conversation-strip">
                {visibleAssignments.map((assignment) => (
                  <AssignmentCard key={assignment.id} assignment={assignment} onOpen={openAssignment} />
                ))}
              </div>
            )}
            <div className="message-list" ref={messageListRef} onScroll={handleMessageListScroll}>
              <div className="message-list-inner">
                <div ref={topRef} className="history-page-status">
                  {historyPage?.loading && t("home.loadingOlder")}
                  {historyPage?.error && (
                    <button type="button" onClick={() => { void loadOlderPreservingPosition(); }}>
                      {t("home.retryOlder")}
                    </button>
                  )}
                  {showOldestReached ? t("home.oldestReached") : null}
                </div>
                {(() => {
                  const headedTurns = new Set<string>();
                  return conversationItems.map((item) => {
                    if (item.type === "tools") {
                      return (
                        <ToolActivityGroup
                          key={`tools-${item.messages[0].id}`}
                          messages={item.messages}
                        />
                      );
                    }
                    const m = item.message;
                    const turnId = displayMessageTurnId(m);
                    const canShowHeader = messageHasAgentHeader(m);
                    const showAgentHeader = !canShowHeader || !turnId || !headedTurns.has(turnId);
                    if (canShowHeader && turnId) headedTurns.add(turnId);
                    return (
                      <MessageRow
                        key={m.id}
                        message={m}
                        agentName={agentName || t("home.defaultAgentName")}
                        showAgentHeader={showAgentHeader}
                        highlighted={focusedSearchMessageId === m.id}
                        turnUsage={turnId && finalAgentMessageByTurn.get(turnId) === m.id
                          ? turnUsageById.get(turnId)
                          : undefined}
                        contextPressure={m.id === latestFinalAgentMessageId
                          ? tokenUsageSummary?.context_pressure || undefined
                          : undefined}
                        onShowArtifact={showArtifact}
                        onMaximizeVisualization={maximizeVisualization}
                        onPresentArtifact={toggleArtifactPresentation}
                        onShowMemories={showMemories}
                      />
                    );
                  });
                })()}
                <div ref={bottomRef} />
              </div>
            </div>
            {!followingLatest && (
              <button
                type="button"
                className={`scroll-to-latest ${unreadWhileAway ? "has-unread" : ""}`}
                onClick={scrollToLatest}
                title={t("home.oldestReached")}
              >
                <Icon name="chevron-down" size={16} />
                {unreadWhileAway && <span>{t("home.newMessage")}</span>}
              </button>
            )}
          </>
        )}
        {!showAgentStart && (
          <div className="wb-home-composer">
            <MusicPlayer />
            <ChatInput
              onSend={sendComposerMessage}
              sending={sending}
              onAbort={abortMessage}
              continueTurnId={continueTurnId}
              onContinue={(turnId) => { void continueTurn(turnId); }}
            />
          </div>
        )}
      </div>
      {terminalOpen && <TerminalPanel key={terminalAgentId || "shell"} />}
      </div>
      <ActivitySidebar
        open={activityPanelOpen && !focusedArtifactKey}
        onClose={() => setActivityPanelOpen(false)}
        selectedAssignmentId={selectedAssignmentId}
        onSelectAssignment={setSelectedAssignmentId}
        section={rightSidebarSection}
        onSectionChange={setRightSidebarSection}
        focusedArtifactKey={focusedArtifactKey}
        focusedMemories={focusedMemories}
        onOpenArtifact={openArtifactWorkspace}
      />
      {focusedArtifactKey && activeAgentId && (
        <ArtifactWorkspace
          agentId={activeAgentId}
          artifactKey={focusedArtifactKey}
          onClose={closeArtifactWorkspace}
        />
      )}
      {presentationStage && activeAgentId && presentationArtifacts.length > 0 && (
        <ArtifactPresentationStage
          agentId={activeAgentId}
          artifacts={presentationArtifacts}
          layout={presentationStage.layout}
          activeIndex={presentationStage.activeIndex}
          mediaCommand={presentationStage.mediaCommand}
          onClose={() => setPresentationStage(null)}
          onActiveIndexChange={(activeIndex) => setPresentationStage((current) => (
            current ? { ...current, activeIndex } : current
          ))}
          onFollowUp={(prompt) => useCoreStore.getState().setDraft(prompt)}
        />
      )}
    </div>
  );
}

function DreamingNotice({ agentName }: { agentName: string }) {
  const { t } = useTranslation();
  return (
    <div className="dreaming-message-notice" role="status">
      <Icon name="moon" size={16} />
      <div>
        <strong>{t("home.dreamingTitle", { name: agentName })}</strong>
        <span>{t("home.dreamingNotice")}</span>
      </div>
    </div>
  );
}

function livingStateName(state: import("../../store").AgentStateSnapshot["living"], t: (key: string) => string): string {
  return {
    dormant: t("home.livingDormant"),
    waking: t("home.livingWaking"),
    awake: t("home.livingAwake"),
    idle: t("home.agentReady"),
    working: t("sidebar.agentWorking"),
    sleeping: t("home.livingSleeping"),
    dreaming: t("home.livingDreaming"),
  }[state];
}

// ── 解析 ANSI 转义码，分离思考内容和正文 ──

function parseThinkingContent(raw: string, streaming: boolean): { thinking: string; content: string } {
  const ansiDim = /\x1b\[2m([\s\S]*?)\x1b\[0m/g;
  const thinkingParts: string[] = [];
  let content = raw.replace(ansiDim, (_, t) => {
    thinkingParts.push(t.trim());
    return "";
  });
  const bareDim = /\[2m([\s\S]*?)\[0m/g;
  content = content.replace(bareDim, (_, t) => {
    thinkingParts.push(t.trim());
    return "";
  });

  if (streaming) {
    const openTag = /\x1b\[2m([\s\S]*?)$/;
    const m = content.match(openTag);
    if (m) {
      thinkingParts.push(m[1].trim());
      content = content.replace(openTag, "");
    }
    const bareOpen = /\[2m([\s\S]*?)$/;
    const bm = content.match(bareOpen);
    if (bm) {
      thinkingParts.push(bm[1].trim());
      content = content.replace(bareOpen, "");
    }
  }

  return {
    thinking: thinkingParts.join("\n\n").trim(),
    content: content.trim(),
  };
}

function MessageRow({
  message,
  agentName,
  showAgentHeader,
  highlighted,
  turnUsage,
  contextPressure,
  onShowArtifact,
  onMaximizeVisualization,
  onPresentArtifact,
  onShowMemories,
}: {
  message: DisplayMessage;
  agentName: string;
  showAgentHeader: boolean;
  highlighted: boolean;
  turnUsage?: TokenUsageTurn;
  contextPressure?: ContextTokenPressure;
  onShowArtifact: (artifactId: string, sessionId: string) => void;
  onMaximizeVisualization: () => void;
  onPresentArtifact: (artifactKey: string) => void;
  onShowMemories: (references: MemoryReference[]) => void;
}) {
  const { t } = useTranslation();
  const isUser = message.role === "user";
  const [thinkingExpanded, setThinkingExpanded] = useState(false);
  const [messageCopied, setMessageCopied] = useState(false);
  const messageCopyTimerRef = useRef<number>();
  const activeAgentId = useCoreStore((s) => s.activeAgentId || "");
  const activeSessionId = useCoreStore((s) => {
    const agentId = s.activeAgentId || "";
    return s.activeSessionByAgent[agentId] || "";
  });
  const retryMessage = useCoreStore((s) => s.retryMessage);
  const agentSending = useCoreStore((s) => {
    const agentId = s.activeAgentId || "";
    const sessionId = agentId ? s.activeSessionByAgent[agentId] : null;
    return s.sendingByConversation[`${agentId}\u0000${sessionId || "new"}`] || false;
  });

  useEffect(() => () => window.clearTimeout(messageCopyTimerRef.current), []);

  const copyWholeMessage = async (text: string) => {
    await navigator.clipboard.writeText(text);
    setMessageCopied(true);
    window.clearTimeout(messageCopyTimerRef.current);
    messageCopyTimerRef.current = window.setTimeout(() => setMessageCopied(false), 1600);
  };

  if (message.action) {
    return <ActionApprovalCard message={message} agentName={agentName} showAgentHeader={showAgentHeader} />;
  }

  if (message.interaction) {
    return <InteractionCard message={message} agentName={agentName} showAgentHeader={showAgentHeader} />;
  }

  if (message.capabilitySetup) {
    return <CapabilitySetupCard message={message} agentName={agentName} showAgentHeader={showAgentHeader} />;
  }

  if (message.artifact) {
    return (
      <ArtifactCard
        message={message}
        agentName={agentName}
        showAgentHeader={showAgentHeader}
        agentId={activeAgentId}
        sessionId={activeSessionId}
        onShowArtifact={onShowArtifact}
        onMaximizeVisualization={onMaximizeVisualization}
        onPresentArtifact={onPresentArtifact}
      />
    );
  }

  if (message.tool) {
    return <ToolActivityRow message={message} />;
  }

  if (message.serviceError) {
    const canRetry = Boolean(message.serviceError.retryMessageId) && !agentSending;
    return (
      <div className="model-service-error" role="status">
        <div className="model-service-error-icon">
          <Icon name="info" size={17} />
        </div>
        <div className="model-service-error-body">
          <strong>{t("home.unavailable")}</strong>
          <p>{message.serviceError.message}</p>
          <div className="model-service-error-actions">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => openSettingsCenter("models", activeAgentId)}
            >
              {t("home.switchModel")}
            </Button>
            {message.serviceError.retryMessageId && (
              <Button
                variant="secondary"
                size="sm"
                disabled={!canRetry}
                onClick={() => void retryMessage(message.serviceError!.retryMessageId!)}
              >
                {t("home.retry")}
              </Button>
            )}
          </div>
        </div>
      </div>
    );
  }

  if (isUser) {
    return (
      <div
        id={`conversation-message-${message.id}`}
        className={`user-message-row ${highlighted ? "search-message-highlight" : ""}`}
      >
        <div className="user-message-stack">
          <div className="user-message-bubble">
            {message.invocation && (
              <div
                className="message-invocation-chip"
                title={message.invocation.name || message.invocation.id}
              >
                <span className={`slash-invocation-kind is-${message.invocation.kind}`}>
                  {message.invocation.kind === "capability" ? t("home.kindCapability") : message.invocation.kind === "skill" ? t("home.kindSkill") : t("home.kindProcess")}
                </span>
                <span>
                  {message.invocation.id}
                  {message.invocation.processTemplateId ? ` · ${message.invocation.processTemplateId}` : ""}
                </span>
              </div>
            )}
            {message.attachments && message.attachments.length > 0 && (
              <div className="message-attachments">
                {message.attachments.map((attachment) => (
                  <MessageAttachment
                    attachment={attachment}
                    agentId={activeAgentId}
                    sessionId={activeSessionId}
                    key={attachment.id}
                  />
                ))}
              </div>
            )}
            {message.content && <div>{message.content}</div>}
            {message.deliveryStatus === "failed" &&
              !message.deliveryErrorCode?.startsWith("MODEL_") &&
              message.sourceMessageId && (
                <button
                  type="button"
                  className="message-retry"
                  disabled={agentSending}
                  onClick={() => void retryMessage(message.sourceMessageId!)}
                >
                  {t("home.retry")}
                </button>
              )}
            {message.deliveryStatus && ["queued", "failed", "interrupted"].includes(message.deliveryStatus) && (
              <div className={`message-delivery-status ${message.deliveryStatus}`}>
                {message.deliveryStatus === "queued" && t("home.queued")}
                {message.deliveryStatus === "failed" && (
                  message.deliveryErrorCode?.startsWith("MODEL_")
                    ? t("home.modelUnavailable")
                    : `${t("home.processingFailed")}${message.deliveryError ? `: ${message.deliveryError}` : ""}`
                )}
                {message.deliveryStatus === "interrupted" && t("home.interrupted")}
              </div>
            )}
          </div>
          <div className="user-message-meta">
            {message.createdAt && (
              <time dateTime={new Date(message.createdAt).toISOString()}>
                {formatMessageTime(message.createdAt)}
              </time>
            )}
            <button
              type="button"
              title={t("home.copyMessage")}
              onClick={() => void copyWholeMessage(message.content)}
            >
              <Icon name="copy" size={13} />
              <span>{messageCopied ? t("common.copied") : t("common.copy")}</span>
            </button>
          </div>
        </div>
      </div>
    );
  }

  const parsed = parseThinkingContent(message.content, message.streaming);
  const structuredThinking = message.reasoningContent?.trim() || "";
  const thinking = structuredThinking || parsed.thinking;
  const hasThinking = thinking.length > 0;
  const displayedContent = parsed.thinking ? parsed.content : message.content;
  const thinkingComplete = Boolean(structuredThinking)
    || !message.streaming
    || /\x1b\[0m/.test(message.content)
    || /\[0m/.test(message.content);

  return (
    <div
      id={`conversation-message-${message.id}`}
      className={`assistant-message-row ${showAgentHeader ? "" : "agent-turn-continuation"} ${highlighted ? "search-message-highlight" : ""}`}
    >
      {displayedContent.trim() && (
        <button
          type="button"
          className="message-copy-action"
          title={t("home.copyAnswer")}
          onClick={() => void copyWholeMessage(displayedContent)}
        >
          <Icon name="copy" size={14} />
          <span>{messageCopied ? t("common.copied") : t("common.copy")}</span>
        </button>
      )}
      {showAgentHeader && (
        <div className="assistant-avatar">
          <div className="assistant-avatar-face">
            {agentName.charAt(0)}
          </div>
          <span className="assistant-avatar-name">{agentName}</span>
        </div>
      )}
      {message.responsePhase && !message.content.trim() && (
        <div className={`agent-response-phase is-${message.responsePhase}`} role="status">
          <span className="agent-response-phase-dot" aria-hidden="true" />
          <span>
            {message.responsePhase === "waiting"
              ? t("home.responseWaiting")
              : message.responsePhase === "thinking"
                ? t("home.deepThinking")
                : t("home.replying")}
          </span>
        </div>
      )}
      {hasThinking && (
        <div className={`thinking-block ${!thinkingExpanded ? "thinking-collapsed" : ""} ${thinkingComplete ? "thinking-complete" : ""}`}>
          <div
            className={`thinking-header ${!thinkingComplete ? "thinking-loading" : ""}`}
            onClick={() => setThinkingExpanded(!thinkingExpanded)}
          >
            <span className="thinking-title">
              {thinkingComplete ? t("home.deepThink") : t("home.deepThinking")}
            </span>
            {thinkingComplete && (
              <span className={`thinking-chevron ${thinkingExpanded ? "expanded" : ""}`}>▼</span>
            )}
          </div>
          {thinkingExpanded && (
            <div className="thinking-content">
              {thinking}
            </div>
          )}
        </div>
      )}
      <div className="assistant-text-content">
        <MarkdownMessage
          content={displayedContent}
          streaming={message.streaming}
        />
      </div>
      {(!message.streaming && (turnUsage || contextPressure?.available))
        || (message.memoryReferences && message.memoryReferences.length > 0) ? (
        <div className="message-hover-metadata">
          {turnUsage && !message.streaming && (
            <div
              className="message-token-usage"
              title={t("usage.turnDetails", {
                input: formatTokens(turnUsage.input_tokens),
                output: formatTokens(turnUsage.output_tokens),
                latency: (turnUsage.latency_ms / 1000).toFixed(1),
              })}
            >
              <span>
                {turnUsage.estimated_calls > 0 ? "≈" : ""}
                {t("usage.input")} {formatTokens(turnUsage.input_tokens)}
              </span>
              <span>·</span>
              <span>{t("usage.output")} {formatTokens(turnUsage.output_tokens)}</span>
              <span>·</span>
              <span>{t("usage.callCount", { count: turnUsage.calls })}</span>
              <span>·</span>
              <span>{(turnUsage.latency_ms / 1000).toFixed(1)}s</span>
            </div>
          )}
          {turnUsage && turnUsage.tool_input_tokens > 0 && (
            <span className="message-input-component">
              {t("usage.component.tools")} {formatTokens(turnUsage.tool_input_tokens)}
            </span>
          )}
          {turnUsage && turnUsage.skill_input_tokens > 0 && (
            <span className="message-input-component">
              Skill {formatTokens(turnUsage.skill_input_tokens)}
            </span>
          )}
          {contextPressure?.available && !message.streaming && (
            <span
              className={`message-context-pressure${contextPressure.reached ? " is-reached" : ""}`}
              title={t("usage.contextPressureHint", {
                current: formatTokens(contextPressure.message_tokens),
                threshold: formatTokens(contextPressure.trigger_tokens),
                percent: Math.round(contextPressure.pressure_ratio * 100),
              })}
            >
              {t("usage.contextPressure", {
                current: formatTokens(contextPressure.message_tokens),
                threshold: formatTokens(contextPressure.trigger_tokens),
              })}
              <span>·</span>
              <span>{contextPressure.reached
                ? t("usage.contextPressureReached")
                : `${Math.round(contextPressure.pressure_ratio * 100)}%`}</span>
            </span>
          )}
          {message.memoryReferences && message.memoryReferences.length > 0 && (
            <button
              type="button"
              className="message-memory-reference"
              onClick={() => onShowMemories(message.memoryReferences || [])}
            >
              <Icon name="sparkles" size={13} />
              {t("home.memoryReferences", { count: message.memoryReferences.length })}
            </button>
          )}
        </div>
      ) : null}
    </div>
  );
}

function formatMessageTime(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function MessageAttachment({
  attachment,
  agentId,
  sessionId,
}: {
  attachment: NonNullable<DisplayMessage["attachments"]>[number];
  agentId: string;
  sessionId: string;
}) {
  const { t } = useTranslation();
  const [previewUrl, setPreviewUrl] = useState(attachment.previewUrl || "");
  const [error, setError] = useState("");
  const [previewOpen, setPreviewOpen] = useState(false);
  const [audioPlaying, setAudioPlaying] = useState(false);
  const [audioDuration, setAudioDuration] = useState(0);
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    setPreviewUrl(attachment.previewUrl || "");
    setError("");
    if (
      (attachment.kind !== "image" && attachment.kind !== "audio")
      || attachment.previewUrl
      || !agentId
      || !sessionId
    ) return;
    let cancelled = false;
    void window.gateway.getAttachment({
      agentId,
      sessionId,
      attachmentId: attachment.id,
    }).then((response) => {
      if (cancelled) return;
      if (response.error) {
        setError(response.error.message);
        return;
      }
      const value = response.result?.attachment;
      if (!value || typeof value !== "object" || Array.isArray(value)) {
        setError(t("home.invalidAttachment"));
        return;
      }
      const item = value as Record<string, unknown>;
      const dataBase64 = typeof item.dataBase64 === "string" ? item.dataBase64 : "";
      const mimeType = typeof item.mimeType === "string" ? item.mimeType : attachment.mimeType;
      if (!dataBase64) {
        setError(t("home.emptyAttachment"));
        return;
      }
      setPreviewUrl(`data:${mimeType};base64,${dataBase64}`);
    }).catch((reason) => {
      if (!cancelled) setError(String(reason));
    });
    return () => { cancelled = true; };
  }, [agentId, attachment.id, attachment.kind, attachment.mimeType, attachment.previewUrl, sessionId]);

  useEffect(() => () => {
    audioRef.current?.pause();
  }, []);

  const open = async () => {
    if (!agentId || !sessionId) return;
    const result = await window.gateway.openAttachment({
      agentId,
      sessionId,
      attachmentId: attachment.id,
    });
    setError(result.ok ? "" : result.error || t("home.openAttachmentFailed"));
  };

  const toggleAudio = async () => {
    const audio = audioRef.current;
    if (!audio) {
      if (error) await open();
      return;
    }
    try {
      if (audio.paused) await audio.play();
      else audio.pause();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  if (attachment.kind === "audio") {
    return (
      <button
        type="button"
        className={`message-voice-attachment ${audioPlaying ? "is-playing" : ""} ${error ? "error" : ""}`}
        onClick={() => { void toggleAudio(); }}
        title={error || t("home.voiceConversation")}
      >
        {previewUrl && (
          <audio
            ref={audioRef}
            src={previewUrl}
            preload="metadata"
            onLoadedMetadata={(event) => {
              const duration = event.currentTarget.duration;
              setAudioDuration(Number.isFinite(duration) ? duration : 0);
            }}
            onPlay={() => setAudioPlaying(true)}
            onPause={() => setAudioPlaying(false)}
            onEnded={() => setAudioPlaying(false)}
          />
        )}
        <span className="message-voice-control" aria-hidden="true">
          <span className={audioPlaying ? "voice-pause-symbol" : "voice-play-symbol"} />
        </span>
        <span className="message-voice-wave" aria-hidden="true">
          {[5, 9, 14, 8, 18, 12, 7, 16, 10, 6, 13, 9].map((height, index) => (
            <i key={`${height}-${index}`} style={{ height }} />
          ))}
        </span>
        <span className="message-voice-duration">
          {audioDuration > 0 ? formatAudioDuration(audioDuration) : error ? t("home.unablePlay") : t("home.audio")}
        </span>
      </button>
    );
  }

  if (attachment.kind === "image") {
    return (
      <>
        <button
          type="button"
          className={`message-inline-image ${error ? "error" : ""}`}
          onClick={() => previewUrl ? setPreviewOpen(true) : void open()}
          title={error || attachment.name}
        >
          {previewUrl ? (
            <img src={previewUrl} alt={attachment.name} />
          ) : (
            <span className="message-inline-image-loading">{error ? "!" : "IMG"}</span>
          )}
          <span>{attachment.name}</span>
        </button>
        {previewOpen && previewUrl && (
          <ImageLightbox
            src={previewUrl}
            name={attachment.name}
            onClose={() => setPreviewOpen(false)}
            onOpenOriginal={() => void open()}
          />
        )}
      </>
    );
  }

  const fileButton = (
    <button
      type="button"
      className={`message-attachment ${attachment.kind}`}
      onClick={() => { void open(); }}
      title={error || t("home.openAttachment", { name: attachment.name })}
    >
      {previewUrl ? (
        <img src={previewUrl} alt={attachment.name} />
      ) : (
        <span className={`message-attachment-icon ${error ? "error" : ""}`}>
          {error
            ? "!"
            : attachment.kind === "video"
                ? "VIDEO"
              : t("home.file")}
        </span>
      )}
      <span className="message-attachment-name">{attachment.name}</span>
    </button>
  );
  if (!attachment.annotation) return fileButton;
  return (
    <div className="message-attachment-reference">
      {fileButton}
      <blockquote title={attachment.annotation.selectedText}>
        {attachment.annotation.sheet && attachment.annotation.range
          ? `${attachment.annotation.sheet}!${attachment.annotation.range} · `
          : attachment.annotation.page ? `${t("preview.selectedPage", { page: attachment.annotation.page })} · ` : ""}
        {attachment.annotation.selectedText}
      </blockquote>
    </div>
  );
}

function formatAudioDuration(seconds: number): string {
  const rounded = Math.max(1, Math.round(seconds));
  const minutes = Math.floor(rounded / 60);
  const remainder = rounded % 60;
  return minutes > 0 ? `${minutes}:${String(remainder).padStart(2, "0")}` : `${remainder}″`;
}

function ArtifactCard({
  message,
  agentName,
  showAgentHeader,
  agentId,
  sessionId,
  onShowArtifact,
  onMaximizeVisualization,
  onPresentArtifact,
}: {
  message: DisplayMessage;
  agentName: string;
  showAgentHeader: boolean;
  agentId: string;
  sessionId: string;
  onShowArtifact: (artifactId: string, sessionId: string) => void;
  onMaximizeVisualization: () => void;
  onPresentArtifact: (artifactKey: string) => void;
}) {
  const { t } = useTranslation();
  const storedArtifact = useCoreStore((state) => (
    state.artifactsByAgent[agentId] || []
  ).find((item) => item.id === message.artifact?.id && item.sessionId === sessionId));
  const artifact = storedArtifact || message.artifact!;
  const [previewUrl, setPreviewUrl] = useState("");
  const [visualizationData, setVisualizationData] = useState("");
  const [error, setError] = useState("");
  const [opening, setOpening] = useState(false);
  const [playing, setPlaying] = useState(false);
  const previewSupported = supportsArtifactPreview(artifact);
  const setDraft = useCoreStore((state) => state.setDraft);

  useEffect(() => {
    setPreviewUrl("");
    setVisualizationData("");
    setError("");
    if (
      !["image", "visualization"].includes(artifact.kind)
      || artifact.size > 20 * 1024 * 1024
      || !agentId
      || !sessionId
    ) return;
    let cancelled = false;
    void window.gateway.getArtifact({ agentId, sessionId, artifactId: artifact.id })
      .then((response) => {
        if (cancelled) return;
        if (response.error) {
          setError(response.error.message);
          return;
        }
        const raw = response.result?.artifact;
        if (!raw || typeof raw !== "object" || Array.isArray(raw)) return;
        const value = raw as Record<string, unknown>;
        const data = typeof value.dataBase64 === "string" ? value.dataBase64 : "";
        const mime = typeof value.mimeType === "string" ? value.mimeType : artifact.mimeType;
        if (data && artifact.kind === "visualization") setVisualizationData(data);
        else if (data) setPreviewUrl(`data:${mime};base64,${data}`);
      })
      .catch((reason) => { if (!cancelled) setError(String(reason)); });
    return () => { cancelled = true; };
  }, [
    agentId,
    artifact.id,
    artifact.kind,
    artifact.mimeType,
    artifact.size,
    storedArtifact?.updatedAt,
    sessionId,
  ]);

  const open = async () => {
    if (!agentId || !sessionId || opening) return;
    setOpening(true);
    try {
      const result = await window.gateway.openArtifact({
        agentId, sessionId, artifactId: artifact.id,
      });
      setError(result.ok ? "" : result.error || t("preview.openFailed"));
    } finally {
      setOpening(false);
    }
  };

  const playAudio = async () => {
    if (!agentId || !sessionId || playing) return;
    setPlaying(true);
    try {
      const response = await window.gateway.authorizeArtifactMedia({
        agentId,
        sessionId,
        artifactId: artifact.id,
      });
      if (response.error) {
        setError(response.error.message);
        return;
      }
      enqueueMediaFilePlayback(agentId, response.result || {});
      setError("");
    } catch (reason) {
      setError(String(reason));
    } finally {
      setPlaying(false);
    }
  };

  const size = artifact.size < 1024
    ? `${artifact.size} B`
    : artifact.size < 1024 * 1024
      ? `${(artifact.size / 1024).toFixed(1)} KB`
      : `${(artifact.size / 1024 / 1024).toFixed(1)} MB`;

  if (artifact.kind === "visualization") {
    const visualizationKey = `${sessionId}:${artifact.id}`;
    return (
      <div className={`assistant-message-row artifact-message-row visualization-message-row ${showAgentHeader ? "" : "agent-turn-continuation"}`}>
        {showAgentHeader && (
          <div className="assistant-avatar">
            <div className="assistant-avatar-face">{agentName.charAt(0)}</div>
            <span className="assistant-avatar-name">{agentName}</span>
          </div>
        )}
        {visualizationData ? (
          <VisualizationPreview
            dataBase64={visualizationData}
            fileName={artifact.name}
            inline
            onExpand={onMaximizeVisualization}
            onFullscreen={() => onPresentArtifact(visualizationKey)}
            onFollowUp={(prompt) => setDraft(prompt)}
          />
        ) : (
          <div className="visualization-inline-loading">
            <Icon name="sparkles" size={18} />
            {error || t("visualize.loading")}
          </div>
        )}
      </div>
    );
  }

  if (artifact.kind === "image") {
    return (
      <div className={`assistant-message-row artifact-image-message-row ${showAgentHeader ? "" : "agent-turn-continuation"}`}>
        {showAgentHeader && (
          <div className="assistant-avatar">
            <div className="assistant-avatar-face">{agentName.charAt(0)}</div>
            <span className="assistant-avatar-name">{agentName}</span>
          </div>
        )}
        <div className="artifact-inline-image-group">
          <button
            type="button"
            className={`artifact-inline-image ${error ? "error" : ""}`}
            onClick={() => onShowArtifact(artifact.id, sessionId)}
            disabled={opening}
            title={error || `${t("common.preview")} ${artifact.name}`}
          >
            {previewUrl ? (
              <img src={previewUrl} alt={artifact.name} />
            ) : (
              <span className="artifact-inline-image-loading">
                <Icon name="sparkles" size={22} />
                {error || t("home.loadImage")}
              </span>
            )}
          </button>
          <div className="artifact-inline-image-meta">
            <span title={artifact.name}>{artifact.name}</span>
            <div>
              <button type="button" onClick={() => onShowArtifact(artifact.id, sessionId)}>
                {t("common.preview")}
              </button>
              <button
                type="button"
                onClick={() => onPresentArtifact(`${sessionId}:${artifact.id}`)}
                title={t("visualize.fullscreen")}
                aria-label={t("visualize.fullscreen")}
              >
                <Icon name="maximize" size={14} />
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`assistant-message-row artifact-message-row ${showAgentHeader ? "" : "agent-turn-continuation"}`}>
      {showAgentHeader && (
        <div className="assistant-avatar">
          <div className="assistant-avatar-face">{agentName.charAt(0)}</div>
          <span className="assistant-avatar-name">{agentName}</span>
        </div>
      )}
      <div className="artifact-card-group">
        <button
          type="button"
          className={`artifact-card artifact-${artifact.kind}`}
          onClick={() => artifact.kind === "audio"
            ? void playAudio()
            : previewSupported ? onShowArtifact(artifact.id, sessionId) : void open()}
          disabled={opening || playing}
          title={error || `${artifact.kind === "audio"
            ? t("mediaPlayer.play")
            : previewSupported ? t("common.preview") : t("common.open")} ${artifact.name}`}
        >
          {previewUrl ? (
            <img className="artifact-preview" src={previewUrl} alt={artifact.name} />
          ) : (
            <span className={`artifact-icon ${error ? "error" : ""}`}>
              <Icon name={artifact.kind === "audio" ? "play" : "file-text"} size={20} />
            </span>
          )}
          <span className="artifact-info">
            <span className="artifact-label">{t("home.artifactLabel")}</span>
            <span className="artifact-name">{artifact.name}</span>
            <span className="artifact-meta">
              {size} · {playing
                ? t("mediaPlayer.loading")
                : opening ? t("home.opening")
                  : artifact.kind === "audio" ? t("mediaPlayer.play")
                    : previewSupported ? t("home.preview") : t("home.open")}
            </span>
            {error && <span className="artifact-error">{error}</span>}
          </span>
          <Icon
            name={artifact.kind === "audio" ? "play" : previewSupported ? "eye" : "external-link"}
            size={16}
            className="artifact-open-icon"
          />
        </button>
        <button
          type="button"
          className="artifact-present-button"
          onClick={() => onPresentArtifact(`${sessionId}:${artifact.id}`)}
          title={t("visualize.fullscreen")}
          aria-label={t("visualize.fullscreen")}
        >
          <Icon name="maximize" size={15} />
        </button>
      </div>
    </div>
  );
}

function ImageLightbox({
  src,
  name,
  onClose,
  onOpenOriginal,
}: {
  src: string;
  name: string;
  onClose: () => void;
  onOpenOriginal: () => void;
}) {
  const { t } = useTranslation();
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div className="message-image-lightbox" role="dialog" aria-modal="true" aria-label={name} onClick={onClose}>
      <div className="message-image-lightbox-toolbar" onClick={(event) => event.stopPropagation()}>
        <span title={name}>{name}</span>
        <button type="button" onClick={onOpenOriginal}>
          <Icon name="external-link" size={15} />
          {t("home.openOriginal")}
        </button>
        <button type="button" className="message-image-lightbox-close" onClick={onClose} aria-label={t("common.close")}>
          ×
        </button>
      </div>
      <img src={src} alt={name} onClick={(event) => event.stopPropagation()} />
    </div>
  );
}

function ActionApprovalCard({ message, agentName, showAgentHeader }: {
  message: DisplayMessage;
  agentName: string;
  showAgentHeader: boolean;
}) {
  const { t } = useTranslation();
  const action = message.action!;
  const respondToAction = useCoreStore((s) => s.respondToAction);
  const canRespond = action.status === "pending" || action.status === "error";
  const command = typeof action.arguments.command === "string" ? action.arguments.command : "";

  const respond = (decision: "allow" | "deny") => {
    if (!canRespond) return;
    void respondToAction(action.id, decision);
  };

  return (
    <div className={`assistant-message-row interaction-message-row ${showAgentHeader ? "" : "agent-turn-continuation"}`}>
      {showAgentHeader && (
        <div className="assistant-avatar">
          <div className="assistant-avatar-face">{agentName.charAt(0)}</div>
          <span className="assistant-avatar-name">{agentName}</span>
        </div>
      )}
      <div className={`interaction-card action-card action-${action.status}`}>
        <div className="interaction-card-label action-card-label">
          {t("home.actionLabel")}
          <span className={`action-risk action-risk-${action.riskLevel}`}>
            {t(`home.actionRisk_${action.riskLevel}`, { defaultValue: action.riskLevel })}
          </span>
        </div>
        <div className="interaction-card-question">{action.summary}</div>
        {action.reason && <div className="action-card-reason">{action.reason}</div>}
        {command && <pre className="action-card-command">{command}</pre>}
        {canRespond && (
          <div className="interaction-card-choices action-card-actions">
            <button type="button" className="action-deny" onClick={() => respond("deny")}>
              {t("home.actionDeny")}
            </button>
            <button type="button" className="action-allow" onClick={() => respond("allow")}>
              {t("home.actionAllowOnce")}
            </button>
          </div>
        )}
        {action.status === "responding" && (
          <div className="interaction-card-status">{t("home.actionResponding")}</div>
        )}
        {action.status === "completed" && (
          <div className="interaction-card-status interaction-card-result">{t("home.actionCompleted")}</div>
        )}
        {action.status === "rejected" && (
          <div className="interaction-card-status">{t("home.actionRejected")}</div>
        )}
        {action.status === "cancelled" && (
          <div className="interaction-card-status">{t("home.actionCancelled")}</div>
        )}
        {action.status === "expired" && (
          <div className="interaction-card-status">{t("home.actionExpired")}</div>
        )}
        {(action.status === "failed" || action.status === "error") && (
          <div className="interaction-card-error">{action.error || t("home.actionFailed")}</div>
        )}
      </div>
    </div>
  );
}

function ToolActivityRow({ message }: { message: DisplayMessage }) {
  const { t } = useTranslation();
  const tool = message.tool!;
  const running = tool.status === "running";
  const failed = tool.status === "error";
  const title = running
    ? t("home.toolRunning", { name: tool.name })
    : failed
      ? t("home.toolError", { name: tool.name })
      : t("home.toolComplete", { name: tool.name });
  const hasArguments = Object.keys(tool.arguments).length > 0;
  const hasDetails = hasArguments || Boolean(tool.summary) || Boolean(tool.error);
  const duration = formatToolDuration(tool.durationMs);

  return (
    <div className={`tool-activity tool-${tool.status}`}>
      <span className="tool-activity-indicator" aria-hidden="true" />
      <div className="tool-activity-body">
        {hasDetails && !running ? (
          <details className="tool-activity-details">
            <summary className="tool-activity-title">
              <span>{title}</span>
              {duration && <span className="tool-activity-duration">{duration}</span>}
            </summary>
            {hasArguments && (
              <div className="tool-activity-section">
                <span>{t("home.toolArguments")}</span>
                <pre>{JSON.stringify(tool.arguments, null, 2)}</pre>
              </div>
            )}
            {(tool.error || tool.summary) && (
              <div className="tool-activity-section">
                <span>{failed ? t("home.toolErrorDetail") : t("home.toolResult")}</span>
                <pre>{tool.error || tool.summary}{tool.truncated ? "…" : ""}</pre>
              </div>
            )}
          </details>
        ) : (
          <div className="tool-activity-title">
            <span>{title}</span>
            {duration && <span className="tool-activity-duration">{duration}</span>}
          </div>
        )}
      </div>
    </div>
  );
}

function ToolActivityGroup({ messages }: { messages: DisplayMessage[] }) {
  const { t } = useTranslation();
  const running = messages.some((message) => message.tool?.status === "running");
  const failed = messages.some((message) => message.tool?.status === "error");
  const musicToolCallId = [...messages]
    .reverse()
    .find((message) => message.tool?.name === "play_music")
    ?.tool?.id || "";
  return (
    <>
      <div className={`tool-process ${running ? "tool-process-running" : ""} ${failed ? "tool-process-error" : ""}`}>
        <div className="tool-process-header">
          <Icon name="terminal" size={14} />
          <span>{t("home.toolProcess")}</span>
          <span className="tool-process-count">{t("home.toolCount", { count: messages.length })}</span>
        </div>
        <div className="tool-process-list">
          {messages.map((message) => <ToolActivityRow key={message.id} message={message} />)}
        </div>
      </div>
      {musicToolCallId && <MusicPlayer variant="inline" toolCallId={musicToolCallId} />}
    </>
  );
}

function formatToolDuration(durationMs: number | undefined): string {
  if (typeof durationMs !== "number" || !Number.isFinite(durationMs)) return "";
  if (durationMs < 1000) return `${Math.max(1, Math.round(durationMs))} ms`;
  if (durationMs < 60_000) {
    const seconds = durationMs / 1000;
    return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} s`;
  }
  const minutes = Math.floor(durationMs / 60_000);
  const seconds = Math.round((durationMs % 60_000) / 1000);
  return `${minutes} min ${seconds} s`;
}

function InteractionCard({ message, agentName, showAgentHeader }: {
  message: DisplayMessage;
  agentName: string;
  showAgentHeader: boolean;
}) {
  const { t } = useTranslation();
  const interaction = message.interaction!;
  const respondToInteraction = useCoreStore((s) => s.respondToInteraction);
  const [answer, setAnswer] = useState("");
  const canRespond = interaction.status === "pending" || interaction.status === "error";
  const waiting = interaction.status === "responding";

  const submit = (response: string) => {
    if (!canRespond || !response.trim()) return;
    void respondToInteraction(interaction.id, response.trim());
  };

  return (
    <div className={`assistant-message-row interaction-message-row ${showAgentHeader ? "" : "agent-turn-continuation"}`}>
      {showAgentHeader && (
        <div className="assistant-avatar">
          <div className="assistant-avatar-face">{agentName.charAt(0)}</div>
          <span className="assistant-avatar-name">{agentName}</span>
        </div>
      )}
      <div className={`interaction-card interaction-${interaction.status}`}>
        <div className="interaction-card-label">{t("home.interactionLabel")}</div>
        <div className="interaction-card-question">{interaction.question}</div>
        {canRespond && interaction.choices.length > 0 && (
          <div className="interaction-card-choices">
            {interaction.choices.map((choice) => (
              <button type="button" key={choice} onClick={() => submit(choice)}>
                {choice}
              </button>
            ))}
          </div>
        )}
        {canRespond && interaction.choices.length === 0 && (
          <form
            className="interaction-card-answer"
            onSubmit={(event) => {
              event.preventDefault();
              submit(answer);
            }}
          >
            <input
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
              placeholder={t("home.interactionAnswerPlaceholder")}
              autoFocus
            />
            <button type="submit" disabled={!answer.trim()}>{t("home.interactionSubmit")}</button>
          </form>
        )}
        {waiting && <div className="interaction-card-status">{t("home.interactionSending")}</div>}
        {interaction.status === "answered" && (
          <div className="interaction-card-status interaction-card-result">
            {t("home.interactionAnswered", { answer: interaction.response })}
          </div>
        )}
        {interaction.status === "expired" && (
          <div className="interaction-card-status">{t("home.interactionExpired")}</div>
        )}
        {interaction.status === "cancelled" && (
          <div className="interaction-card-status">{t("home.interactionCancelled")}</div>
        )}
        {interaction.status === "error" && interaction.error && (
          <div className="interaction-card-error">{interaction.error}</div>
        )}
      </div>
    </div>
  );
}

function CapabilitySetupCard({ message, agentName, showAgentHeader }: {
  message: DisplayMessage;
  agentName: string;
  showAgentHeader: boolean;
}) {
  const { t } = useTranslation();
  const setup = message.capabilitySetup!;
  const activeAgentId = useCoreStore((state) => state.activeAgentId || "");
  const connectionStatus = useCoreStore((state) => (
    state.connectionByAgent[state.activeAgentId || ""]?.status || "disconnected"
  ));
  const resumeCapabilityRequest = useCoreStore((state) => state.resumeCapabilityRequest);
  const [resumeBusy, setResumeBusy] = useState(false);
  const [resumeError, setResumeError] = useState("");
  const [runtimeStatus, setRuntimeStatus] = useState(setup.status);
  const [statusLoading, setStatusLoading] = useState(false);
  const supportedSections = new Set([
    "overview", "capabilities", "models", "media", "search", "channels",
  ]);
  const refreshStatus = useCallback(async () => {
    if (!activeAgentId || connectionStatus !== "connected") return;
    setStatusLoading(true);
    try {
      const response = await window.gateway.getCapability({
        agentId: activeAgentId,
        capabilityId: setup.capabilityId,
      });
      const capability = response.result?.capability;
      if (!response.error && capability && typeof capability === "object") {
        const status = (capability as Record<string, unknown>).status;
        if (typeof status === "string") setRuntimeStatus(status);
      }
    } finally {
      setStatusLoading(false);
    }
  }, [activeAgentId, connectionStatus, setup.capabilityId]);

  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  useEffect(() => {
    const handleChanged = (event: Event) => {
      const detail = (event as CustomEvent<{ agentId?: string; capabilityId?: string }>).detail;
      if (detail?.agentId !== activeAgentId) return;
      if (detail.capabilityId && detail.capabilityId !== setup.capabilityId) return;
      void refreshStatus();
    };
    window.addEventListener(CAPABILITY_STATUS_CHANGED_EVENT, handleChanged);
    return () => window.removeEventListener(CAPABILITY_STATUS_CHANGED_EVENT, handleChanged);
  }, [activeAgentId, refreshStatus, setup.capabilityId]);

  const ready = runtimeStatus === "ready" || runtimeStatus === "degraded";
  const statusText = setup.resumeStatus === "resumed"
    ? t("home.capabilityResumed")
    : statusLoading
      ? t("home.capabilityChecking")
      : connectionStatus !== "connected"
        ? t("home.capabilityOffline")
        : runtimeStatus === "preparing"
          ? t("home.capabilityRestartRequired")
          : runtimeStatus === "needs_setup"
            ? t("home.capabilityNeedsSetup")
            : runtimeStatus === "disabled"
              ? t("home.capabilityDisabled")
              : ready
                ? t("home.capabilityReady")
                : t("home.capabilityUnavailable");

  return (
    <div className={`assistant-message-row interaction-message-row ${showAgentHeader ? "" : "agent-turn-continuation"}`}>
      {showAgentHeader && (
        <div className="assistant-avatar">
          <div className="assistant-avatar-face">{agentName.charAt(0)}</div>
          <span className="assistant-avatar-name">{agentName}</span>
        </div>
      )}
      <div className="interaction-card capability-setup-card">
        <div className="capability-setup-heading">
          <span className="capability-setup-icon"><Icon name="settings" size={16} /></span>
          <div>
            <div className="interaction-card-label">{t("home.capabilitySetupTitle")}</div>
            <div className="capability-setup-name">{setup.capabilityName}</div>
          </div>
        </div>
        <div className="interaction-card-question">{setup.summary}</div>
        <div className={`capability-setup-runtime ${ready ? "ready" : ""} ${setup.resumeStatus === "resumed" ? "resumed" : ""}`}>
          <span />{statusText}
        </div>
        <div className="capability-setup-actions">
          <Button
            size="sm"
            onClick={() => {
              const section = supportedSections.has(setup.action.section)
                ? setup.action.section as SettingsSection
                : "capabilities";
              openSettingsCenter(section, activeAgentId, setup.action.target);
            }}
          >
            {setup.action.label || t("home.goToSettings")}
          </Button>
          {setup.sourceMessageId && setup.resumeStatus !== "resumed" && (
            <Button
              variant="secondary"
              size="sm"
              disabled={resumeBusy || statusLoading || !ready || connectionStatus !== "connected"}
              onClick={async () => {
                setResumeBusy(true);
                setResumeError("");
                const error = await resumeCapabilityRequest(setup.sourceMessageId!);
                setResumeError(error);
                setResumeBusy(false);
              }}
            >
              {resumeBusy ? t("home.resumingTask") : t("home.continueTask")}
            </Button>
          )}
        </div>
        {resumeError && <div className="capability-setup-error">{resumeError}</div>}
      </div>
    </div>
  );
}
