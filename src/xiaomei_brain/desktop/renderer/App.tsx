import { useEffect, useRef, useState } from "react";
import { useCoreStore, initGatewayEvents } from "./store";
import { MenuBar } from "./components/MenuBar";
import { MainShell } from "./components/MainShell";
import { DesktopInfoProvider } from "./desktop-info";
import { IdentityPage } from "./components/IdentityPage";
import type { IdentityStatus } from "./types";
import i18n from "./i18n";

export function App() {
  const agents = useCoreStore((s) => s.agents);
  const connectToAgent = useCoreStore((s) => s.connectToAgent);
  const refreshLocalAgents = useCoreStore((s) => s.refreshLocalAgents);
  const localDiscoveryComplete = useCoreStore((s) => s.localDiscoveryComplete);
  const localAvailabilityByAgent = useCoreStore((s) => s.localAvailabilityByAgent);
  const [identityStatus, setIdentityStatus] = useState<IdentityStatus | null>(null);
  const didAutoConnect = useRef(false);

  useEffect(() => {
    initGatewayEvents();
    void window.identity.status().then(setIdentityStatus);
    void window.desktop.getSettings().then((settings) => {
      void i18n.changeLanguage(settings.language);
    });
  }, []);

  useEffect(() => {
    if (identityStatus?.unlocked) void refreshLocalAgents();
    else didAutoConnect.current = false;
  }, [identityStatus?.unlocked]);

  useEffect(() => {
    const handleIdentityChange = (event: Event) => {
      didAutoConnect.current = false;
      setIdentityStatus((event as CustomEvent<IdentityStatus>).detail);
    };
    window.addEventListener("xiaomei:identity-locked", handleIdentityChange);
    window.addEventListener("xiaomei:identity-status-changed", handleIdentityChange);
    return () => {
      window.removeEventListener("xiaomei:identity-locked", handleIdentityChange);
      window.removeEventListener("xiaomei:identity-status-changed", handleIdentityChange);
    };
  }, []);

  // Discovery is the first-use boundary. Once it completes, the main shell can
  // guide both an empty installation and an existing set of Agents.
  useEffect(() => {
    if (identityStatus?.unlocked && localDiscoveryComplete && !didAutoConnect.current && agents.length > 0) {
      didAutoConnect.current = true;
      agents.forEach((agent) => {
        if (agent.source !== "local" || localAvailabilityByAgent[agent.id]) {
          void connectToAgent(agent.id);
        }
      });
    }
  }, [agents, localDiscoveryComplete, identityStatus?.unlocked]);

  return (
    <DesktopInfoProvider>
      <div className="app">
        <MenuBar />
        {!identityStatus ? null : !identityStatus.unlocked ? (
          <IdentityPage status={identityStatus} onReady={setIdentityStatus} />
        ) : !localDiscoveryComplete ? (
          <div className="desktop-startup-check" role="status">
            <span />
            <p>正在检查本机 Agent…</p>
          </div>
        ) : (
          <MainShell />
        )}
      </div>
    </DesktopInfoProvider>
  );
}
