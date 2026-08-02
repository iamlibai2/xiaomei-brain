import { useState } from "react";
import { ConversationList } from "./conversation-list/ConversationList";
import { HomePage } from "./home/HomePage";
import { SettingsCenter } from "./settings/SettingsCenter";
import { UnifiedSearchDialog } from "./search/UnifiedSearchDialog";

export function MainShell() {
  const [leftSidebarCollapsed, setLeftSidebarCollapsed] = useState(false);

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
