import { ConversationList } from "./conversation-list/ConversationList";
import { HomePage } from "./home/HomePage";
import { SettingsCenter } from "./settings/SettingsCenter";

export function MainShell() {
  return (
    <div className="main-shell">
      <ConversationList />
      <HomePage />
      <SettingsCenter />
    </div>
  );
}
