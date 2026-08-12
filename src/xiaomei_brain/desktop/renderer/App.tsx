import { useCallback, useEffect, useRef, useState } from "react";
import { useCoreStore, initGatewayEvents } from "./store";
import { ConnectPage } from "./components/ConnectPage";
import { MenuBar } from "./components/MenuBar";
import { MainShell } from "./components/MainShell";
import { DesktopInfoProvider } from "./desktop-info";
import { IdentityPage } from "./components/IdentityPage";
import { DesktopLockScreen } from "./components/DesktopLockScreen";
import { BootstrapFlow } from "./components/bootstrap/BootstrapFlow";
import { BootstrapScreen } from "./components/bootstrap/BootstrapScreen";
import type { BootstrapStatus, DesktopSettings, IdentityStatus } from "./types";
import i18n from "./i18n";
import { initializeMessageSound, setMessageSound } from "./message-sound";

export function App() {
  const page = useCoreStore((state) => state.page);
  const agents = useCoreStore((state) => state.agents);
  const activeAgentId = useCoreStore((state) => state.activeAgentId);
  const connectToAgent = useCoreStore((state) => state.connectToAgent);
  const setPage = useCoreStore((state) => state.setPage);
  const refreshLocalAgents = useCoreStore((state) => state.refreshLocalAgents);
  const localDiscoveryComplete = useCoreStore((state) => state.localDiscoveryComplete);
  const localAvailabilityByAgent = useCoreStore((state) => state.localAvailabilityByAgent);
  const [bootstrapStatus, setBootstrapStatus] = useState<BootstrapStatus | null>(null);
  const [bootstrapError, setBootstrapError] = useState("");
  const [desktopLocked, setDesktopLocked] = useState(false);
  const [startupRestoreComplete, setStartupRestoreComplete] = useState(false);
  const startupRestoreAgentRef = useRef<string | null>(null);
  const beganFirstRunRef = useRef(false);

  const refreshBootstrap = useCallback(async () => {
    setBootstrapError("");
    try {
      let response = await window.bootstrap.status();
      if (!response.ok || !response.status) {
        throw new Error(response.error || "Unable to read Desktop startup state");
      }
      if (
        response.status.phase === "first_run"
        && !response.status.startedAt
        && !beganFirstRunRef.current
      ) {
        beganFirstRunRef.current = true;
        response = await window.bootstrap.begin();
        if (!response.ok || !response.status) {
          throw new Error(response.error || "Unable to begin first-run setup");
        }
      }
      if (response.status.legacyReady) {
        const adopted = await window.bootstrap.complete({
          initialAgentId: response.status.initialAgentId,
        });
        if (adopted.ok && adopted.status) response = adopted;
      }
      if (!response.status) throw new Error("Unable to resolve Desktop startup state");
      setBootstrapStatus(response.status);
    } catch (error) {
      setBootstrapError(error instanceof Error ? error.message : String(error));
    }
  }, []);

  useEffect(() => {
    const disposeGatewayEvents = initGatewayEvents();
    const disposeMessageSound = initializeMessageSound();
    const applySettings = (settings: DesktopSettings) => {
      void i18n.changeLanguage(settings.language);
      setMessageSound(settings.messageSound);
      const root = document.documentElement;
      root.setAttribute("data-message-font", settings.messageFont || "default");
      if (settings.theme === "system") root.removeAttribute("data-theme");
      else root.setAttribute("data-theme", settings.theme);
    };
    void window.desktop.getSettings().then(applySettings);
    void refreshBootstrap();
    const handleSettings = (event: Event) => {
      const settings = (event as CustomEvent<DesktopSettings>).detail;
      if (settings) applySettings(settings);
    };
    window.addEventListener("xiaomei:desktop-settings-changed", handleSettings);
    return () => {
      window.removeEventListener("xiaomei:desktop-settings-changed", handleSettings);
      disposeMessageSound();
      disposeGatewayEvents();
    };
  }, [refreshBootstrap]);

  useEffect(() => {
    const lock = () => setDesktopLocked(true);
    const biometricUnlock = () => setDesktopLocked(false);
    window.addEventListener("xiaomei:desktop-lock-requested", lock);
    window.addEventListener("xiaomei:desktop-biometric-verified", biometricUnlock);
    return () => {
      window.removeEventListener("xiaomei:desktop-lock-requested", lock);
      window.removeEventListener("xiaomei:desktop-biometric-verified", biometricUnlock);
    };
  }, []);

  useEffect(() => {
    if (desktopLocked) document.documentElement.dataset.desktopLocked = "true";
    else delete document.documentElement.dataset.desktopLocked;
  }, [desktopLocked]);

  useEffect(() => {
    const refreshIdentity = () => { void refreshBootstrap(); };
    window.addEventListener("xiaomei:identity-locked", refreshIdentity);
    window.addEventListener("xiaomei:identity-status-changed", refreshIdentity);
    return () => {
      window.removeEventListener("xiaomei:identity-locked", refreshIdentity);
      window.removeEventListener("xiaomei:identity-status-changed", refreshIdentity);
    };
  }, [refreshBootstrap]);

  const applicationReady = bootstrapStatus?.phase === "ready";
  useEffect(() => {
    if (applicationReady) {
      void refreshLocalAgents();
    } else {
      startupRestoreAgentRef.current = null;
      setStartupRestoreComplete(false);
    }
  }, [applicationReady, refreshLocalAgents]);

  // Restore the selected Agent before rendering saved conversations. Other
  // Agents connect in the background only after this visible state is stable.
  useEffect(() => {
    if (!applicationReady || !localDiscoveryComplete || startupRestoreComplete) return;
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
    applicationReady,
    connectToAgent,
    localAvailabilityByAgent,
    localDiscoveryComplete,
    page,
    setPage,
    startupRestoreComplete,
  ]);

  useEffect(() => {
    if (!applicationReady || !localDiscoveryComplete || !startupRestoreComplete) return;
    agents.forEach((agent) => {
      if (agent.source !== "local" || localAvailabilityByAgent[agent.id] === true) {
        void connectToAgent(agent.id);
      }
    });
  }, [agents, applicationReady, connectToAgent, localAvailabilityByAgent, localDiscoveryComplete, startupRestoreComplete]);

  let content;
  if (bootstrapError) {
    content = <BootstrapScreen error={bootstrapError} onRetry={() => void refreshBootstrap()} />;
  } else if (!bootstrapStatus) {
    content = <BootstrapScreen />;
  } else if (!bootstrapStatus.preview && (
    (bootstrapStatus.step === "identity" && bootstrapStatus.setupMode !== "quick")
    || bootstrapStatus.phase === "ready_locked"
  )) {
    content = (
      <IdentityPage
        status={bootstrapStatus.identity}
        onReady={() => { void refreshBootstrap(); }}
        bootstrapMode={bootstrapStatus.step === "identity" ? bootstrapStatus.setupMode : undefined}
      />
    );
  } else if (bootstrapStatus.phase !== "ready") {
    content = (
      <BootstrapFlow
        status={bootstrapStatus}
        onRefresh={refreshBootstrap}
        onComplete={setBootstrapStatus}
      />
    );
  } else if (!startupRestoreComplete) {
    content = <BootstrapScreen />;
  } else {
    content = page === "connect" ? <ConnectPage /> : <MainShell />;
  }

  return (
    <DesktopInfoProvider>
      <div className="app">
        <MenuBar windowOnly={!applicationReady} />
        {content}
        {bootstrapStatus?.phase === "ready" && desktopLocked && (
          <DesktopLockScreen
            identity={bootstrapStatus.identity as IdentityStatus}
            onUnlock={() => setDesktopLocked(false)}
          />
        )}
      </div>
    </DesktopInfoProvider>
  );
}
