import { ConversationList } from "./conversation-list/ConversationList";
import { HomePage } from "./home/HomePage";
import { SettingsCenter } from "./settings/SettingsCenter";
import { UnifiedSearchDialog } from "./search/UnifiedSearchDialog";

export function MainShell() {
  return (
    <div className="main-shell">
      <ConversationList />
      <HomePage />
      <SettingsCenter />
      <UnifiedSearchDialog />
    </div>
  );
}
