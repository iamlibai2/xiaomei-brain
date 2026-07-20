import { useEffect, useRef } from "react";
import { useCoreStore, initGatewayEvents } from "./store";
import { ConnectPage } from "./components/ConnectPage";
import { MenuBar } from "./components/MenuBar";
import { MainShell } from "./components/MainShell";
import { DesktopInfoProvider } from "./desktop-info";

export function App() {
  const page = useCoreStore((s) => s.page);
  const agents = useCoreStore((s) => s.agents);
  const connectToAgent = useCoreStore((s) => s.connectToAgent);
  const setPage = useCoreStore((s) => s.setPage);
  const refreshLocalAgents = useCoreStore((s) => s.refreshLocalAgents);
  const localDiscoveryComplete = useCoreStore((s) => s.localDiscoveryComplete);
  const localAvailabilityByAgent = useCoreStore((s) => s.localAvailabilityByAgent);

  useEffect(() => {
    initGatewayEvents();
    void refreshLocalAgents();
  }, []);

  // Auto-connect saved agents on first render when agents are loaded
  const didAutoConnect = useRef(false);
  useEffect(() => {
    if (localDiscoveryComplete && !didAutoConnect.current && agents.length > 0) {
      didAutoConnect.current = true;
      if (page === "connect") setPage("chat");
      agents.forEach((agent) => {
        if (agent.source !== "local" || localAvailabilityByAgent[agent.id]) {
          void connectToAgent(agent.id);
        }
      });
    }
  }, [agents, localDiscoveryComplete]);

  return (
    <DesktopInfoProvider>
      <div className="app">
        <MenuBar />
        {page === "connect" ? (
          <ConnectPage />
        ) : (
          <MainShell />
        )}
      </div>
    </DesktopInfoProvider>
  );
}
