import React, { useState } from "react";
import { useGateway } from "./hooks/useGateway";
import { ConnectPage } from "./components/ConnectPage";
import { ChatLayout } from "./components/ChatLayout";

export function App() {
  const gateway = useGateway();
  const [page, setPage] = useState<"connect" | "chat">("connect");

  const handleConnected = () => setPage("chat");

  return (
    <div className="app">
      {page === "connect" ? (
        <ConnectPage gateway={gateway} onConnected={handleConnected} />
      ) : (
        <ChatLayout gateway={gateway} />
      )}
    </div>
  );
}
