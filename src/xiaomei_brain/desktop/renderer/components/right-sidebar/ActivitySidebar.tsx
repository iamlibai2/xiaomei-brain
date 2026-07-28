import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type {
  ActivityCategory,
  ActivitySnapshot,
  ArtifactSnapshot,
  AssignmentSnapshot,
  MemoryReference,
  PersonMemoryListState,
  PersonMemorySnapshot,
} from "../../store";
import { useCoreStore } from "../../store";
import { Icon } from "../ui";
import { AssignmentPanel } from "./AssignmentPanel";

const EMPTY: ActivitySnapshot[] = [];
const EMPTY_ASSIGNMENTS: AssignmentSnapshot[] = [];
const EMPTY_ARTIFACTS: ArtifactSnapshot[] = [];
const EMPTY_MEMORIES: PersonMemorySnapshot[] = [];
const EMPTY_MEMORY_LIST: PersonMemoryListState = {
  loading: false,
  loadingMore: false,
  hasMore: false,
  nextOffset: null,
  error: "",
};
const ACTIVE = new Set(["queued", "running", "paused"]);

const categoryNames: Record<ActivityCategory, string> = {
  work: "工作",
  cognition: "认知",
  sleep: "睡眠",
  communication: "沟通",
};

const statusNames: Record<ActivitySnapshot["status"], string> = {
  queued: "等待中",
  running: "进行中",
  paused: "已暂停",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

const pauseNames: Record<string, string> = {
  realtime_message: "正在优先回复实时消息",
  waiting_approval: "等待你的批准",
  waiting_input: "等待你的回复",
  waiting_resource: "等待资源恢复",
  agent_stopping: "Agent 已停止",
  self_paused: "Agent 主动暂停",
  interrupted: "上次运行被中断",
};

export function ActivitySidebar({
  open,
  onClose,
  selectedAssignmentId,
  onSelectAssignment,
  section,
  onSectionChange,
  focusedArtifactKey,
  focusedMemories,
}: {
  open: boolean;
  onClose: () => void;
  selectedAssignmentId: string | null;
  onSelectAssignment: (assignmentId: string | null) => void;
  section: "activity" | "assignment" | "artifact" | "memory" | "context";
  onSectionChange: (section: "activity" | "assignment" | "artifact" | "memory" | "context") => void;
  focusedArtifactKey: string;
  focusedMemories: MemoryReference[];
}) {
  const agentId = useCoreStore((state) => state.activeAgentId || "");
  const activities = useCoreStore((state) => state.activitiesByAgent[state.activeAgentId || ""] || EMPTY);
  const loading = useCoreStore((state) => state.activityLoadingByAgent[state.activeAgentId || ""] || false);
  const error = useCoreStore((state) => state.activityErrorByAgent[state.activeAgentId || ""] || "");
  const refresh = useCoreStore((state) => state.refreshActivities);
  const assignments = useCoreStore((state) => state.assignmentsByAgent[state.activeAgentId || ""] || EMPTY_ASSIGNMENTS);
  const refreshAssignments = useCoreStore((state) => state.refreshAssignments);
  const artifacts = useCoreStore((state) => state.artifactsByAgent[state.activeAgentId || ""] || EMPTY_ARTIFACTS);
  const artifactLoading = useCoreStore((state) => state.artifactLoadingByAgent[state.activeAgentId || ""] || false);
  const artifactError = useCoreStore((state) => state.artifactErrorByAgent[state.activeAgentId || ""] || "");
  const refreshArtifacts = useCoreStore((state) => state.refreshArtifacts);
  const memories = useCoreStore((state) => (
    state.personMemoriesByAgent[state.activeAgentId || ""] || EMPTY_MEMORIES
  ));
  const memoryList = useCoreStore((state) => (
    state.personMemoryListByAgent[state.activeAgentId || ""] || EMPTY_MEMORY_LIST
  ));
  const refreshMemories = useCoreStore((state) => state.refreshPersonMemories);
  const loadMoreMemories = useCoreStore((state) => state.loadMorePersonMemories);
  const activeSessionId = useCoreStore((state) => state.activeSessionByAgent[state.activeAgentId || ""] || "");
  const agentName = useCoreStore((state) => (
    state.connectionByAgent[state.activeAgentId || ""]?.agentName
    || state.agents.find((item) => item.id === state.activeAgentId)?.name
    || "Agent"
  ));
  const connectionStatus = useCoreStore((state) => state.connectionByAgent[state.activeAgentId || ""]?.status || "disconnected");
  const agentState = useCoreStore((state) => state.agentStateByAgent[state.activeAgentId || ""]);
  const [view, setView] = useState<"current" | "history">("current");
  const [selectedId, setSelectedId] = useState("");

  useEffect(() => {
    if (open && agentId) {
      void refresh(agentId);
      void refreshAssignments(agentId);
      void refreshArtifacts(agentId);
      void refreshMemories(agentId);
    }
  }, [agentId, open, refresh, refreshArtifacts, refreshAssignments, refreshMemories]);

  useEffect(() => {
    setSelectedId("");
  }, [agentId]);

  useEffect(() => {
    if (selectedAssignmentId) onSectionChange("assignment");
  }, [onSectionChange, selectedAssignmentId]);

  const visible = useMemo(
    () => activities.filter((item) => view === "current"
      ? ACTIVE.has(item.status)
      : !ACTIVE.has(item.status)),
    [activities, view],
  );
  const selected = activities.find((item) => item.id === selectedId)
    || visible[0]
    || null;
  const primaryActivity = activities.find((item) => ACTIVE.has(item.status));

  if (!open) return null;

  return (
    <aside className="agent-right-sidebar" aria-label="Agent 活动">
      <header className="agent-right-sidebar-header">
        <div>
          <strong>{agentName}</strong>
          <span>
            {connectionStatus === "connected" ? "在线" : "未连接"}
            {agentState ? ` · ${livingStateNames[agentState.living]}` : ""}
            {agentState?.focusSummary
              ? ` · ${agentState.focusSummary}`
              : primaryActivity
                ? ` · ${primaryActivity.progressSummary || primaryActivity.title}`
                : ""}
          </span>
        </div>
        <div className="agent-right-sidebar-actions">
          <button type="button" onClick={() => void refresh(agentId)} title="刷新">
            <Icon name="refresh" size={15} />
          </button>
          <button type="button" onClick={onClose} title="关闭">×</button>
        </div>
      </header>
      <div className="right-sidebar-sections">
        <button className={section === "activity" ? "active" : ""} onClick={() => onSectionChange("activity")}>
          动态
        </button>
        <button className={section === "assignment" ? "active" : ""} onClick={() => onSectionChange("assignment")}>
          委托
          {assignments.some((item) => ACTIVE.has(activityStatusForAssignment(item.status))) && (
            <span>{assignments.filter((item) => ACTIVE.has(activityStatusForAssignment(item.status))).length}</span>
          )}
        </button>
        <button className={section === "artifact" ? "active" : ""} onClick={() => onSectionChange("artifact")}>
          产物
          {artifacts.length > 0 && <span>{artifacts.length}</span>}
        </button>
        <button className={section === "memory" ? "active" : ""} onClick={() => onSectionChange("memory")}>
          记忆
          {memories.length > 0 && <span>{memories.length}{memoryList.hasMore ? "+" : ""}</span>}
        </button>
        <button className={section === "context" ? "active" : ""} onClick={() => onSectionChange("context")}>
          上下文
        </button>
      </div>
      {section === "activity" ? <>
        <div className="activity-view-tabs">
        <button className={view === "current" ? "active" : ""} onClick={() => setView("current")}>
          当前
          <span>{activities.filter((item) => ACTIVE.has(item.status)).length}</span>
        </button>
        <button className={view === "history" ? "active" : ""} onClick={() => setView("history")}>
          最近完成
        </button>
      </div>
      <div className="activity-sidebar-body">
        <nav className="activity-list">
          {loading && visible.length === 0 && <p className="activity-empty">正在加载…</p>}
          {error && <p className="activity-error">{error}</p>}
          {!loading && !error && visible.length === 0 && (
            <div className="activity-empty-state">
              <span className="activity-empty-orbit" />
              <strong>{view === "current" ? "现在没有后台活动" : "还没有最近活动"}</strong>
              <p>{view === "current" ? "Agent 有新的工作或内在整理时会自然出现在这里。" : "完成的活动会按时间浮到这里。"}</p>
            </div>
          )}
          {visible.map((activity) => (
            <button
              type="button"
              className={`activity-list-item ${selected?.id === activity.id ? "selected" : ""}`}
              key={activity.id}
              onClick={() => setSelectedId(activity.id)}
            >
              <span className={`activity-category-dot ${activity.category}`} />
              <span className="activity-list-copy">
                <strong>{activity.title}</strong>
                <small>{activity.progressSummary || statusNames[activity.status]}</small>
              </span>
              <span className={`activity-status-pill ${activity.status}`}>
                {statusNames[activity.status]}
              </span>
            </button>
          ))}
        </nav>
        {selected && (
          <ActivityDetail activity={selected} />
        )}
      </div>
      </> : section === "assignment" ? (
        <AssignmentPanel
          selectedId={selectedAssignmentId}
          onSelect={onSelectAssignment}
          onClose={() => onSectionChange("activity")}
        />
      ) : section === "artifact" ? (
        <ArtifactPanel
          agentId={agentId}
          artifacts={artifacts}
          loading={artifactLoading}
          error={artifactError}
          onRefresh={() => void refreshArtifacts(agentId)}
          activeSessionId={activeSessionId}
          focusedArtifactKey={focusedArtifactKey}
        />
      ) : section === "memory" ? (
        <MemoryPanel
          memories={memories}
          page={memoryList}
          onRefresh={() => void refreshMemories(agentId)}
          onLoadMore={() => void loadMoreMemories(agentId)}
        />
      ) : (
        <ContextPanel
          agentName={agentName}
          connectionStatus={connectionStatus}
          sessionId={activeSessionId}
          activities={activities}
          artifacts={artifacts}
          agentState={agentState}
          focusedMemories={focusedMemories}
        />
      )}
    </aside>
  );
}

function MemoryPanel({
  memories,
  page,
  onRefresh,
  onLoadMore,
}: {
  memories: PersonMemorySnapshot[];
  page: PersonMemoryListState;
  onRefresh: () => void;
  onLoadMore: () => void;
}) {
  return (
    <section className="person-memory-panel">
      <div className="person-memory-heading">
        <div>
          <strong>与当前人物相关的长期记忆</strong>
          <p>只展示 Agent 可以向当前人物呈现的记忆，不包含全局知识、梦境或内在叙事。</p>
        </div>
        <button type="button" onClick={onRefresh} disabled={page.loading || page.loadingMore}>
          刷新
        </button>
      </div>
      {page.loading && memories.length === 0 && <p className="activity-empty">正在加载…</p>}
      {page.error && <p className="activity-error">{page.error}</p>}
      {!page.loading && !page.error && memories.length === 0 && (
        <div className="activity-empty-state">
          <strong>还没有形成长期记忆</strong>
          <p>随着你们持续交流，适合长期保留的内容会自然出现在这里。</p>
        </div>
      )}
      <div className="person-memory-list">
        {memories.map((memory) => (
          <article key={memory.id}>
            <strong>{memory.summary}</strong>
            <div className="person-memory-meta">
              <span>{memorySourceName(memory.source) || "长期记忆"}</span>
              {memory.createdAt > 0 && <time>{new Date(memory.createdAt * 1000).toLocaleString()}</time>}
            </div>
            {memory.tags.length > 0 && (
              <div className="person-memory-tags">
                {memory.tags.map((tag) => <span key={tag}>#{tag}</span>)}
              </div>
            )}
            {memory.lastAccessed > memory.createdAt && (
              <small>最近使用：{new Date(memory.lastAccessed * 1000).toLocaleString()}</small>
            )}
          </article>
        ))}
      </div>
      {page.hasMore && (
        <button
          type="button"
          className="person-memory-load-more"
          onClick={onLoadMore}
          disabled={page.loadingMore}
        >
          {page.loadingMore ? "正在加载…" : "加载更多"}
        </button>
      )}
    </section>
  );
}

function ArtifactPanel({
  agentId,
  artifacts,
  loading,
  error,
  onRefresh,
  activeSessionId,
  focusedArtifactKey,
}: {
  agentId: string;
  artifacts: ArtifactSnapshot[];
  loading: boolean;
  error: string;
  onRefresh: () => void;
  activeSessionId: string;
  focusedArtifactKey: string;
}) {
  const [opening, setOpening] = useState("");
  const [scope, setScope] = useState<"current" | "all">("current");
  const [selectedKey, setSelectedKey] = useState("");
  const [previewUrl, setPreviewUrl] = useState("");
  const [previewError, setPreviewError] = useState("");
  const visible = scope === "current"
    ? artifacts.filter((artifact) => artifact.sessionId === activeSessionId)
    : artifacts;
  const selected = visible.find((artifact) => (
    `${artifact.sessionId}:${artifact.id}` === selectedKey
  )) || visible[0] || null;

  useEffect(() => {
    if (!focusedArtifactKey) return;
    setScope("all");
    setSelectedKey(focusedArtifactKey);
  }, [focusedArtifactKey]);

  useEffect(() => {
    setPreviewUrl("");
    setPreviewError("");
    if (!selected || selected.kind !== "image" || selected.size > 5 * 1024 * 1024) return;
    let cancelled = false;
    void window.gateway.getArtifact({
      agentId,
      sessionId: selected.sessionId,
      artifactId: selected.id,
    }).then((response) => {
      if (cancelled) return;
      if (response.error) {
        setPreviewError(response.error.message);
        return;
      }
      const raw = response.result?.artifact;
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) return;
      const value = raw as Record<string, unknown>;
      const data = typeof value.dataBase64 === "string" ? value.dataBase64 : "";
      const mime = typeof value.mimeType === "string" ? value.mimeType : selected.mimeType;
      if (data) setPreviewUrl(`data:${mime};base64,${data}`);
    }).catch((reason) => {
      if (!cancelled) setPreviewError(String(reason));
    });
    return () => { cancelled = true; };
  }, [agentId, selected?.id, selected?.kind, selected?.mimeType, selected?.sessionId, selected?.size]);

  const open = async (artifact: ArtifactSnapshot) => {
    if (opening) return;
    setOpening(`${artifact.sessionId}:${artifact.id}`);
    try {
      await window.gateway.openArtifact({
        agentId,
        sessionId: artifact.sessionId,
        artifactId: artifact.id,
      });
    } finally {
      setOpening("");
    }
  };
  return (
    <section className="artifact-sidebar-panel">
      <div className="artifact-sidebar-toolbar">
        <div className="artifact-scope-tabs">
          <button type="button" className={scope === "current" ? "active" : ""} onClick={() => setScope("current")}>
            当前会话
          </button>
          <button type="button" className={scope === "all" ? "active" : ""} onClick={() => setScope("all")}>
            全部
          </button>
        </div>
        <button type="button" onClick={onRefresh}>刷新</button>
      </div>
      {selected && (
        <div className="artifact-sidebar-preview">
          {previewUrl ? (
            <img src={previewUrl} alt={selected.name} />
          ) : (
            <span className={`artifact-kind-icon ${selected.kind}`}>
              <Icon name={selected.kind === "image" ? "sparkles" : "file-text"} size={24} />
            </span>
          )}
          <div>
            <strong>{selected.name}</strong>
            <small>{formatBytes(selected.size)} · {new Date(selected.createdAt * 1000).toLocaleString()}</small>
            {previewError && <em>{previewError}</em>}
          </div>
          <button type="button" onClick={() => void open(selected)} disabled={Boolean(opening)}>
            {opening ? "打开中…" : "打开"}
          </button>
        </div>
      )}
      {loading && visible.length === 0 && <p className="activity-empty">正在加载…</p>}
      {error && <p className="activity-error">{error}</p>}
      {!loading && !error && visible.length === 0 && (
        <div className="activity-empty-state">
          <strong>{scope === "current" ? "当前会话还没有产物" : "还没有产物"}</strong>
          <p>文件、图片和报告生成后会集中出现在这里。</p>
        </div>
      )}
      <div className="artifact-sidebar-grid">
        {visible.map((artifact) => {
          const key = `${artifact.sessionId}:${artifact.id}`;
          return (
            <button
              type="button"
              key={key}
              className={selected && `${selected.sessionId}:${selected.id}` === key ? "selected" : ""}
              onClick={() => setSelectedKey(key)}
            >
              <span className={`artifact-kind-icon ${artifact.kind}`}>
                <Icon name={artifact.kind === "image" ? "sparkles" : "file-text"} size={17} />
              </span>
              <span>
                <strong>{artifact.name}</strong>
                <small>{formatBytes(artifact.size)} · {new Date(artifact.createdAt * 1000).toLocaleString()}</small>
                {artifact.description && <em>{artifact.description}</em>}
              </span>
              <i>查看</i>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function ContextPanel({
  agentName,
  connectionStatus,
  sessionId,
  activities,
  artifacts,
  agentState,
  focusedMemories,
}: {
  agentName: string;
  connectionStatus: string;
  sessionId: string;
  activities: ActivitySnapshot[];
  artifacts: ArtifactSnapshot[];
  agentState: import("../../store").AgentStateSnapshot | undefined;
  focusedMemories: MemoryReference[];
}) {
  const active = activities.filter((item) => ACTIVE.has(item.status));
  const personId = activities.find((item) => item.personId)?.personId || "";
  const goal = active.find((item) => item.kind === "goal_pace");
  const recentMemory = activities.find((item) => (
    item.kind === "internal_processing"
    || item.kind === "memory_extraction"
    || item.kind === "dag_compaction"
  ));
  return (
    <section className="context-sidebar-panel">
      <ContextBlock title="本次回答召回的记忆">
        {focusedMemories.length > 0 ? (
          <div className="memory-reference-list">
            <p>这些记忆在回答前被召回并提供给 Agent，不代表逐条直接引用。</p>
            {focusedMemories.map((memory, index) => (
              <article key={`${memory.id || "memory"}-${index}`}>
                <strong>{memory.summary}</strong>
                <span>
                  {memory.source ? memorySourceName(memory.source) : "长期记忆"}
                  {memory.createdAt > 0
                    ? ` · ${new Date(memory.createdAt * 1000).toLocaleString()}`
                    : ""}
                </span>
                {memory.tags.length > 0 && (
                  <small>{memory.tags.map((tag) => `#${tag}`).join(" ")}</small>
                )}
              </article>
            ))}
          </div>
        ) : (
          <>
            <strong>点击一条带有记忆标记的回答查看</strong>
            <span>这里只展示回答前实际召回的长期记忆摘要。</span>
          </>
        )}
      </ContextBlock>
      <ContextBlock title="当前 Agent">
        <strong>{agentName}</strong>
        <span>
          {connectionStatus === "connected" ? "在线" : "未连接"}
          {agentState ? ` · ${livingStateNames[agentState.living]}` : ""}
        </span>
        {agentState?.focusSummary && <span>{agentState.focusSummary}</span>}
        {agentState?.livingSince > 0 && (
          <span>当前状态持续 {formatDuration(Date.now() / 1000 - agentState.livingSince)}</span>
        )}
      </ContextBlock>
      <ContextBlock title="最近意图">
        <strong>{agentState?.lastIntent
          ? intentTypeName(agentState.lastIntent.type)
          : "暂时没有可观察的意图决策"}</strong>
        {agentState?.lastIntent?.summary && <span>{agentState.lastIntent.summary}</span>}
        {agentState?.lastIntent?.decidedAt ? (
          <span>{new Date(agentState.lastIntent.decidedAt * 1000).toLocaleString()}</span>
        ) : null}
      </ContextBlock>
      <ContextBlock title="当前会话">
        <strong>{sessionId || "尚未选择会话"}</strong>
        {personId && <span>人物：{personId}</span>}
      </ContextBlock>
      <ContextBlock title="正在发生">
        <strong>{active.length > 0 ? `${active.length} 项活动` : "没有后台活动"}</strong>
        {active.slice(0, 3).map((item) => <span key={item.id}>{item.title} · {statusNames[item.status]}</span>)}
      </ContextBlock>
      <ContextBlock title="当前 Goal">
        <strong>{goal?.title || "当前没有可观察的 Goal 推进"}</strong>
        {goal?.progressSummary && <span>{goal.progressSummary}</span>}
      </ContextBlock>
      <ContextBlock title="记忆整理">
        <strong>{recentMemory ? recentMemory.title : "暂无最近整理记录"}</strong>
        {recentMemory?.progressSummary && <span>{recentMemory.progressSummary}</span>}
      </ContextBlock>
      <ContextBlock title="产物">
        <strong>{artifacts.length} 个可读取产物</strong>
        <span>仅展示 Agent 已授权给当前人物或全局可见的资产</span>
      </ContextBlock>
    </section>
  );
}

function memorySourceName(value: string): string {
  const names: Record<string, string> = {
    immediate: "对话中形成",
    periodic: "周期整理",
    dream: "梦境整理",
    manual: "明确记录",
    internal: "内部经验",
    every_turn: "轮次整理",
    merged: "记忆合并",
    task_completion: "任务完成后形成",
  };
  return names[value] || value;
}

function ContextBlock({ title, children }: { title: string; children: ReactNode }) {
  return <div className="context-block"><h3>{title}</h3><div>{children}</div></div>;
}

function ActivityDetail({ activity }: { activity: ActivitySnapshot }) {
  const hasProgress = activity.totalSteps !== null && activity.totalSteps > 0;
  const percent = hasProgress && activity.completedSteps !== null
    ? Math.round((activity.completedSteps / activity.totalSteps!) * 100)
    : null;
  return (
    <section className="activity-detail">
      <div className="activity-detail-heading">
        <span>{categoryNames[activity.category]}</span>
        <time>{formatTime(activity.updatedAt)}</time>
        <h2>{activity.title}</h2>
        <p>{activity.progressSummary || activity.resultSummary || statusNames[activity.status]}</p>
      </div>
      {percent !== null && (
        <div className="activity-detail-progress">
          <div><span style={{ width: `${percent}%` }} /></div>
          <small>{activity.completedSteps}/{activity.totalSteps} · {percent}%</small>
        </div>
      )}
      {activity.status === "paused" && (
        <div className="activity-pause-reason">
          {pauseNames[activity.pauseReason] || activity.pauseReason || "活动已暂停"}
        </div>
      )}
      {activity.errorMessage && <div className="activity-error">{activity.errorMessage}</div>}
      {activity.steps.length > 0 && (
        <ol className="activity-step-list">
          {activity.steps.map((step, index) => (
            <li className={step.status} key={step.id}>
              <span>{step.status === "completed" ? "✓" : step.status === "running" ? "•" : index + 1}</span>
              <div>
                <strong>{step.title}</strong>
                {step.summary && <p>{step.summary}</p>}
              </div>
            </li>
          ))}
        </ol>
      )}
      <dl className="activity-metadata">
        {activity.currentStep && <><dt>当前阶段</dt><dd>{activity.currentStep}</dd></>}
        <dt>活动类型</dt><dd>{activity.kind}</dd>
        {activity.originSessionId && <><dt>来源会话</dt><dd>{activity.originSessionId}</dd></>}
      </dl>
    </section>
  );
}

function formatTime(value: number): string {
  if (!value) return "";
  return new Date(value * 1000).toLocaleString();
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

const livingStateNames = {
  dormant: "休眠",
  waking: "正在苏醒",
  awake: "清醒",
  idle: "空闲",
  working: "工作中",
  sleeping: "睡眠中",
  dreaming: "做梦中",
} as const;

function intentTypeName(value: string): string {
  const names: Record<string, string> = {
    wait: "暂不行动",
    learn: "学习",
    progress: "推进目标",
    work: "工作",
    express: "表达",
    care: "关心",
    greet: "问候",
    sleep: "准备睡眠",
    reflect: "反思",
    dream: "进入梦境",
  };
  return names[value.toLowerCase()] || value || "未知意图";
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return "不到 1 分钟";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时`;
  return `${Math.floor(seconds / 86400)} 天`;
}

function activityStatusForAssignment(status: AssignmentSnapshot["status"]): ActivitySnapshot["status"] {
  if (status === "completed") return "completed";
  if (status === "failed") return "failed";
  if (status === "cancelled" || status === "declined") return "cancelled";
  if (status === "paused" || status === "waiting_person") return "paused";
  if (status === "in_progress") return "running";
  return "queued";
}
