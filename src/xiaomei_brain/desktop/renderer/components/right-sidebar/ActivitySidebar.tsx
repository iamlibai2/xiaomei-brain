import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type {
  ActivityCategory,
  ActivitySnapshot,
  ArtifactSnapshot,
  AgentStateMetric,
  AssignmentSnapshot,
  MemoryReference,
  PersonMemoryListState,
  PersonMemorySnapshot,
} from "../../store";
import { useCoreStore } from "../../store";
import { Icon } from "../ui";
import { AssignmentPanel } from "./AssignmentPanel";
import { ProjectPanel } from "./ProjectPanel";
import { supportsArtifactPreview } from "../../artifacts/preview-capability";

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
  onOpenArtifact,
}: {
  open: boolean;
  onClose: () => void;
  selectedAssignmentId: string | null;
  onSelectAssignment: (assignmentId: string | null) => void;
  section: "activity" | "state" | "project" | "assignment" | "artifact" | "memory" | "context";
  onSectionChange: (section: "activity" | "state" | "project" | "assignment" | "artifact" | "memory" | "context") => void;
  focusedArtifactKey: string;
  focusedMemories: MemoryReference[];
  onOpenArtifact: (artifactId: string, sessionId: string) => void;
}) {
  const agentId = useCoreStore((state) => state.activeAgentId || "");
  const activities = useCoreStore((state) => state.activitiesByAgent[state.activeAgentId || ""] || EMPTY);
  const loading = useCoreStore((state) => state.activityLoadingByAgent[state.activeAgentId || ""] || false);
  const error = useCoreStore((state) => state.activityErrorByAgent[state.activeAgentId || ""] || "");
  const refresh = useCoreStore((state) => state.refreshActivities);
  const assignments = useCoreStore((state) => state.assignmentsByAgent[state.activeAgentId || ""] || EMPTY_ASSIGNMENTS);
  const refreshAssignments = useCoreStore((state) => state.refreshAssignments);
  const currentProject = useCoreStore((state) => state.currentProjectByAgent[state.activeAgentId || ""] || null);
  const projectLoading = useCoreStore((state) => state.projectLoadingByAgent[state.activeAgentId || ""] || false);
  const projectError = useCoreStore((state) => state.projectErrorByAgent[state.activeAgentId || ""] || "");
  const refreshCurrentProject = useCoreStore((state) => state.refreshCurrentProject);
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
  const refreshAgentState = useCoreStore((state) => state.refreshAgentState);
  const activeSessionId = useCoreStore((state) => state.activeSessionByAgent[state.activeAgentId || ""] || "");
  const agentName = useCoreStore((state) => (
    state.connectionByAgent[state.activeAgentId || ""]?.agentName
    || state.agents.find((item) => item.id === state.activeAgentId)?.name
    || "Agent"
  ));
  const connectionStatus = useCoreStore((state) => state.connectionByAgent[state.activeAgentId || ""]?.status || "disconnected");
  const agentState = useCoreStore((state) => state.agentStateByAgent[state.activeAgentId || ""]);
  const speaking = useCoreStore((state) => Boolean(state.speakingByAgent[state.activeAgentId || ""]));
  const [view, setView] = useState<"current" | "history">("current");
  const [selectedId, setSelectedId] = useState("");

  useEffect(() => {
    if (open && agentId) {
      void refresh(agentId);
      void refreshAssignments(agentId);
      void refreshCurrentProject(agentId);
      void refreshArtifacts(agentId);
      void refreshMemories(agentId);
      void refreshAgentState(agentId);
    }
  }, [
    activeSessionId,
    agentId,
    open,
    refresh,
    refreshAgentState,
    refreshArtifacts,
    refreshAssignments,
    refreshCurrentProject,
    refreshMemories,
  ]);

  useEffect(() => {
    if (!open || section !== "state" || !agentId) return;
    const timer = window.setInterval(() => {
      void refreshAgentState(agentId);
    }, 10_000);
    return () => window.clearInterval(timer);
  }, [agentId, open, refreshAgentState, section]);

  useEffect(() => {
    setSelectedId("");
  }, [agentId]);

  useEffect(() => {
    if (selectedAssignmentId) onSectionChange("assignment");
  }, [onSectionChange, selectedAssignmentId]);

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose, open]);

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

  const activeAssignmentCount = assignments.filter(
    (item) => ACTIVE.has(activityStatusForAssignment(item.status)),
  ).length;

  return (
    <>
    <button
      type="button"
      className="agent-right-sidebar-backdrop"
      aria-label="关闭 Agent 详情"
      onClick={onClose}
    />
    <aside className="agent-right-sidebar" aria-label="Agent 详情">
      <header className="agent-right-sidebar-header">
        <div className="agent-right-sidebar-identity">
          <div className="agent-right-sidebar-avatar">{agentName.charAt(0)}</div>
          <div className="agent-right-sidebar-copy">
            <strong>{agentName}</strong>
            <span>
              <i className={connectionStatus === "connected" ? "online" : "offline"} />
              {connectionStatus === "connected" ? "在线" : "未连接"}
              {agentState ? ` · ${livingStateNames[agentState.living]}` : ""}
            </span>
            {(agentState?.focusSummary || primaryActivity) && (
              <small>
                {agentState?.focusSummary
                  || primaryActivity?.progressSummary
                  || primaryActivity?.title}
              </small>
            )}
          </div>
        </div>
        <div className="agent-right-sidebar-actions">
          <button type="button" onClick={() => {
            void refresh(agentId);
            void refreshAgentState(agentId);
          }} title="刷新">
            <Icon name="refresh" size={15} />
          </button>
          <button type="button" onClick={onClose} title="关闭右栏" aria-label="关闭右栏">
            <Icon name="sidebar-panel-right" size={15} />
          </button>
        </div>
      </header>
      <nav className="right-sidebar-sections" aria-label="Agent 详情栏目">
        <button type="button" className={section === "activity" ? "active" : ""} aria-current={section === "activity" ? "page" : undefined} onClick={() => onSectionChange("activity")}>
          <Icon name="clock" size={15} />
          <span className="right-sidebar-section-label">动态</span>
        </button>
        <button type="button" className={section === "state" ? "active" : ""} aria-current={section === "state" ? "page" : undefined} onClick={() => onSectionChange("state")}>
          <Icon name="sparkles" size={15} />
          <span className="right-sidebar-section-label">状态</span>
        </button>
        <button type="button" className={section === "project" ? "active" : ""} aria-current={section === "project" ? "page" : undefined} onClick={() => onSectionChange("project")}>
          <Icon name="folder" size={15} />
          <span className="right-sidebar-section-label">项目</span>
          {currentProject && <span className="right-sidebar-section-count">1</span>}
        </button>
        <button type="button" className={section === "assignment" ? "active" : ""} aria-current={section === "assignment" ? "page" : undefined} onClick={() => onSectionChange("assignment")}>
          <Icon name="robot" size={15} />
          <span className="right-sidebar-section-label">委托</span>
          {activeAssignmentCount > 0 && <span className="right-sidebar-section-count">{activeAssignmentCount}</span>}
        </button>
        <button type="button" className={section === "artifact" ? "active" : ""} aria-current={section === "artifact" ? "page" : undefined} onClick={() => onSectionChange("artifact")}>
          <Icon name="folder" size={15} />
          <span className="right-sidebar-section-label">产物</span>
          {artifacts.length > 0 && <span className="right-sidebar-section-count">{artifacts.length}</span>}
        </button>
        <button type="button" className={section === "memory" ? "active" : ""} aria-current={section === "memory" ? "page" : undefined} onClick={() => onSectionChange("memory")}>
          <Icon name="info" size={15} />
          <span className="right-sidebar-section-label">记忆</span>
          {memories.length > 0 && <span className="right-sidebar-section-count">{memories.length}{memoryList.hasMore ? "+" : ""}</span>}
        </button>
        <button type="button" className={section === "context" ? "active" : ""} aria-current={section === "context" ? "page" : undefined} onClick={() => onSectionChange("context")}>
          <Icon name="file-text" size={15} />
          <span className="right-sidebar-section-label">上下文</span>
        </button>
      </nav>
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
      </> : section === "state" ? (
        <StatusPanel
          agentName={agentName}
          connectionStatus={connectionStatus}
          agentState={agentState}
          speaking={speaking}
          onRefresh={() => void refreshAgentState(agentId)}
        />
      ) : section === "project" ? (
        <ProjectPanel
          detail={currentProject}
          loading={projectLoading}
          error={projectError}
          onRefresh={() => void refreshCurrentProject(agentId)}
        />
      ) : section === "assignment" ? (
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
          onOpenArtifact={onOpenArtifact}
        />
      ) : section === "memory" ? (
        <MemoryPanel
          memories={memories}
          page={memoryList}
          focusedMemories={focusedMemories}
          onRefresh={() => void refreshMemories(agentId)}
          onLoadMore={() => void loadMoreMemories(agentId)}
        />
      ) : section === "context" ? (
        <ContextPanel
          agentName={agentName}
          connectionStatus={connectionStatus}
          sessionId={activeSessionId}
          activities={activities}
          artifacts={artifacts}
          agentState={agentState}
          focusedMemories={focusedMemories}
        />
      ) : null}
    </aside>
    </>
  );
}

