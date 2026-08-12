import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import i18n from "../../i18n";
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

function categoryName(category: ActivityCategory): string {
  return i18n.t(`rightSidebarUi.category${category.charAt(0).toUpperCase()}${category.slice(1)}`);
}

function statusName(status: ActivitySnapshot["status"]): string {
  return i18n.t(`rightSidebarUi.status${status.charAt(0).toUpperCase()}${status.slice(1)}`);
}

function pauseName(reason?: string): string {
  const keys: Record<string, string> = {
    realtime_message: "pauseRealtime", waiting_approval: "pauseApproval", waiting_input: "pauseInput",
    waiting_resource: "pauseResource", agent_stopping: "pauseStopping", self_paused: "pauseSelf", interrupted: "pauseInterrupted",
  };
  return reason && keys[reason] ? i18n.t(`rightSidebarUi.${keys[reason]}`) : reason || i18n.t("rightSidebarUi.noCurrent");
}

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
  const { t } = useTranslation();
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
      aria-label={t("rightSidebarUi.close")}
      title={`${t("rightSidebarUi.close")} (Ctrl+Shift+B)`}
      onClick={onClose}
    />
    <aside className="agent-right-sidebar" aria-label={t("rightSidebarUi.details")}>
      <header className="agent-right-sidebar-header">
        <div className="agent-right-sidebar-identity">
          <div className="agent-right-sidebar-avatar">{agentName.charAt(0)}</div>
          <div className="agent-right-sidebar-copy">
            <strong>{agentName}</strong>
            <span>
              <i className={connectionStatus === "connected" ? "online" : "offline"} />
              {connectionStatus === "connected" ? t("rightSidebarUi.online") : t("rightSidebarUi.disconnected")}
              {agentState ? ` · ${livingStateName(agentState.living)}` : ""}
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
          }} title={t("rightSidebarUi.refresh")}>
            <Icon name="refresh" size={15} />
          </button>
          <button type="button" onClick={onClose} title={`${t("rightSidebarUi.close")} (Ctrl+Shift+B)`} aria-label={t("rightSidebarUi.close")}>
            <Icon name="sidebar-panel-right" size={15} />
          </button>
        </div>
      </header>
      <nav className="right-sidebar-sections" aria-label={t("rightSidebarUi.sections")}>
        <button type="button" className={section === "activity" ? "active" : ""} aria-current={section === "activity" ? "page" : undefined} onClick={() => onSectionChange("activity")}>
          <Icon name="clock" size={15} />
          <span className="right-sidebar-section-label">{t("rightSidebarUi.activity")}</span>
        </button>
        <button type="button" className={section === "state" ? "active" : ""} aria-current={section === "state" ? "page" : undefined} onClick={() => onSectionChange("state")}>
          <Icon name="sparkles" size={15} />
          <span className="right-sidebar-section-label">{t("rightSidebarUi.state")}</span>
        </button>
        <button type="button" className={section === "project" ? "active" : ""} aria-current={section === "project" ? "page" : undefined} onClick={() => onSectionChange("project")}>
          <Icon name="folder" size={15} />
          <span className="right-sidebar-section-label">{t("rightSidebarUi.project")}</span>
          {currentProject && <span className="right-sidebar-section-count">1</span>}
        </button>
        <button type="button" className={section === "assignment" ? "active" : ""} aria-current={section === "assignment" ? "page" : undefined} onClick={() => onSectionChange("assignment")}>
          <Icon name="robot" size={15} />
          <span className="right-sidebar-section-label">{t("rightSidebarUi.assignment")}</span>
          {activeAssignmentCount > 0 && <span className="right-sidebar-section-count">{activeAssignmentCount}</span>}
        </button>
        <button type="button" className={section === "artifact" ? "active" : ""} aria-current={section === "artifact" ? "page" : undefined} onClick={() => onSectionChange("artifact")}>
          <Icon name="folder" size={15} />
          <span className="right-sidebar-section-label">{t("rightSidebarUi.artifact")}</span>
          {artifacts.length > 0 && <span className="right-sidebar-section-count">{artifacts.length}</span>}
        </button>
        <button type="button" className={section === "memory" ? "active" : ""} aria-current={section === "memory" ? "page" : undefined} onClick={() => onSectionChange("memory")}>
          <Icon name="info" size={15} />
          <span className="right-sidebar-section-label">{t("rightSidebarUi.memory")}</span>
          {memories.length > 0 && <span className="right-sidebar-section-count">{memories.length}{memoryList.hasMore ? "+" : ""}</span>}
        </button>
        <button type="button" className={section === "context" ? "active" : ""} aria-current={section === "context" ? "page" : undefined} onClick={() => onSectionChange("context")}>
          <Icon name="file-text" size={15} />
          <span className="right-sidebar-section-label">{t("rightSidebarUi.context")}</span>
        </button>
      </nav>
      {section === "activity" ? <>
        <div className="activity-view-tabs">
        <button className={view === "current" ? "active" : ""} onClick={() => setView("current")}>
          {t("rightSidebarUi.current")}
          <span>{activities.filter((item) => ACTIVE.has(item.status)).length}</span>
        </button>
        <button className={view === "history" ? "active" : ""} onClick={() => setView("history")}>
          {t("rightSidebarUi.history")}
        </button>
      </div>
      <div className="activity-sidebar-body">
        <nav className="activity-list">
              {loading && visible.length === 0 && <p className="activity-empty">{t("rightSidebarUi.loading")}</p>}
          {error && <p className="activity-error">{error}</p>}
          {!loading && !error && visible.length === 0 && (
            <div className="activity-empty-state">
              <span className="activity-empty-orbit" />
              <strong>{view === "current" ? t("rightSidebarUi.noCurrent") : t("rightSidebarUi.noHistory")}</strong>
              <p>{view === "current" ? t("rightSidebarUi.currentHint") : t("rightSidebarUi.historyHint")}</p>
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
                <small>{activity.progressSummary || statusName(activity.status)}</small>
              </span>
              <span className={`activity-status-pill ${activity.status}`}>
                {statusName(activity.status)}
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
  const { t } = useTranslation();
  const recentMemories = [...memories].sort((left, right) => (
    right.createdAt - left.createdAt
  ));
  return (
    <section className="person-memory-panel">
      {focusedMemories.length > 0 && (
        <div className="focused-memory-section">
          <div className="person-memory-heading">
            <div>
          <strong>{t("rightSidebarUi.memoryReferences")}</strong>
          <p>{t("rightSidebarUi.memoryReferencesHint")}</p>
            </div>
          </div>
          <div className="memory-reference-list">
            {focusedMemories.map((memory, index) => (
              <article key={`${memory.id || "memory"}-${index}`}>
                <strong>{memory.summary}</strong>
                <span>
                  {memory.source ? memorySourceName(memory.source) : t("rightSidebarUi.longTermMemory")}
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
          <strong>{t("rightSidebarUi.recentMemory")}</strong>
          <p>{t("rightSidebarUi.recentMemoryHint")}</p>
        </div>
        <button type="button" onClick={onRefresh} disabled={page.loading || page.loadingMore}>
          {t("rightSidebarUi.refresh")}
        </button>
      </div>
      {page.loading && memories.length === 0 && <p className="activity-empty">{t("rightSidebarUi.loading")}</p>}
      {page.error && <p className="activity-error">{page.error}</p>}
      {!page.loading && !page.error && recentMemories.length === 0 && (
        <div className="activity-empty-state">
          <strong>{t("rightSidebarUi.noRecentMemory")}</strong>
          <p>{t("rightSidebarUi.recentMemoryEmpty")}</p>
        </div>
      )}
      <div className="person-memory-list">
        {recentMemories.map((memory) => (
          <article key={memory.id}>
            <strong>{memory.summary}</strong>
            <div className="person-memory-meta">
              <span>
                {memory.memoryLayer === "short_term"
                  ? t("rightSidebarUi.shortTermMemory")
                  : t("rightSidebarUi.longTermMemoryLabel")}
                {` / ${memorySourceName(memory.source)}`}
              </span>
              {memory.createdAt > 0 && (
                <time>{new Date(memory.createdAt * 1000).toLocaleString()}</time>
              )}
            </div>
            {memory.tags.length > 0 && (
              <div className="person-memory-tags">
                {memory.tags.map((tag) => <span key={tag}>#{tag}</span>)}
              </div>
            )}
            {memory.memoryLayer === "short_term" && (
              <small>{t("rightSidebarUi.shortTermMemoryStrength", { count: memory.reinforcementCount })}</small>
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
          {page.loadingMore ? t("rightSidebarUi.loading") : t("sidebar.loadMoreSessions")}
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
  const { t } = useTranslation();
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
      if (!result.ok) setActionError(result.error || t("projectUi.openArtifactFailed"));
    } finally {
      setOpeningKey("");
    }
  };
  return (
    <section className="artifact-sidebar-panel">
      <div className="artifact-sidebar-toolbar">
        <div className="artifact-scope-tabs">
          <button type="button" className={scope === "current" ? "active" : ""} onClick={() => setScope("current")}>
            {t("rightSidebarUi.currentConversation")}
          </button>
          <button type="button" className={scope === "all" ? "active" : ""} onClick={() => setScope("all")}>
            {t("rightSidebarUi.all")}
          </button>
        </div>
        <button type="button" onClick={onRefresh}>{t("rightSidebarUi.refresh")}</button>
      </div>
      {loading && visible.length === 0 && <p className="activity-empty">{t("rightSidebarUi.loading")}</p>}
      {error && <p className="activity-error">{error}</p>}
      {actionError && <p className="activity-error">{actionError}</p>}
      {!loading && !error && visible.length === 0 && (
        <div className="activity-empty-state">
          <strong>{scope === "current" ? t("rightSidebarUi.artifactsCurrentEmpty") : t("rightSidebarUi.artifactsEmpty")}</strong>
          <p>{t("rightSidebarUi.artifactsHint")}</p>
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
              title={`${previewable ? t("common.preview") : t("common.open")} ${artifact.name}`}
            >
              <span className={`artifact-kind-icon ${artifact.kind}`}>
                <Icon name={artifact.kind === "image" ? "sparkles" : "file-text"} size={17} />
              </span>
              <span>
                <strong>{artifact.name}</strong>
                <small>{formatBytes(artifact.size)} · {new Date(artifact.updatedAt * 1000).toLocaleString()}</small>
                {artifact.description && <em>{artifact.description}</em>}
              </span>
              <i>{openingKey === key ? t("home.opening") : previewable ? t("common.preview") : t("common.open")}</i>
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
  const { t } = useTranslation();
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
      <ContextBlock title={t("rightSidebarUi.memoryReferences")}>
        {focusedMemories.length > 0 ? (
          <div className="memory-reference-list">
            <p>{t("rightSidebarUi.recalledHint")}</p>
            {focusedMemories.map((memory, index) => (
              <article key={`${memory.id || "memory"}-${index}`}>
                <strong>{memory.summary}</strong>
                <span>
                  {memory.source ? memorySourceName(memory.source) : t("rightSidebarUi.longTermMemory")}
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
            <strong>{t("rightSidebarUi.clickMemoryHint")}</strong>
            <span>{t("rightSidebarUi.memorySummaryHint")}</span>
          </>
        )}
      </ContextBlock>
      <ContextBlock title={t("rightSidebarUi.currentAgent")}>
        <strong>{agentName}</strong>
        <span>
          {connectionStatus === "connected" ? t("rightSidebarUi.statusOnline") : t("rightSidebarUi.statusNoConnection")}
          {agentState ? ` · ${livingStateName(agentState.living)}` : ""}
        </span>
        {agentState?.focusSummary && <span>{agentState.focusSummary}</span>}
        {agentState && agentState.livingSince > 0 && (
          <span>{t("rightSidebarUi.duration", { value: formatDuration(Date.now() / 1000 - agentState.livingSince) })}</span>
        )}
      </ContextBlock>
      <ContextBlock title={t("rightSidebarUi.intent")}>
        <strong>{agentState?.lastIntent
          ? intentTypeName(agentState.lastIntent.type)
          : t("rightSidebarUi.noIntent")}</strong>
        {agentState?.lastIntent?.summary && <span>{agentState.lastIntent.summary}</span>}
        {agentState?.lastIntent?.decidedAt ? (
          <span>{new Date(agentState.lastIntent.decidedAt * 1000).toLocaleString()}</span>
        ) : null}
      </ContextBlock>
      <ContextBlock title={t("rightSidebarUi.session")}>
        <strong>{sessionId || t("rightSidebarUi.notSelected")}</strong>
        {personId && <span>{t("rightSidebarUi.person", { value: personId })}</span>}
      </ContextBlock>
      <ContextBlock title={t("rightSidebarUi.happening")}>
        <strong>{active.length > 0 ? t("rightSidebarUi.activeCount", { count: active.length }) : t("rightSidebarUi.noBackground")}</strong>
        {active.slice(0, 3).map((item) => <span key={item.id}>{item.title} · {statusName(item.status)}</span>)}
      </ContextBlock>
      <ContextBlock title={t("rightSidebarUi.goal")}>
        <strong>{goal?.title || t("rightSidebarUi.noGoal")}</strong>
        {goal?.progressSummary && <span>{goal.progressSummary}</span>}
      </ContextBlock>
      <ContextBlock title={t("rightSidebarUi.memoryWork")}>
        <strong>{recentMemory ? recentMemory.title : t("rightSidebarUi.noMemoryWork")}</strong>
        {recentMemory?.progressSummary && <span>{recentMemory.progressSummary}</span>}
      </ContextBlock>
      <ContextBlock title={t("rightSidebarUi.artifact")}>
        <strong>{t("rightSidebarUi.artifactCount", { count: artifacts.length })}</strong>
        <span>{t("rightSidebarUi.authorizedHint")}</span>
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
  const { t } = useTranslation();
  const internal = agentState?.internal;
  const relationship = agentState?.relationship;

  return (
    <section className="agent-status-panel">
      <div className="agent-status-panel-heading">
        <div>
          <strong>{t("rightSidebarUi.stateTitle", { name: agentName })}</strong>
          <span>{t("rightSidebarUi.stateHint")}</span>
        </div>
        <button type="button" onClick={onRefresh}>{t("rightSidebarUi.refresh")}</button>
      </div>

      <StateCard title={t("rightSidebarUi.currentState")} accent={speaking ? "speaking" : agentState?.living || "idle"}>
        <div className="agent-current-state">
          <span className={`agent-current-state-dot ${speaking ? "speaking" : agentState?.living || "idle"}`} />
          <div>
            <strong>
              {connectionStatus === "connected"
                ? speaking
                  ? t("rightSidebarUi.statusSpeaking")
                  : agentState
                    ? livingStateName(agentState.living)
                    : t("rightSidebarUi.statusOnline")
                : t("rightSidebarUi.statusNoConnection")}
            </strong>
            {agentState?.focusSummary && <p>{agentState.focusSummary}</p>}
            {agentState?.livingSince ? (
              <small>{t("rightSidebarUi.duration", { value: formatDuration(Date.now() / 1000 - agentState.livingSince) })}</small>
            ) : null}
          </div>
        </div>
      </StateCard>

      <StateCard title={relationship ? t("rightSidebarUi.relationshipWith", { name: relationship.displayName }) : t("rightSidebarUi.relationship")}>
        {relationship ? (
          <>
            <div className="relationship-summary">
              <strong>{relationship.relationType} · {relationship.status}</strong>
              <span>{relationship.description}</span>
            </div>
            <StateMetricList metrics={[
              {
                key: "depth",
                label: t("rightSidebarUi.familiarity"),
                value: relationship.depth,
                description: relationship.depthDescription,
              },
              {
                key: "trust",
                label: t("rightSidebarUi.trust"),
                value: relationship.trust,
                description: relationship.trustDescription,
              },
              {
                key: "closeness",
                label: t("rightSidebarUi.closeness"),
                value: relationship.closeness,
                description: relationship.closenessDescription,
              },
            ]} compact />
            <small className="relationship-interactions">
              {t("rightSidebarUi.interactionCount", { count: relationship.interactionCount })}
              {relationship.lastInteractionAt
                ? ` · ${t("rightSidebarUi.lastInteraction", { value: new Date(relationship.lastInteractionAt * 1000).toLocaleString() })}`
                : ""}
            </small>
          </>
        ) : (
          <p className="state-empty-copy">{t("rightSidebarUi.stateNoRelationship")}</p>
        )}
      </StateCard>

      {internal ? (
        <>
          <StateCard title={t("rightSidebarUi.mood")}>
            <div className="mood-summary">
              <strong>{internal.moodSummary || t("rightSidebarUi.statusCalm")}</strong>
              <span>{t("rightSidebarUi.energy", { value: formatPercent(internal.energy) })} · {internal.energyDescription}</span>
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
              <p className="state-empty-copy">{t("rightSidebarUi.noActiveEmotion")}</p>
            )}
          </StateCard>

          <StateCard title={t("rightSidebarUi.body")}>
            <p className="state-natural-language">{internal.somatic}</p>
          </StateCard>

          <StateCard title={t("rightSidebarUi.drives")}>
            <StateMetricList metrics={internal.desires} />
          </StateCard>

          <StateCard title={t("rightSidebarUi.hormones")}>
            <StateMetricList metrics={internal.hormones} />
          </StateCard>

          <StateCard title={t("rightSidebarUi.contradictions")}>
            {internal.contradictions.length > 0 ? (
              <div className="state-tension-list">
                {internal.contradictions.map((item) => <p key={item}>{item}</p>)}
              </div>
            ) : (
              <p className="state-empty-copy">{t("rightSidebarUi.noContradictions")}</p>
            )}
          </StateCard>

          <StateCard title={t("rightSidebarUi.tendencies")}>
            {internal.impulse && <p className="state-natural-language">{internal.impulse}</p>}
            {internal.behaviorTendencies.length > 0 && (
              <ul className="behavior-tendency-list">
                {internal.behaviorTendencies.map((item) => <li key={item}>{item}</li>)}
              </ul>
            )}
            {!internal.impulse && internal.behaviorTendencies.length === 0 && (
              <p className="state-empty-copy">{t("rightSidebarUi.noTendencies")}</p>
            )}
          </StateCard>

          <details className="raw-state-details">
            <summary>{t("rightSidebarUi.rawState")}</summary>
            {relationship?.rawContext && (
              <>
                <h4>{t("rightSidebarUi.relationshipContext")}</h4>
                <pre>{relationship.rawContext}</pre>
              </>
            )}
            <h4>{t("rightSidebarUi.bodyContext")}</h4>
            <pre>{internal.rawContext}</pre>
          </details>

          {internal.observedAt > 0 && (
            <time className="agent-state-observed-at">
              {t("rightSidebarUi.recentUpdate", { value: new Date(internal.observedAt * 1000).toLocaleString() })}
            </time>
          )}
        </>
      ) : (
        <div className="activity-empty-state">
          <strong>{t("rightSidebarUi.stateUnavailableTitle")}</strong>
          <p>{t("rightSidebarUi.stateUnavailableCopy")}</p>
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
  const key = `rightSidebarUi.memorySource${value.replace(/(^|_)([a-z])/g, (_, __, char) => char.toUpperCase())}`;
  return i18n.t(key, { defaultValue: value });
}

function ActivityDetail({ activity }: { activity: ActivitySnapshot }) {
  const { t } = useTranslation();
  const hasProgress = activity.totalSteps !== null && activity.totalSteps > 0;
  const percent = hasProgress && activity.completedSteps !== null
    ? Math.round((activity.completedSteps / activity.totalSteps!) * 100)
    : null;
  return (
    <section className="activity-detail">
      <div className="activity-detail-heading">
        <span>{categoryName(activity.category)}</span>
        <time>{formatTime(activity.updatedAt)}</time>
        <h2>{activity.title}</h2>
        <p>{activity.progressSummary || activity.resultSummary || statusName(activity.status)}</p>
      </div>
      {percent !== null && (
        <div className="activity-detail-progress">
          <div><span style={{ width: `${percent}%` }} /></div>
          <small>{activity.completedSteps}/{activity.totalSteps} · {percent}%</small>
        </div>
      )}
      {activity.status === "paused" && (
        <div className="activity-pause-reason">
          {pauseName(activity.pauseReason)}
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
        {activity.currentStep && <><dt>{t("rightSidebarUi.currentStage")}</dt><dd>{activity.currentStep}</dd></>}
        <dt>{t("rightSidebarUi.activityType")}</dt><dd>{activity.kind}</dd>
        {activity.originSessionId && <><dt>{t("rightSidebarUi.sourceSession")}</dt><dd>{activity.originSessionId}</dd></>}
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

function livingStateName(state: string): string {
  const keys: Record<string, string> = {
    dormant: "livingDormant", waking: "livingWaking", awake: "livingAwake", idle: "livingIdle",
    working: "livingWorking", sleeping: "livingSleeping", dreaming: "livingDreaming",
  };
  return keys[state] ? i18n.t(`rightSidebarUi.${keys[state]}`) : state;
}

function formatPercent(value: number): string {
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

function intentTypeName(value: string): string {
  const key = `rightSidebarUi.intent${value.charAt(0).toUpperCase()}${value.slice(1).toLowerCase()}`;
  return value ? i18n.t(key, { defaultValue: value }) : i18n.t("rightSidebarUi.unknownIntent");
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return i18n.t("rightSidebarUi.lessThanMinute");
  if (seconds < 3600) return i18n.t("rightSidebarUi.minutes", { count: Math.floor(seconds / 60) });
  if (seconds < 86400) return i18n.t("rightSidebarUi.hours", { count: Math.floor(seconds / 3600) });
  return i18n.t("rightSidebarUi.days", { count: Math.floor(seconds / 86400) });
}

function activityStatusForAssignment(status: AssignmentSnapshot["status"]): ActivitySnapshot["status"] {
  if (status === "completed") return "completed";
  if (status === "failed") return "failed";
  if (status === "cancelled" || status === "declined") return "cancelled";
  if (status === "paused" || status === "waiting_person") return "paused";
  if (status === "in_progress") return "running";
  return "queued";
}
