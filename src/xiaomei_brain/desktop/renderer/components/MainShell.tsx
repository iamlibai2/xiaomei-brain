import { ConversationList } from "./conversation-list/ConversationList";
import { HomePage } from "./home/HomePage";
import { useGateway } from "../hooks/useGateway";

interface MainShellProps {
  gateway: ReturnType<typeof useGateway>;
}

export function MainShell({ gateway }: MainShellProps) {
  return (
    <div className="main-shell">
      <ConversationList />
      <HomePage gateway={gateway} />
    </div>
  );
}
