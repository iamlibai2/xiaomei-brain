import { useEffect, useState } from "react";
import { ConversationList } from "./conversation-list/ConversationList";
import { HomePage } from "./home/HomePage";
import { SettingsCenter } from "./settings/SettingsCenter";
import { UnifiedSearchDialog } from "./search/UnifiedSearchDialog";
import { registerEmbodimentCommand } from "../embodiment/command-registry";
import { WorkspacesPage } from "./workspaces/WorkspacesPage";
import { useCoreStore } from "../store";

export function MainShell() {
  const [leftSidebarCollapsed, setLeftSidebarCollapsed] = useState(false);
  const [surface, setSurface] = useState<"chat" | "workspaces">("chat");
  const [requestedWorkspaceId, setRequestedWorkspaceId] = useState("");
  const activeAgentId = useCoreStore((state) => state.activeAgentId || "");

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

  useEffect(() => window.gateway.onEvent((event: { event?: string; agentId?: string; data?: unknown }) => {
    if (
      event.agentId !== activeAgentId
      || !["workspace.created", "workspace.updated"].includes(event.event || "")
    ) return;
    const data = event.data && typeof event.data === "object" ? event.data as Record<string, unknown> : {};
    setRequestedWorkspaceId(String(data.id || ""));
    setSurface("workspaces");
  }), [activeAgentId]);

  return (
    <div className="main-shell">
      <ConversationList
        collapsed={leftSidebarCollapsed}
        onCollapsedChange={setLeftSidebarCollapsed}
        surface={surface}
        onOpenChat={() => setSurface("chat")}
        onOpenWorkspaces={() => setSurface("workspaces")}
      />
      {surface === "workspaces" ? (
        <WorkspacesPage
          preferredWorkspaceId={requestedWorkspaceId}
          onBackToChat={() => setSurface("chat")}
        />
      ) : (
        <HomePage
          leftSidebarCollapsed={leftSidebarCollapsed}
          onLeftSidebarCollapsedChange={setLeftSidebarCollapsed}
        />
      )}
      <SettingsCenter />
      <UnifiedSearchDialog />
    </div>
  );
}
