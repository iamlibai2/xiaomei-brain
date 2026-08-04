import { useCallback, useEffect, useMemo, useState } from "react";
import type { LocalAIServiceStatus, ModelConfigSnapshot } from "../../types";
import { useCoreStore } from "../../store";
import { Button, Icon, type IconName } from "../ui";
import {
  LOCAL_AI_STATUS_CHANGED_EVENT,
  openSettingsCenter,
} from "../settings/events";

type ModelState = "waiting" | "checking" | "ready" | "missing" | "error";

interface ReadinessItem {
  id: string;
  title: string;
  detail: string;
  actionLabel: string;
  icon: IconName;
  action: () => void;
  busy?: boolean;
}

function hasConfiguredPrimary(snapshot: ModelConfigSnapshot): boolean {
  const value = snapshot.selection.primary || snapshot.active.primary || "";
  const [providerId, modelId] = value.split("/", 2);
  if (!providerId || !modelId) return false;
  return Boolean(snapshot.providers
    .find((provider) => provider.id === providerId)
    ?.models.some((model) => model.id === modelId));
}

export function FirstRunReadinessCard({
  compact = false,
  onReadyChange,
}: {
  compact?: boolean;
  onReadyChange?: (ready: boolean) => void;
}) {
  const agents = useCoreStore((state) => state.agents);
  const activeAgentId = useCoreStore((state) => state.activeAgentId);
  const connection = useCoreStore((state) => (
    activeAgentId ? state.connectionByAgent[activeAgentId] : undefined
  ));
  const localOnline = useCoreStore((state) => (
    activeAgentId ? state.localAvailabilityByAgent[activeAgentId] : undefined
  ));
  const lifecycle = useCoreStore((state) => (
    activeAgentId ? state.lifecycleByAgent[activeAgentId] : undefined
  ));
  const connectToAgent = useCoreStore((state) => state.connectToAgent);
  const controlLocalAgent = useCoreStore((state) => state.controlLocalAgent);
  const activeAgent = agents.find((agent) => agent.id === activeAgentId) || agents[0];
  const [services, setServices] = useState<LocalAIServiceStatus[]>([]);
  const [servicesChecking, setServicesChecking] = useState(true);
  const [servicesError, setServicesError] = useState("");
  const [modelState, setModelState] = useState<ModelState>("waiting");
  const [modelError, setModelError] = useState("");

  const loadLocalAI = useCallback(async () => {
    setServicesChecking(true);
    try {
      const cached = await window.localAI.cachedList();
      if (cached.ok && cached.services.length > 0) {
        setServices(cached.services);
        setServicesChecking(false);
      }
      const current = await window.localAI.list();
      if (current.ok) {
        setServices(current.services);
        setServicesError("");
      } else {
        setServicesError(current.error || "无法检查本机 AI 服务。");
      }
    } catch (error) {
      setServices([]);
      setServicesError(String(error instanceof Error ? error.message : error));
    } finally {
      setServicesChecking(false);
    }
  }, []);

  useEffect(() => {
    void loadLocalAI();
    const handleStatus = (event: Event) => {
      const detail = (event as CustomEvent<{ services?: LocalAIServiceStatus[] }>).detail;
      if (detail?.services) {
        setServices(detail.services);
        setServicesChecking(false);
        setServicesError("");
      }
    };
    window.addEventListener(LOCAL_AI_STATUS_CHANGED_EVENT, handleStatus);
    return () => window.removeEventListener(LOCAL_AI_STATUS_CHANGED_EVENT, handleStatus);
  }, [loadLocalAI]);

  useEffect(() => {
    if (!activeAgent || connection?.status !== "connected") {
      setModelState("waiting");
      setModelError("");
      return;
    }
    let cancelled = false;
    setModelState("checking");
    void window.gateway.getModelConfig({ agentId: activeAgent.id }).then((response) => {
      if (cancelled) return;
      if (response.error) {
        setModelState("error");
        setModelError(response.error.message);
        return;
      }
      if (!response.result) {
        setModelState("missing");
        return;
      }
      const snapshot = response.result as unknown as ModelConfigSnapshot;
      setModelState(hasConfiguredPrimary(snapshot) ? "ready" : "missing");
      setModelError("");
    });
    return () => { cancelled = true; };
  }, [activeAgent?.id, connection?.status]);

  useEffect(() => {
    const refreshModel = () => {
      if (!activeAgent || connection?.status !== "connected") return;
      setModelState("checking");
      void window.gateway.getModelConfig({ agentId: activeAgent.id }).then((response) => {
        if (response.error) {
          setModelState("error");
          setModelError(response.error.message);
          return;
        }
        if (!response.result) {
          setModelState("missing");
          return;
        }
        setModelState(hasConfiguredPrimary(response.result as unknown as ModelConfigSnapshot) ? "ready" : "missing");
      });
    };
    window.addEventListener("xiaomei:model-selection-changed", refreshModel);
    return () => window.removeEventListener("xiaomei:model-selection-changed", refreshModel);
  }, [activeAgent?.id, connection?.status]);

  const embedding = services.find((service) => service.id === "embedding");
  const localEmbeddingReady = activeAgent?.source !== "local"
    || Boolean(embedding?.model_present && embedding.state === "online");
  const agentConnected = connection?.status === "connected";
  const agentBusy = connection?.status === "connecting"
    || lifecycle?.status === "starting"
    || lifecycle?.status === "restarting";

  const missingItems = useMemo<ReadinessItem[]>(() => {
    const items: ReadinessItem[] = [];
    if (!activeAgent) {
      items.push({
        id: "agent-create",
        title: "创建或连接一个 Agent",
        detail: "创建本地 Agent 后即可开始，也可以连接已有的远程 Agent。",
        actionLabel: "添加 Agent",
        icon: "robot",
        action: () => openSettingsCenter("agents"),
      });
      return items;
    }

    // An empty service list while the background check is still running means
    // "unknown", not "missing".  Rendering the first-run card at that point
    // makes an already configured Desktop flash the onboarding UI on startup.
    if (activeAgent.source === "local" && !servicesChecking && !localEmbeddingReady) {
      const downloading = embedding?.state === "downloading";
      items.push({
        id: "embedding",
        title: "准备向量服务",
        detail: servicesChecking
          ? "正在检查本机向量模型与服务…"
          : servicesError
            ? servicesError
            : !embedding?.model_present
              ? "需要先下载向量模型，记忆检索依赖它。"
              : embedding?.state === "starting"
                ? "向量服务正在启动。"
                : embedding?.error || "向量模型已就绪，还需要启动服务。",
        actionLabel: downloading ? "查看下载进度" : "配置本机 AI 服务",
        icon: "cpu",
        action: () => openSettingsCenter("local-ai"),
        busy: servicesChecking || embedding?.state === "starting",
      });
    }

    const agentIssueConfirmed = activeAgent.source === "local" && localOnline === false
      || connection?.status === "error";
    if (!agentConnected && agentIssueConfirmed) {
      const isLocalStopped = activeAgent.source === "local" && localOnline === false;
      const waitingForEmbedding = activeAgent.source === "local" && !localEmbeddingReady;
      items.push({
        id: "agent-online",
        title: isLocalStopped ? `启动 ${activeAgent.name}` : `连接 ${activeAgent.name}`,
        detail: lifecycle?.status === "error"
          ? lifecycle.error || "Agent 启动失败，请检查日志。"
          : connection?.status === "error"
            ? connection.error || "Agent 连接失败。"
            : isLocalStopped
              ? "Agent 已创建，启动后 Desktop 会自动连接。"
              : "需要建立连接才能读取会话和模型配置。",
        actionLabel: waitingForEmbedding
          ? "先完成向量服务"
          : agentBusy
            ? "正在准备…"
            : isLocalStopped
              ? "启动 Agent"
              : "重新连接",
        icon: "play",
        busy: agentBusy || waitingForEmbedding,
        action: () => {
          if (isLocalStopped) void controlLocalAgent(activeAgent.id, "start");
          else void connectToAgent(activeAgent.id);
        },
      });
    }

    // Reading the model configuration is also a background health check.  Do
    // not present it as unfinished onboarding until it has actually failed or
    // confirmed that the primary model is missing.
    if (agentConnected && (modelState === "missing" || modelState === "error")) {
      items.push({
        id: "model",
        title: "配置主模型",
        detail: modelState === "error"
          ? modelError || "暂时无法读取模型配置。"
          : "添加可用模型并将它设为主模型。",
        actionLabel: "配置模型",
        icon: "sparkles",
        action: () => openSettingsCenter("models", activeAgent.id),
      });
    }
    return items;
  }, [
    activeAgent,
    agentBusy,
    agentConnected,
    connectToAgent,
    connection?.error,
    connection?.status,
    controlLocalAgent,
    embedding,
    lifecycle?.error,
    lifecycle?.status,
    localEmbeddingReady,
    localOnline,
    modelError,
    modelState,
    servicesChecking,
    servicesError,
  ]);

  useEffect(() => {
    onReadyChange?.(missingItems.length === 0);
  }, [missingItems.length, onReadyChange]);

  if (missingItems.length === 0) return null;

  return (
    <section className={`first-run-card ${compact ? "is-compact" : ""}`} aria-label="完成初始准备">
      <header>
        <div className="first-run-card-icon"><Icon name="sparkles" size={20} /></div>
        <div>
          <h2>完成初始准备</h2>
          <p>还差 {missingItems.length} 项，完成后就可以开始对话。</p>
        </div>
        <Button variant="ghost" size="icon-sm" icon="refresh" title="重新检查" onClick={() => void loadLocalAI()} />
      </header>
      <div className="first-run-items">
        {missingItems.map((item) => (
          <div className="first-run-item" key={item.id}>
            <span className="first-run-item-icon"><Icon name={item.icon} size={17} /></span>
            <div className="first-run-item-copy">
              <strong>{item.title}</strong>
              <span>{item.detail}</span>
            </div>
            <Button
              variant={item.id === "agent-online" ? "primary" : "secondary"}
              size="sm"
              disabled={item.busy}
              onClick={item.action}
            >
              {item.actionLabel}
            </Button>
          </div>
        ))}
      </div>
    </section>
  );
}
