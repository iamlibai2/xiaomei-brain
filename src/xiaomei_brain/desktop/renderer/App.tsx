import { useEffect, useRef } from "react";
import { useCoreStore, initGatewayEvents } from "./store";
import { ConnectPage } from "./components/ConnectPage";
import { MenuBar } from "./components/MenuBar";
import { MainShell } from "./components/MainShell";

export function App() {
  const page = useCoreStore((s) => s.page);
  const agents = useCoreStore((s) => s.agents);
  const connectToAgent = useCoreStore((s) => s.connectToAgent);
  const setPage = useCoreStore((s) => s.setPage);

  useEffect(() => {
    initGatewayEvents();
  }, []);

  // Auto-connect saved agents on first render when agents are loaded
  const didAutoConnect = useRef(false);
  useEffect(() => {
    if (!didAutoConnect.current && agents.length > 0) {
      didAutoConnect.current = true;
      if (page === "connect") setPage("chat");
      agents.forEach((a) => connectToAgent(a.id));
    }
  }, [agents]);

  return (
    <div className="app">
      <MenuBar />
      {page === "connect" ? (
        <ConnectPage />
      ) : (
        <MainShell />
      )}
    </div>
  );
}
