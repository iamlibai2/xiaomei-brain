import { useEffect, useRef, useState } from "react";
import { useCoreStore, initGatewayEvents } from "./store";
import { ConnectPage } from "./components/ConnectPage";
import { MenuBar } from "./components/MenuBar";
import { MainShell } from "./components/MainShell";
import { DesktopInfoProvider } from "./desktop-info";
import { IdentityPage } from "./components/IdentityPage";
import type { IdentityStatus } from "./types";
import i18n from "./i18n";
import { setMessageSoundEnabled } from "./message-sound";

export function App() {
  const page = useCoreStore((s) => s.page);
  const agents = useCoreStore((s) => s.agents);
  const activeAgentId = useCoreStore((s) => s.activeAgentId);
  const connectToAgent = useCoreStore((s) => s.connectToAgent);
  const setPage = useCoreStore((s) => s.setPage);
  const refreshLocalAgents = useCoreStore((s) => s.refreshLocalAgents);
  const localDiscoveryComplete = useCoreStore((s) => s.localDiscoveryComplete);
  const localAvailabilityByAgent = useCoreStore((s) => s.localAvailabilityByAgent);
  const [identityStatus, setIdentityStatus] = useState<IdentityStatus | null>(null);
  const [startupRestoreComplete, setStartupRestoreComplete] = useState(false);
  const startupRestoreAgentRef = useRef<string | null>(null);

  useEffect(() => {
    const disposeGatewayEvents = initGatewayEvents();
    void window.identity.status().then(setIdentityStatus);
    const applySettings = (settings: import("./types").DesktopSettings) => {
      void i18n.changeLanguage(settings.language);
      setMessageSoundEnabled(settings.messageSoundsEnabled);
      const root = document.documentElement;
      if (settings.theme === "system") root.removeAttribute("data-theme");
      else root.setAttribute("data-theme", settings.theme);
    };
    void window.desktop.getSettings().then(applySettings);
    const handleSettings = (event: Event) => {
      const settings = (event as CustomEvent<import("./types").DesktopSettings>).detail;
      if (settings) applySettings(settings);
    };
    window.addEventListener("xiaomei:desktop-settings-changed", handleSettings);
    return () => {
      window.removeEventListener("xiaomei:desktop-settings-changed", handleSettings);
      disposeGatewayEvents();
    };
  }, []);

  useEffect(() => {
    if (identityStatus?.unlocked) {
      void refreshLocalAgents();
    } else {
      startupRestoreAgentRef.current = null;
      setStartupRestoreComplete(false);
    }
  }, [identityStatus?.unlocked]);

  useEffect(() => {
    const handleIdentityChange = (event: Event) => {
      setIdentityStatus((event as CustomEvent<IdentityStatus>).detail);
    };
    window.addEventListener("xiaomei:identity-locked", handleIdentityChange);
    window.addEventListener("xiaomei:identity-status-changed", handleIdentityChange);
    return () => {
      window.removeEventListener("xiaomei:identity-locked", handleIdentityChange);
      window.removeEventListener("xiaomei:identity-status-changed", handleIdentityChange);
    };
  }, []);

  // Restore the selected Agent first. The promise resolves only after its
  // resume snapshot and session list have been loaded, which is the actual
  // boundary for rendering the saved conversation.
  useEffect(() => {
    if (!identityStatus?.unlocked || !localDiscoveryComplete || startupRestoreComplete) return;
    if (page === "connect" && agents.length > 0) setPage("chat");
    if (agents.length === 0) {
      setStartupRestoreComplete(true);
      return;
    }

    const activeAgent = agents.find((agent) => agent.id === activeAgentId) || agents[0];
    if (startupRestoreAgentRef.current === activeAgent.id) return;
    startupRestoreAgentRef.current = activeAgent.id;
    if (activeAgent.source === "local" && localAvailabilityByAgent[activeAgent.id] === false) {
      setStartupRestoreComplete(true);
      return;
    }
    void connectToAgent(activeAgent.id).finally(() => setStartupRestoreComplete(true));
  }, [
    activeAgentId,
    agents,
    connectToAgent,
    identityStatus?.unlocked,
    localAvailabilityByAgent,
    localDiscoveryComplete,
    page,
    setPage,
    startupRestoreComplete,
  ]);

  // Once the visible conversation is restored, connect the remaining Agents
  // in the background and react to later local availability changes.
  useEffect(() => {
    if (!identityStatus?.unlocked || !localDiscoveryComplete || !startupRestoreComplete) return;
    agents.forEach((agent) => {
      if (agent.source !== "local" || localAvailabilityByAgent[agent.id] === true) {
        void connectToAgent(agent.id);
      }
    });
  }, [agents, connectToAgent, identityStatus?.unlocked, localAvailabilityByAgent, localDiscoveryComplete, startupRestoreComplete]);

  return (
    <DesktopInfoProvider>
      <div className="app">
        <MenuBar />
        {!identityStatus ? null : !identityStatus.unlocked ? (
          <IdentityPage status={identityStatus} onReady={setIdentityStatus} />
        ) : !startupRestoreComplete ? null : page === "connect" ? (
          <ConnectPage />
        ) : (
          <MainShell />
        )}
      </div>
    </DesktopInfoProvider>
  );
}
