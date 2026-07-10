import { QuickActions } from "./QuickActions";
import { ChatInput } from "./ChatInput";
import { ContextBar } from "./ContextBar";
import { useGateway } from "../../hooks/useGateway";

interface HomeComposerProps {
  gateway: ReturnType<typeof useGateway>;
}

export function HomeComposer({ gateway }: HomeComposerProps) {
  return (
    <div className="wb-home-composer">
      <QuickActions onAction={() => {}} />
      <ChatInput gateway={gateway} />
      <ContextBar />
    </div>
  );
}
