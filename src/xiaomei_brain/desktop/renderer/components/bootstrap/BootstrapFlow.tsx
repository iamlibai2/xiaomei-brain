import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { BootstrapStatus } from "../../types";
import { useCoreStore } from "../../store";
import { FirstRunSetup } from "../FirstRunSetup";
import { Button, Icon } from "../ui";
import { BootstrapWelcome } from "./BootstrapWelcome";
import { QuickPreparation } from "./QuickPreparation";
import { OptionalServicesSetup } from "./OptionalServicesSetup";
import { BootstrapWizard } from "./BootstrapWizard";
import { BootstrapModelSetup } from "./BootstrapModelSetup";
import { IdentityPage } from "../IdentityPage";
import { BootstrapAgentSetup } from "./BootstrapAgentSetup";

export function BootstrapFlow({ status, onRefresh, onComplete }: {
  status: BootstrapStatus;
  onRefresh: () => Promise<void>;
  onComplete: (status: BootstrapStatus) => void;
}) {
  const { t } = useTranslation();
  const agents = useCoreStore((state) => state.agents);
  const refreshLocalAgents = useCoreStore((state) => state.refreshLocalAgents);
  const controlLocalAgent = useCoreStore((state) => state.controlLocalAgent);
  const connectToAgent = useCoreStore((state) => state.connectToAgent);
  const switchAgent = useCoreStore((state) => state.switchAgent);
  const connectionByAgent = useCoreStore((state) => state.connectionByAgent);
  const lifecycleByAgent = useCoreStore((state) => state.lifecycleByAgent);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const preparedAgentRef = useRef("");

  const initialAgent = agents.find((agent) => agent.localAgentId === status.initialAgentId);
  const connectionStatus = initialAgent ? connectionByAgent[initialAgent.id]?.status : "disconnected";
  const connectionError = initialAgent
    ? lifecycleByAgent[initialAgent.id]?.error || connectionByAgent[initialAgent.id]?.error || ""
    : "";

  const run = useCallback(async (operation: () => Promise<{ ok: boolean; error?: string; status?: BootstrapStatus }>) => {
    setWorking(true);
    setError("");
    try {
      const result = await operation();
      if (!result.ok) throw new Error(result.error || t("bootstrap.operationFailed"));
      if (result.status?.phase === "ready") onComplete(result.status);
      else await onRefresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setWorking(false);
    }
  }, [onComplete, onRefresh, t]);

  const prepareModelAgent = useCallback(async () => {
      if (status.step !== "model" || status.preview) return;
      await refreshLocalAgents();
      const entry = useCoreStore.getState().agents
        .find((agent) => agent.localAgentId === status.initialAgentId);
      if (!entry || preparedAgentRef.current === entry.id) return;
      preparedAgentRef.current = entry.id;
      await switchAgent(entry.id);
      const current = useCoreStore.getState();
      if (!current.localAvailabilityByAgent[entry.id]) {
        await controlLocalAgent(entry.id, "start");
      } else if (current.connectionByAgent[entry.id]?.status !== "connected") {
        await connectToAgent(entry.id);
      }
  }, [connectToAgent, controlLocalAgent, refreshLocalAgents, status.initialAgentId, status.preview, status.step, switchAgent]);

  useEffect(() => {
    if (status.step !== "model" || status.preview) return;
    let cancelled = false;
    void prepareModelAgent().catch((reason) => {
      preparedAgentRef.current = "";
      if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
    });
    return () => { cancelled = true; };
  }, [prepareModelAgent, status.preview, status.step]);

  if (status.step === "welcome") {
    return <BootstrapWelcome onSelect={async (mode) => {
      const response = await window.bootstrap.selectMode({ mode });
      if (!response.ok) throw new Error(response.error || t("bootstrap.operationFailed"));
      if (response.status) onComplete(response.status);
      else await onRefresh();
    }} />;
  }

  if (status.setupMode === "quick" && ["runtime", "inference", "embedding"].includes(status.step)) {
    return <QuickPreparation onComplete={onRefresh} />;
  }

  if (status.setupMode === "quick" && status.step === "agent") {
    return <QuickPreparation task="agent" onComplete={onRefresh} />;
  }

  if (status.setupMode === "custom" && status.step === "agent") {
    return <BootstrapAgentSetup preview={status.preview} onComplete={onRefresh} />;
  }

  if (!status.preview && status.setupMode === "quick" && status.step === "identity") {
    return <IdentityPage status={status.identity} bootstrapMode="quick" onReady={() => { void onRefresh(); }} />;
  }

  if (status.step === "optional_services") {
    return <OptionalServicesSetup initial={status.optionalServices} preview={status.preview} onComplete={async (services) => {
      const response = await window.bootstrap.completeOptionalServices({ services });
      if (!response.ok) throw new Error(response.error || t("bootstrap.operationFailed"));
      if (response.status) onComplete(response.status);
      else await onRefresh();
    }} />;
  }

  if (status.preview && status.step === "identity") {
    return (
      <BootstrapWizard
        mode={status.setupMode}
        current="identity"
        preview
        title={t("bootstrap.previewIdentityTitle")}
        description={t("bootstrap.previewIdentityDescription")}
        actions={(
          <Button variant="primary" size="lg" className="bootstrap-primary-action" onClick={() => void run(() => window.bootstrap.advancePreview())}>
            {t("bootstrap.previewContinue")}
          </Button>
        )}
      >
        <div className="bootstrap-identity-form">
          <label><span>{t("bootstrap.previewName")}</span><input value={t("bootstrap.previewNameValue")} readOnly /></label>
          <label><span>{t("bootstrap.previewPassword")}</span><input value="••••••••" type="password" readOnly /></label>
          <label><span>{t("identity.confirmPassword")}</span><input value="••••••••" type="password" readOnly /></label>
        </div>
      </BootstrapWizard>
    );
  }

  if (status.preview && status.step === "complete") {
    return (
      <BootstrapWizard
        mode={status.setupMode}
        current="complete"
        preview
        title={t("bootstrap.previewCompleteTitle")}
        description={t("bootstrap.previewCompleteDescription")}
      >
        <div className="bootstrap-complete-mark"><Icon name="check" size={22} /></div>
      </BootstrapWizard>
    );
  }

  if (status.step === "inference" || status.step === "embedding") {
    return <FirstRunSetup initial={status.setup} embedding={status.embedding} stage={status.step} mode={status.setupMode} onComplete={onRefresh} preview={status.preview} />;
  }

  if (status.step === "model") {
    return (
      <BootstrapModelSetup
        mode={status.setupMode}
        agentId={initialAgent?.id || status.initialAgentId}
        initialAgentId={status.initialAgentId}
        connected={Boolean(status.preview || (initialAgent && connectionStatus === "connected"))}
        connectionError={connectionError}
        preview={status.preview}
        onRetryConnection={() => {
          preparedAgentRef.current = "";
          setError("");
          void prepareModelAgent();
        }}
        onComplete={onComplete}
      />
    );
  }

  const pageTitle = status.step === "runtime"
    ? (status.phase === "repair_required" ? t("bootstrap.repairTitle") : t("bootstrap.runtimeTitle"))
    : t("bootstrap.modelTitle");
  const pageDescription = status.step === "runtime"
    ? (status.phase === "repair_required" ? t("bootstrap.repairDescription") : t("bootstrap.runtimeDescription"))
    : t("bootstrap.modelDescription");

  const actions = status.step === "runtime" ? (
    <Button variant="primary" size="lg" className="bootstrap-primary-action" disabled={working} onClick={() => void run(() => window.bootstrap.prepareRuntime())}>
      {working ? t("bootstrap.preparing") : t("bootstrap.prepareRuntime")}
    </Button>
  ) : undefined;

  return (
    <BootstrapWizard
      mode={status.setupMode}
      current={status.step}
      title={pageTitle}
      description={pageDescription}
      preview={status.preview}
      actions={actions}
    >
        {status.step === "runtime" && status.runtime.error && (
          <div className="bootstrap-error"><p>{status.runtime.error}</p></div>
        )}
        {status.step === "runtime" && working && (
          <div className="setup-progress">
            <div><span className="is-indeterminate" /></div>
            <p>{t("bootstrap.installingRuntime")}</p>
          </div>
        )}

        {error && (
          <div className="bootstrap-error">
            <strong>{t("bootstrap.operationFailed")}</strong>
            <p>{error}</p>
            <div className="bootstrap-error-actions">
              <Button variant="secondary" size="sm" onClick={() => void onRefresh()}>{t("common.retry")}</Button>
              <Button variant="ghost" size="sm" onClick={() => void window.desktop.openLogDirectory()}>
                {t("bootstrap.openLogs")}
              </Button>
            </div>
          </div>
        )}
    </BootstrapWizard>
  );
}
