import { useState } from "react";
import { useTranslation } from "react-i18next";
import { createPortal } from "react-dom";
import type { AgentEntry } from "../../types";
import { useCoreStore } from "../../store";
import { AddAgentDialog } from "../conversation-list/AddAgentDialog";
import { Button, Icon } from "../ui";

interface Props {
  onConfigure: (agentId: string) => void;
  onOpenConversation: () => void;
}

export function AgentManagementPanel({ onConfigure, onOpenConversation }: Props) {
  const { t } = useTranslation();
  const agents = useCoreStore((state) => state.agents);
  const activeAgentId = useCoreStore((state) => state.activeAgentId);
  const connectionByAgent = useCoreStore((state) => state.connectionByAgent);
  const localAvailabilityByAgent = useCoreStore((state) => state.localAvailabilityByAgent);
  const localInfoByAgent = useCoreStore((state) => state.localInfoByAgent);
  const lifecycleByAgent = useCoreStore((state) => state.lifecycleByAgent);
  const connectToAgent = useCoreStore((state) => state.connectToAgent);
  const switchAgent = useCoreStore((state) => state.switchAgent);
  const controlLocalAgent = useCoreStore((state) => state.controlLocalAgent);
  const refreshLocalAgents = useCoreStore((state) => state.refreshLocalAgents);
  const openAgentLogs = useCoreStore((state) => state.openAgentLogs);
  const removeAgent = useCoreStore((state) => state.removeAgent);
  const [addMode, setAddMode] = useState<"local" | "remote" | null>(null);
  const [removeTarget, setRemoveTarget] = useState<AgentEntry | null>(null);

  async function openConversation(agentId: string) {
    await switchAgent(agentId);
    onOpenConversation();
  }

  return (
    <div className="agent-management-page">
      <header className="settings-page-heading agent-management-heading">
        <div>
          <h2>{t("agentMgmt.title")}</h2>
          <p>{t("agentMgmt.description")}</p>
        </div>
        <div>
          <Button
            variant="ghost"
            size="sm"
            icon="refresh"
            onClick={() => { void refreshLocalAgents(); }}
          >
            {t("agentMgmt.refresh")}
          </Button>
          <Button variant="secondary" size="sm" icon="plus" onClick={() => setAddMode("local")}>
            {t("agentMgmt.createLocal")}
          </Button>
          <Button variant="primary" size="sm" icon="external-link" onClick={() => setAddMode("remote")}>
            {t("agentMgmt.connectRemote")}
          </Button>
        </div>
      </header>

      {agents.length === 0 ? (
        <section className="agent-management-empty">
          <span className="agent-management-empty-icon"><Icon name="robot" size={24} /></span>
          <h3>{t("agentMgmt.emptyTitle")}</h3>
          <p>{t("agentMgmt.emptyDescription")}</p>
          <div className="agent-management-empty-actions">
            <Button variant="secondary" size="md" icon="plus" onClick={() => setAddMode("local")}>
              {t("agentMgmt.createLocal")}
            </Button>
            <Button variant="primary" size="md" icon="external-link" onClick={() => setAddMode("remote")}>
              {t("agentMgmt.connectRemote")}
            </Button>
          </div>
        </section>
      ) : (
        <div className="agent-management-list">
          {agents.map((agent) => {
            const connection = connectionByAgent[agent.id];
            const localOnline = agent.source === "local"
              ? localAvailabilityByAgent[agent.id]
              : undefined;
            const lifecycle = lifecycleByAgent[agent.id];
            const status = agentStatus(agent, connection?.status, localOnline, lifecycle?.status, t);
            const lifecycleBusy = lifecycle?.status === "starting"
              || lifecycle?.status === "stopping"
              || lifecycle?.status === "restarting";
            const canOpenConversation = agent.source !== "local" || localOnline !== false;

            return (
              <article className="agent-management-card" key={agent.id}>
                <span className="agent-management-avatar">{agent.name.charAt(0) || "A"}</span>
                <div className="agent-management-copy">
                  <div className="agent-management-name">
                    <h3>{agent.name}</h3>
                    {agent.id === activeAgentId && <span>{t("agentMgmt.currentConversation")}</span>}
                    <span className={`agent-management-status ${status.tone}`}>
                      <i />{status.label}
                    </span>
                  </div>
                  <p>{agent.description || (agent.source === "local" ? t("agentMgmt.localAgent") : t("agentMgmt.remoteAgent"))}</p>
                  <div className="agent-management-meta">
                    <span>{agent.source === "local" ? t("settings.local") : t("settings.remote")}</span>
                    <span>{agent.host}:{agent.port}</span>
                    {localInfoByAgent[agent.id]?.pid && (
                      <span>PID {localInfoByAgent[agent.id].pid}</span>
                    )}
                  </div>
                  {lifecycle?.error && <small className="agent-management-error">{lifecycle.error}</small>}
                  {connection?.status === "error" && connection.error && (
                    <small className="agent-management-error">{connection.error}</small>
                  )}
                </div>
                <div className="agent-management-actions">
                  <Button
                    variant="ghost"
                    size="sm"
                    icon="external-link"
                    className="settings-list-action primary"
                    disabled={!canOpenConversation}
                    onClick={() => { void openConversation(agent.id); }}
                  >
                    {t("agentMgmt.openConversation")}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    icon="settings"
                    className="settings-list-action"
                    onClick={() => onConfigure(agent.id)}
                  >
                    {t("agentMgmt.configure")}
                  </Button>
                  {agent.source === "local" ? (
                    <>
                      <Button
                        variant="ghost"
                        size="sm"
                        icon={localOnline === false ? "play" : "power"}
                        className="settings-list-action"
                        disabled={lifecycleBusy}
                        onClick={() => {
                          void controlLocalAgent(agent.id, localOnline === false ? "start" : "stop");
                        }}
                      >
                        {localOnline === false ? t("agentMgmt.start") : t("agentMgmt.stop")}
                      </Button>
                      {agent.localAgentId && (
                        <Button
                          variant="text"
                          size="sm"
                          icon="terminal"
                          className="settings-list-action"
                          onClick={() => openAgentLogs(agent.localAgentId!)}
                        >
                          {t("agentMgmt.viewLogs")}
                        </Button>
                      )}
                    </>
                  ) : (
                    <>
                      {connection?.status !== "connected" && (
                        <Button
                          variant="ghost"
                          size="sm"
                          icon="external-link"
                          className="settings-list-action"
                          disabled={connection?.status === "connecting"}
                          onClick={() => { void connectToAgent(agent.id); }}
                        >
                          {connection?.status === "connecting" ? t("agentMgmt.connecting") : t("agentMgmt.connect")}
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        icon="trash"
                        className="settings-list-action danger"
                        onClick={() => setRemoveTarget(agent)}
                      >
                        {t("agentMgmt.remove")}
                      </Button>
                    </>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}

      {addMode && (
        <AddAgentDialog
          activateCreated={false}
          initialMode={addMode}
          allowModeSwitch={false}
          onClose={() => setAddMode(null)}
        />
      )}
      {removeTarget && createPortal(
        <div
          className="agent-remove-overlay"
          onMouseDown={(event) => {
            event.stopPropagation();
            setRemoveTarget(null);
          }}
        >
          <section
            className="agent-remove-dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="agent-remove-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <h3 id="agent-remove-title">{t("agentMgmt.removeTitle")}</h3>
            <p>
              {t("agentMgmt.removeDescription", { name: removeTarget.name })}
            </p>
            <footer>
              <Button variant="ghost" size="md" onClick={() => setRemoveTarget(null)}>{t("common.cancel")}</Button>
              <Button
                variant="danger"
                size="md"
                onClick={() => {
                  removeAgent(removeTarget.id);
                  setRemoveTarget(null);
                }}
              >
                {t("agentMgmt.remove")}
              </Button>
            </footer>
          </section>
        </div>,
        document.body,
      )}
    </div>
  );
}

function agentStatus(
  agent: AgentEntry,
  connection?: "disconnected" | "connecting" | "connected" | "error",
  localOnline?: boolean,
  lifecycle?: "idle" | "starting" | "stopping" | "restarting" | "error",
  t: (key: string) => string = (key) => key,
): { label: string; tone: string } {
  if (lifecycle === "starting") return { label: t("agentMgmt.starting"), tone: "pending" };
  if (lifecycle === "stopping") return { label: t("agentMgmt.stopping"), tone: "pending" };
  if (lifecycle === "restarting") return { label: t("agentMgmt.restarting"), tone: "pending" };
  if (lifecycle === "error" || connection === "error") return { label: t("agentMgmt.error"), tone: "error" };
  if (connection === "connected") return { label: t("agentMgmt.online"), tone: "online" };
  if (connection === "connecting") return { label: t("agentMgmt.connecting"), tone: "pending" };
  if (agent.source === "local" && localOnline === false) return { label: t("agentMgmt.stopped"), tone: "" };
  if (agent.source === "local" && localOnline) return { label: t("agentMgmt.running"), tone: "online" };
  return { label: t("agentMgmt.disconnected"), tone: "" };
}
