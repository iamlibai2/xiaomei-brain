import { useEffect, useState } from "react";
import { ConversationList } from "./conversation-list/ConversationList";
import { HomePage } from "./home/HomePage";
import { SettingsCenter } from "./settings/SettingsCenter";
import { UnifiedSearchDialog } from "./search/UnifiedSearchDialog";
import { registerEmbodimentCommand } from "../embodiment/command-registry";
import { WorkspacesPage } from "./workspaces/WorkspacesPage";
import { useCoreStore } from "../store";
import { ModelContextDialog } from "./ModelContextDialog";
import { ExecutionAnalysisPanel } from "./ExecutionAnalysisPanel";
import { PromptAnalysisPanel } from "./PromptAnalysisPanel";
import { VectorTracePanel } from "./VectorTracePanel";
import { BrainPanel } from "./BrainPanel";
import { MusicPlayer } from "./music-player/MusicPlayer";
import { MediaLibraryDialog } from "./music-player/MediaLibraryDialog";
import { VideoPlayer } from "./media-player/VideoPlayer";
import { controlMediaPlayback } from "../media-playback";

export function MainShell() {
  const [leftSidebarCollapsed, setLeftSidebarCollapsed] = useState(false);
  const [surface, setSurface] = useState<"chat" | "workspaces">("chat");
  const [requestedWorkspaceId, setRequestedWorkspaceId] = useState("");
  const [analysisPanel, setAnalysisPanel] = useState<"model-context" | "execution" | "prompt" | "vector" | "brain" | null>(null);
  const modelContextOpen = analysisPanel === "model-context";
  const activeAgentId = useCoreStore((state) => state.activeAgentId || "");
  const newSession = useCoreStore((state) => state.newSession);

  useEffect(() => {
    const clearPersonScopedSurface = () => {
      setRequestedWorkspaceId("");
      setSurface("chat");
    };
    window.addEventListener("xiaomei:identity-status-changed", clearPersonScopedSurface);
    window.addEventListener("xiaomei:identity-locked", clearPersonScopedSurface);
    return () => {
      window.removeEventListener("xiaomei:identity-status-changed", clearPersonScopedSurface);
      window.removeEventListener("xiaomei:identity-locked", clearPersonScopedSurface);
    };
  }, []);

  useEffect(() => registerEmbodimentCommand("ui.left_sidebar.set", ({ arguments: args }) => {
    const state = String(args.state || "");
    if (!["open", "closed", "toggle"].includes(state)) {
      return { status: "rejected", error: "无效的左侧栏状态" };
    }
    setLeftSidebarCollapsed((collapsed) => (
      state === "toggle" ? !collapsed : state === "closed"
    ));
    return { status: "completed" };
  }), []);

  useEffect(() => {
    const disposeOpen = registerEmbodimentCommand("ui.workspace.open", ({ arguments: args }) => {
      setRequestedWorkspaceId(String(args.workspace_id || ""));
      setSurface("workspaces");
      return { status: "completed" };
    });
    const disposeClose = registerEmbodimentCommand("ui.workspace.close", () => {
      setSurface("chat");
      return { status: "completed" };
    });
    const disposeState = registerEmbodimentCommand("ui.workspace.state.get", () => ({
      status: "completed",
      result: {
        open: surface === "workspaces",
        workspace_id: requestedWorkspaceId,
      },
    }));
    return () => { disposeOpen(); disposeClose(); disposeState(); };
  }, [requestedWorkspaceId, surface]);

  useEffect(() => {
    const disposers = (["pause", "resume", "stop"] as const).map((action) => (
      registerEmbodimentCommand(`media.player.${action}`, async () => {
        const completed = await controlMediaPlayback(action === "resume" ? "play" : action);
        return completed
          ? { status: "completed" }
          : { status: "rejected", error: "当前没有可执行此操作的音乐" };
      })
    ));
    return () => disposers.forEach((dispose) => dispose());
  }, []);

  useEffect(() => window.gateway.onEvent((event: { event?: string; agentId?: string; data?: unknown }) => {
    if (
      event.agentId !== activeAgentId
      || !["workspace.created", "workspace.updated", "surface.created", "surface.updated"].includes(event.event || "")
    ) return;
    const data = event.data && typeof event.data === "object" ? event.data as Record<string, unknown> : {};
    setRequestedWorkspaceId(String(data.workspace_id || data.id || ""));
    setSurface("workspaces");
  }), [activeAgentId]);

  useEffect(() => {
    const openComparison = () => {
      setSurface("chat");
      setAnalysisPanel("model-context");
      window.dispatchEvent(new CustomEvent("xiaomei:right-sidebar-close"));
    };
    const toggleComparison = () => setAnalysisPanel((current) => {
      if (current !== "model-context") {
        setSurface("chat");
        window.dispatchEvent(new CustomEvent("xiaomei:right-sidebar-close"));
      }
      return current === "model-context" ? null : "model-context";
    });
    const closeComparison = () => setAnalysisPanel(null);
    const openExecution = () => {
      setSurface("chat");
      setAnalysisPanel("execution");
      window.dispatchEvent(new CustomEvent("xiaomei:right-sidebar-close"));
    };
    const toggleExecution = () => setAnalysisPanel((current) => current === "execution" ? null : "execution");
    const openPromptAnalysis = () => {
      setSurface("chat");
      setAnalysisPanel("prompt");
      window.dispatchEvent(new CustomEvent("xiaomei:right-sidebar-close"));
    };
    const openVectorTrace = () => {
      setSurface("chat");
      setAnalysisPanel("vector");
      window.dispatchEvent(new CustomEvent("xiaomei:right-sidebar-close"));
    };
    const openBrain = () => {
      setSurface("chat");
      setAnalysisPanel("brain");
      window.dispatchEvent(new CustomEvent("xiaomei:right-sidebar-close"));
    };
    window.addEventListener("xiaomei:model-context-open", openComparison);
    window.addEventListener("xiaomei:model-context-toggle", toggleComparison);
    window.addEventListener("xiaomei:model-context-close", closeComparison);
    window.addEventListener("xiaomei:execution-analysis-open", openExecution);
    window.addEventListener("xiaomei:execution-analysis-toggle", toggleExecution);
    window.addEventListener("xiaomei:prompt-analysis-open", openPromptAnalysis);
    window.addEventListener("xiaomei:vector-trace-open", openVectorTrace);
    window.addEventListener("xiaomei:brain-open", openBrain);
    return () => {
      window.removeEventListener("xiaomei:model-context-open", openComparison);
      window.removeEventListener("xiaomei:model-context-toggle", toggleComparison);
      window.removeEventListener("xiaomei:model-context-close", closeComparison);
      window.removeEventListener("xiaomei:execution-analysis-open", openExecution);
      window.removeEventListener("xiaomei:execution-analysis-toggle", toggleExecution);
      window.removeEventListener("xiaomei:prompt-analysis-open", openPromptAnalysis);
      window.removeEventListener("xiaomei:vector-trace-open", openVectorTrace);
      window.removeEventListener("xiaomei:brain-open", openBrain);
    };
  }, []);

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if (event.repeat || event.isComposing || event.altKey || !(event.ctrlKey || event.metaKey)) return;
      const code = event.code;
      if (code === "KeyN" && !event.shiftKey) {
        if (document.querySelector('[aria-modal="true"]')) return;
        event.preventDefault();
        setSurface("chat");
        void newSession();
        return;
      }
      if (code === "KeyM" && !event.shiftKey) {
        if (document.querySelector('[aria-modal="true"]')) return;
        event.preventDefault();
        window.dispatchEvent(new CustomEvent("xiaomei:voice-control", {
          detail: { action: "toggle" },
        }));
        return;
      }
      if (code === "KeyM" && event.shiftKey) {
        if (document.querySelector('[aria-modal="true"]')) return;
        event.preventDefault();
        window.dispatchEvent(new CustomEvent("xiaomei:model-context-toggle"));
        return;
      }
      if (code === "KeyE" && event.shiftKey) {
        if (document.querySelector('[aria-modal="true"]')) return;
        event.preventDefault();
        window.dispatchEvent(new CustomEvent("xiaomei:execution-analysis-toggle"));
        return;
      }
      if (code !== "KeyB") return;
      event.preventDefault();
      if (event.shiftKey) {
        window.dispatchEvent(new CustomEvent("xiaomei:right-sidebar-toggle"));
      } else {
        setLeftSidebarCollapsed((collapsed) => !collapsed);
      }
    };
    // Capture before editors and input widgets can consume application-level
    // shortcuts. KeyboardEvent.code also stays stable under Chinese IMEs.
    window.addEventListener("keydown", handleShortcut, true);
    return () => window.removeEventListener("keydown", handleShortcut, true);
  }, [newSession]);

  return (
    <div className={`main-shell${analysisPanel ? " has-analysis-panel" : ""}${analysisPanel === "brain" ? " has-brain-panel" : ""}`}>
      <ConversationList
        collapsed={leftSidebarCollapsed || Boolean(analysisPanel)}
        onCollapsedChange={setLeftSidebarCollapsed}
        surface={surface}
        onOpenChat={() => setSurface("chat")}
        onOpenWorkspaces={() => setSurface("workspaces")}
      />
      <div className="main-shell-content">
      {surface === "workspaces" ? (
        <WorkspacesPage
          preferredWorkspaceId={requestedWorkspaceId}
          onBackToChat={() => setSurface("chat")}
          onEnterConversation={() => setSurface("chat")}
        />
      ) : (
        <HomePage
          leftSidebarCollapsed={leftSidebarCollapsed || Boolean(analysisPanel)}
          onLeftSidebarCollapsedChange={setLeftSidebarCollapsed}
        />
      )}
      {modelContextOpen && (
        <div className="model-context-dock">
          <ModelContextDialog embedded onClose={() => setAnalysisPanel(null)} />
        </div>
      )}
      {analysisPanel === "execution" && (
        <div className="model-context-dock">
          <ExecutionAnalysisPanel onClose={() => setAnalysisPanel(null)} />
        </div>
      )}
      {analysisPanel === "prompt" && (
        <div className="model-context-dock">
          <PromptAnalysisPanel onClose={() => setAnalysisPanel(null)} />
        </div>
      )}
      {analysisPanel === "vector" && (
        <div className="model-context-dock">
          <VectorTracePanel onClose={() => setAnalysisPanel(null)} />
        </div>
      )}
      {analysisPanel === "brain" && (
        <div className="model-context-dock brain-dock">
          <BrainPanel onClose={() => setAnalysisPanel(null)} />
        </div>
      )}
      </div>
      <SettingsCenter />
      <UnifiedSearchDialog />
      {surface === "workspaces" && <MusicPlayer />}
      <VideoPlayer />
      <MediaLibraryDialog />
    </div>
  );
}
