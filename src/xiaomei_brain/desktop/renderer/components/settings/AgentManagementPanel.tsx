import { useState } from "react";
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
          <h2>Agent 管理</h2>
          <p>管理 Desktop 已知的本地与远程 Agent。这里选择的配置目标不会改变当前聊天。</p>
        </div>
        <div>
          <Button
            variant="ghost"
            size="sm"
            icon="refresh"
            onClick={() => { void refreshLocalAgents(); }}
          >
            刷新
          </Button>
          <Button variant="secondary" size="sm" icon="plus" onClick={() => setAddMode("local")}>
            创建本地 Agent
          </Button>
          <Button variant="primary" size="sm" icon="external-link" onClick={() => setAddMode("remote")}>
            连接远程 Agent
          </Button>
        </div>
      </header>

      {agents.length === 0 ? (
        <section className="agent-management-empty">
          <span className="agent-management-empty-icon"><Icon name="robot" size={24} /></span>
          <h3>还没有 Agent</h3>
          <p>创建一个本地 Agent 立即开始，或者连接已经运行的远程 Agent。</p>
          <div className="agent-management-empty-actions">
            <Button variant="secondary" size="md" icon="plus" onClick={() => setAddMode("local")}>
              创建本地 Agent
            </Button>
            <Button variant="primary" size="md" icon="external-link" onClick={() => setAddMode("remote")}>
              连接远程 Agent
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
            const status = agentStatus(agent, connection?.status, localOnline, lifecycle?.status);
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
                    {agent.id === activeAgentId && <span>当前对话</span>}
                    <span className={`agent-management-status ${status.tone}`}>
                      <i />{status.label}
                    </span>
                  </div>
                  <p>{agent.description || (agent.source === "local" ? "本地 AI Agent" : "远程 Agent")}</p>
                  <div className="agent-management-meta">
                    <span>{agent.source === "local" ? "本地" : "远程"}</span>
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
                    打开对话
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    icon="settings"
                    className="settings-list-action"
                    onClick={() => onConfigure(agent.id)}
                  >
                    设置
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
                        {localOnline === false ? "启动" : "停止"}
                      </Button>
                      {agent.localAgentId && (
                        <Button
                          variant="text"
                          size="sm"
                          icon="terminal"
                          className="settings-list-action"
                          onClick={() => openAgentLogs(agent.localAgentId!)}
                        >
                          查看日志
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
                          {connection?.status === "connecting" ? "连接中" : "连接"}
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        icon="trash"
                        className="settings-list-action danger"
                        onClick={() => setRemoveTarget(agent)}
                      >
                        移除
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
            <h3 id="agent-remove-title">移除远程 Agent？</h3>
            <p>
              Desktop 将忘记“{removeTarget.name}”的连接信息，不会停止或删除远端的 Agent。
            </p>
            <footer>
              <Button variant="ghost" size="md" onClick={() => setRemoveTarget(null)}>取消</Button>
              <Button
                variant="danger"
                size="md"
                onClick={() => {
                  removeAgent(removeTarget.id);
                  setRemoveTarget(null);
                }}
              >
                移除
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
): { label: string; tone: string } {
  if (lifecycle === "starting") return { label: "启动中", tone: "pending" };
  if (lifecycle === "stopping") return { label: "停止中", tone: "pending" };
  if (lifecycle === "restarting") return { label: "重启中", tone: "pending" };
  if (lifecycle === "error" || connection === "error") return { label: "异常", tone: "error" };
  if (connection === "connected") return { label: "在线", tone: "online" };
  if (connection === "connecting") return { label: "连接中", tone: "pending" };
  if (agent.source === "local" && localOnline === false) return { label: "已停止", tone: "" };
  if (agent.source === "local" && localOnline) return { label: "运行中", tone: "online" };
  return { label: "未连接", tone: "" };
}
