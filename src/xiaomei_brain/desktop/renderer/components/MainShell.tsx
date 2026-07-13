import { ConversationList } from "./conversation-list/ConversationList";
import { HomePage } from "./home/HomePage";
import { TerminalPanel } from "./terminal/TerminalPanel";
import { useCoreStore } from "../store";

export function MainShell() {
  const terminalOpen = useCoreStore((s) => s.terminalOpen);

  return (
    <div className="main-shell">
      <ConversationList />
      <HomePage />
      {terminalOpen && <TerminalPanel />}
    </div>
  );
}
