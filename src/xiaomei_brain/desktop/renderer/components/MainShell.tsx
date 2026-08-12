import { useEffect, useState } from "react";
import { ConversationList } from "./conversation-list/ConversationList";
import { HomePage } from "./home/HomePage";
import { SettingsCenter } from "./settings/SettingsCenter";
import { UnifiedSearchDialog } from "./search/UnifiedSearchDialog";
import { registerEmbodimentCommand } from "../embodiment/command-registry";
import { WorkspacesPage } from "./workspaces/WorkspacesPage";
import { useCoreStore } from "../store";
import { ModelContextDialog } from "./ModelContextDialog";
import { MusicPlayer } from "./music-player/MusicPlayer";
import { MediaLibraryDialog } from "./music-player/MediaLibraryDialog";
import { controlMediaPlayback } from "../media-playback";

export function MainShell() {
  const [leftSidebarCollapsed, setLeftSidebarCollapsed] = useState(false);
  const [surface, setSurface] = useState<"chat" | "workspaces">("chat");
  const [requestedWorkspaceId, setRequestedWorkspaceId] = useState("");
  const [modelContextOpen, setModelContextOpen] = useState(false);
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
      setModelContextOpen(true);
      window.dispatchEvent(new CustomEvent("xiaomei:right-sidebar-close"));
    };
    const toggleComparison = () => setModelContextOpen((open) => {
      if (!open) {
        setSurface("chat");
        window.dispatchEvent(new CustomEvent("xiaomei:right-sidebar-close"));
      }
      return !open;
    });
    const closeComparison = () => setModelContextOpen(false);
    window.addEventListener("xiaomei:model-context-open", openComparison);
    window.addEventListener("xiaomei:model-context-toggle", toggleComparison);
    window.addEventListener("xiaomei:model-context-close", closeComparison);
    return () => {
      window.removeEventListener("xiaomei:model-context-open", openComparison);
      window.removeEventListener("xiaomei:model-context-toggle", toggleComparison);
      window.removeEventListener("xiaomei:model-context-close", closeComparison);
    };
  }, []);

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if (event.repeat || event.isComposing || event.altKey || !(event.ctrlKey || event.metaKey)) return;
      if (event.key.toLowerCase() === "n" && !event.shiftKey) {
        if (document.querySelector('[aria-modal="true"]')) return;
        event.preventDefault();
        setSurface("chat");
        void newSession();
        return;
      }
      if (event.key.toLowerCase() === "m" && !event.shiftKey) {
        if (document.querySelector('[aria-modal="true"]')) return;
        event.preventDefault();
        window.dispatchEvent(new CustomEvent("xiaomei:voice-control", {
          detail: { action: "toggle" },
        }));
        return;
      }
      if (event.key.toLowerCase() === "m" && event.shiftKey) {
        if (document.querySelector('[aria-modal="true"]')) return;
        event.preventDefault();
        window.dispatchEvent(new CustomEvent("xiaomei:model-context-toggle"));
        return;
      }
      if (event.key.toLowerCase() !== "b") return;
      event.preventDefault();
      if (event.shiftKey) {
        window.dispatchEvent(new CustomEvent("xiaomei:right-sidebar-toggle"));
      } else {
        setLeftSidebarCollapsed((collapsed) => !collapsed);
      }
    };
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, [newSession]);

  return (
    <div className={`main-shell${modelContextOpen ? " has-model-context" : ""}`}>
      <ConversationList
        collapsed={leftSidebarCollapsed || modelContextOpen}
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
          leftSidebarCollapsed={leftSidebarCollapsed || modelContextOpen}
          onLeftSidebarCollapsedChange={setLeftSidebarCollapsed}
        />
      )}
      {modelContextOpen && (
        <div className="model-context-dock">
          <ModelContextDialog embedded onClose={() => setModelContextOpen(false)} />
        </div>
      )}
      </div>
      <SettingsCenter />
      <UnifiedSearchDialog />
      {surface === "workspaces" && <MusicPlayer />}
      <MediaLibraryDialog />
    </div>
  );
}
