import { useEffect, useState } from "react";
import { ConversationList } from "./conversation-list/ConversationList";
import { HomePage } from "./home/HomePage";
import { SettingsCenter } from "./settings/SettingsCenter";
import { UnifiedSearchDialog } from "./search/UnifiedSearchDialog";
import { registerEmbodimentCommand } from "../embodiment/command-registry";

export function MainShell() {
  const [leftSidebarCollapsed, setLeftSidebarCollapsed] = useState(false);

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

  return (
    <div className="main-shell">
      <ConversationList
        collapsed={leftSidebarCollapsed}
        onCollapsedChange={setLeftSidebarCollapsed}
      />
      <HomePage
        leftSidebarCollapsed={leftSidebarCollapsed}
        onLeftSidebarCollapsedChange={setLeftSidebarCollapsed}
      />
      <SettingsCenter />
      <UnifiedSearchDialog />
    </div>
  );
}