function MemoryPanel({
  memories,
  page,
  focusedMemories,
  onRefresh,
  onLoadMore,
}: {
  memories: PersonMemorySnapshot[];
  page: PersonMemoryListState;
  focusedMemories: MemoryReference[];
  onRefresh: () => void;
  onLoadMore: () => void;
}) {
  return (
    <section className="person-memory-panel">
      {focusedMemories.length > 0 && (
        <div className="focused-memory-section">
          <div className="person-memory-heading">
            <div>
              <strong>本次回答召回的记忆</strong>
              <p>这些记忆在回答前被召回并提供给 Agent，不代表逐条直接引用。</p>
            </div>
          </div>
          <div className="memory-reference-list">
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
        </div>
      )}
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
  onOpenArtifact,
}: {
  agentId: string;
  artifacts: ArtifactSnapshot[];
  loading: boolean;
  error: string;
  onRefresh: () => void;
  activeSessionId: string;
  focusedArtifactKey: string;
  onOpenArtifact: (artifactId: string, sessionId: string) => void;
}) {
  const [scope, setScope] = useState<"current" | "all">("current");
  const [openingKey, setOpeningKey] = useState("");
  const [actionError, setActionError] = useState("");
  const visible = scope === "current"
    ? artifacts.filter((artifact) => artifact.sessionId === activeSessionId)
    : artifacts;

  useEffect(() => {
    if (!focusedArtifactKey) return;
    setScope("all");
  }, [focusedArtifactKey]);

  const activateArtifact = async (artifact: ArtifactSnapshot) => {
    if (supportsArtifactPreview(artifact)) {
      onOpenArtifact(artifact.id, artifact.sessionId);
      return;
    }
    const key = `${artifact.sessionId}:${artifact.id}`;
    if (openingKey) return;
    setOpeningKey(key);
    setActionError("");
    try {
      const result = await window.gateway.openArtifact({
        agentId,
        sessionId: artifact.sessionId,
        artifactId: artifact.id,
      });
      if (!result.ok) setActionError(result.error || "无法打开产物");
    } finally {
      setOpeningKey("");
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
      {loading && visible.length === 0 && <p className="activity-empty">正在加载…</p>}
      {error && <p className="activity-error">{error}</p>}
      {actionError && <p className="activity-error">{actionError}</p>}
      {!loading && !error && visible.length === 0 && (
        <div className="activity-empty-state">
          <strong>{scope === "current" ? "当前会话还没有产物" : "还没有产物"}</strong>
          <p>文件、图片和报告生成后会集中出现在这里。</p>
        </div>
      )}
      <div className="artifact-sidebar-grid">
        {visible.map((artifact) => {
          const key = `${artifact.sessionId}:${artifact.id}`;
          const previewable = supportsArtifactPreview(artifact);
          return (
            <button
              type="button"
              key={key}
              className={focusedArtifactKey === key ? "selected" : ""}
              onClick={() => { void activateArtifact(artifact); }}
              disabled={Boolean(openingKey)}
              title={`${previewable ? "预览" : "打开"} ${artifact.name}`}
            >
              <span className={`artifact-kind-icon ${artifact.kind}`}>
                <Icon name={artifact.kind === "image" ? "sparkles" : "file-text"} size={17} />
              </span>
              <span>
                <strong>{artifact.name}</strong>
                <small>{formatBytes(artifact.size)} · {new Date(artifact.updatedAt * 1000).toLocaleString()}</small>
                {artifact.description && <em>{artifact.description}</em>}
              </span>
              <i>{openingKey === key ? "打开中…" : previewable ? "预览" : "打开"}</i>
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
        {agentState && agentState.livingSince > 0 && (
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

function ContextBlock({ title, children }: { title: string; children: ReactNode }) {
  return <div className="context-block"><h3>{title}</h3><div>{children}</div></div>;
}

function StatusPanel({
  agentName,
  connectionStatus,
  agentState,
  speaking,
  onRefresh,
}: {
  agentName: string;
  connectionStatus: string;
  agentState: import("../../store").AgentStateSnapshot | undefined;
  speaking: boolean;
  onRefresh: () => void;
}) {
  const internal = agentState?.internal;
  const relationship = agentState?.relationship;

  return (
    <section className="agent-status-panel">
      <div className="agent-status-panel-heading">
        <div>
          <strong>{agentName}的状态</strong>
          <span>Agent 当前正在经历的生命、关系与身体状态</span>
        </div>
        <button type="button" onClick={onRefresh}>刷新</button>
      </div>

      <StateCard title="当前状态" accent={speaking ? "speaking" : agentState?.living || "idle"}>
        <div className="agent-current-state">
          <span className={`agent-current-state-dot ${speaking ? "speaking" : agentState?.living || "idle"}`} />
          <div>
            <strong>
              {connectionStatus === "connected"
                ? speaking
                  ? "正在说话"
                  : agentState
                    ? livingStateNames[agentState.living]
                    : "在线"
                : "未连接"}
            </strong>
            {agentState?.focusSummary && <p>{agentState.focusSummary}</p>}
            {agentState?.livingSince ? (
              <small>已持续 {formatDuration(Date.now() / 1000 - agentState.livingSince)}</small>
            ) : null}
          </div>
        </div>
      </StateCard>

      <StateCard title={relationship ? `与${relationship.displayName}的关系` : "当前关系"}>
        {relationship ? (
          <>
            <div className="relationship-summary">
              <strong>{relationship.relationType} · {relationship.status}</strong>
              <span>{relationship.description}</span>
            </div>
            <StateMetricList metrics={[
              {
                key: "depth",
                label: "熟悉深度",
                value: relationship.depth,
                description: relationship.depthDescription,
              },
              {
                key: "trust",
                label: "信任",
                value: relationship.trust,
                description: relationship.trustDescription,
              },
              {
                key: "closeness",
                label: "亲密",
                value: relationship.closeness,
                description: relationship.closenessDescription,
              },
            ]} compact />
            <small className="relationship-interactions">
              已互动 {relationship.interactionCount} 次
              {relationship.lastInteractionAt
                ? ` · 最近 ${new Date(relationship.lastInteractionAt * 1000).toLocaleString()}`
                : ""}
            </small>
          </>
        ) : (
          <p className="state-empty-copy">当前连接还没有可展示的人物关系。</p>
        )}
      </StateCard>

      {internal ? (
        <>
          <StateCard title="当前心情">
            <div className="mood-summary">
              <strong>{internal.moodSummary || "平静"}</strong>
              <span>能量 {formatPercent(internal.energy)} · {internal.energyDescription}</span>
            </div>
            {internal.emotions.length > 0 ? (
              <div className="emotion-state-list">
                {internal.emotions.map((emotion) => (
                  <span key={emotion.key}>
                    {emotion.label}<strong>{formatPercent(emotion.value)}</strong>
                  </span>
                ))}
              </div>
            ) : (
              <p className="state-empty-copy">没有明显的活跃情绪。</p>
            )}
          </StateCard>

          <StateCard title="身体感受">
            <p className="state-natural-language">{internal.somatic}</p>
          </StateCard>

          <StateCard title="欲望">
            <StateMetricList metrics={internal.desires} />
          </StateCard>

          <StateCard title="激素">
            <StateMetricList metrics={internal.hormones} />
          </StateCard>

          <StateCard title="状态矛盾">
            {internal.contradictions.length > 0 ? (
              <div className="state-tension-list">
                {internal.contradictions.map((item) => <p key={item}>{item}</p>)}
              </div>
            ) : (
              <p className="state-empty-copy">当前没有检测到明显的内在矛盾。</p>
            )}
          </StateCard>

          <StateCard title="行为倾向">
            {internal.impulse && <p className="state-natural-language">{internal.impulse}</p>}
            {internal.behaviorTendencies.length > 0 && (
              <ul className="behavior-tendency-list">
                {internal.behaviorTendencies.map((item) => <li key={item}>{item}</li>)}
              </ul>
            )}
            {!internal.impulse && internal.behaviorTendencies.length === 0 && (
              <p className="state-empty-copy">当前状态没有形成明显的行为倾向。</p>
            )}
          </StateCard>

          <details className="raw-state-details">
            <summary>原始状态</summary>
            {relationship?.rawContext && (
              <>
                <h4>关系上下文</h4>
                <pre>{relationship.rawContext}</pre>
              </>
            )}
            <h4>身体状态上下文</h4>
            <pre>{internal.rawContext}</pre>
          </details>

          {internal.observedAt > 0 && (
            <time className="agent-state-observed-at">
              最近更新：{new Date(internal.observedAt * 1000).toLocaleString()}
            </time>
          )}
        </>
      ) : (
        <div className="activity-empty-state">
          <strong>身体状态尚不可用</strong>
          <p>Agent 未启用意识系统，或状态仍在初始化。</p>
        </div>
      )}
    </section>
  );
}

function StateMetricList({
  metrics,
  compact = false,
}: {
  metrics: AgentStateMetric[];
  compact?: boolean;
}) {
  return (
    <div className={`state-metric-list ${compact ? "compact" : ""}`}>
      {metrics.map((metric) => (
        <div className="state-metric" key={metric.key}>
          <div>
            <strong>{metric.label}</strong>
            <span>{formatPercent(metric.value)}</span>
          </div>
          <div className="state-metric-track">
            <span style={{ width: `${Math.round(metric.value * 100)}%` }} />
          </div>
          <p>{metric.description}</p>
        </div>
      ))}
    </div>
  );
}

function StateCard({
  title,
  accent = "",
  children,
}: {
  title: string;
  accent?: string;
  children: ReactNode;
}) {
  return (
    <article className={`agent-state-card ${accent}`}>
      <h3>{title}</h3>
      {children}
    </article>
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
  dreaming: "梦境中",
} as const;

function formatPercent(value: number): string {
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

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
