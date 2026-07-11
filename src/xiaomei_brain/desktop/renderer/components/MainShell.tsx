import { ConversationList } from "./conversation-list/ConversationList";
import { HomePage } from "./home/HomePage";

export function MainShell() {
  return (
    <div className="main-shell">
      <ConversationList />
      <HomePage />
    </div>
  );
}
