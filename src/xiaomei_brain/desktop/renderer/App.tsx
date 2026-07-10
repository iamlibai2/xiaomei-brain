import { useState } from "react";
import { useGateway } from "./hooks/useGateway";
import { ConnectPage } from "./components/ConnectPage";
import { MenuBar } from "./components/MenuBar";
import { MainShell } from "./components/MainShell";

export function App() {
  const gateway = useGateway();
  const [page, setPage] = useState<"connect" | "chat">("connect");

  const handleConnected = () => setPage("chat");

  return (
    <div className="app">
      <MenuBar />
      {page === "connect" ? (
        <ConnectPage gateway={gateway} onConnected={handleConnected} />
      ) : (
        <MainShell gateway={gateway} />
      )}
    </div>
  );
}
