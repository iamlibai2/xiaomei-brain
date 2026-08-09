import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useCoreStore } from "../../store";
import { Icon } from "../ui";
import "./workspaces.css";

type WorkspaceComponent = {
  id: string;
  type: "metric" | "text" | "table" | "record" | "bar_chart" | "line_chart" | "pie_chart" | "timeline" | "asset" | "group";
  title?: string;
  value?: unknown;
  detail?: string;
  unit?: string;
  content?: string;
  columns?: Array<string | { key?: string; label?: string }>;
  rows?: Array<Record<string, unknown>>;
  data?: Array<{ label?: string; value?: number; name?: string }>;
  items?: Array<{ time?: unknown; title?: unknown; detail?: unknown }>;
  components?: WorkspaceComponent[];
  asset?: BusinessAsset;
  binding_error?: string;
  [key: string]: unknown;
};

type BusinessField = { id: string; name: string; label: string; data_type: string };
type BusinessRecord = {
  id: string;
  revision: number;
  values: Record<string, unknown>;
};
type BusinessCollection = {
  id: string;
  name: string;
  label: string;
  fields: BusinessField[];
  records: BusinessRecord[];
};
type BusinessEvent = { id: string; summary: string; occurred_at: number };
type BusinessDataSource = {
  id: string;
  kind: string;
  name: string;
  status: string;
};
type BusinessAsset = {
  id: string;
  nature: "working" | "evidence" | "external";
  name: string;
  kind: string;
  mime_type: string;
  size: number;
  source_type: string;
  source_id: string;
  source_session_id: string;
  metadata: Record<string, unknown>;
  revision: number;
  updated_at: number;
};
type BusinessObservation = {
  id: string;
  content: string;
  status: "unprocessed" | "resolved";
  received_at: number;
  session_id: string;
  turn_id: string;
  resolved_record_ids: string[];
  data_source?: { kind?: string; name?: string } | null;
};
type BusinessActionCandidate = {
  id: string;
  collection_label: string;
  fields: Array<{ id: string; label: string }>;
  occurrence_count: number;
  record_count: number;
  example_intents: string[];
  status: "observed" | "candidate";
};
type BusinessActionDefinition = {
  id: string;
  name: string;
  description: string;
  completion_criteria: string;
  collection_label: string;
  fields: Array<{ id: string; label: string }>;
  evidence_count: number;
  status: "active" | "retired";
};
type BusinessActionRun = {
  id: string;
  action_id: string;
  status: "running" | "completed" | "failed";
  business_intent: string;
  started_at: number;
};
type BusinessSnapshot = {
  summary: Record<string, number>;
  dataSources: BusinessDataSource[];
  assets: BusinessAsset[];
  collections: BusinessCollection[];
  observations: BusinessObservation[];
  events: BusinessEvent[];
  actionCandidates: BusinessActionCandidate[];
  actions: BusinessActionDefinition[];
  actionRuns: BusinessActionRun[];
};

type WorkspaceSurface = {
  id: string;
  name: string;
  status: "temporary" | "persistent";
  isDefault: boolean;
  revision: number;
  updatedAt: number;
  components: WorkspaceComponent[];
};

type WorkspaceSnapshot = {
  id: string;
  name: string;
  description: string;
  revision: number;
  createdAt: number;
  updatedAt: number;
  components: WorkspaceComponent[];
  surfaceId: string;
  surfaceRevision: number;
  surfaces: WorkspaceSurface[];
  business: BusinessSnapshot | null;
};

function surfaceSnapshot(value: Record<string, unknown>): WorkspaceSurface | null {
  if (typeof value.id !== "string") return null;
  const definitionValue = value.resolved_definition || value.definition;
  const definition = definitionValue && typeof definitionValue === "object"
    ? definitionValue as Record<string, unknown>
    : {};
  return {
    id: value.id,
    name: typeof value.name === "string" && value.name ? value.name : "Surface",
    status: value.status === "temporary" ? "temporary" : "persistent",
    isDefault: value.is_default === true,
    revision: typeof value.revision === "number" ? value.revision : 0,
    updatedAt: typeof value.updated_at === "number" ? value.updated_at : 0,
    components: Array.isArray(definition.components)
      ? definition.components.filter((entry): entry is WorkspaceComponent => (
        Boolean(entry) && typeof entry === "object" && typeof (entry as WorkspaceComponent).type === "string"
      ))
      : [],
  };
}

function showSurface(item: WorkspaceSnapshot, surfaceId: string): WorkspaceSnapshot {
  const surface = item.surfaces.find((entry) => entry.id === surfaceId);
  if (!surface) return item;
  return {
    ...item,
    components: surface.components,
    surfaceId: surface.id,
    surfaceRevision: surface.revision,
  };
}

function snapshot(value: unknown, preferredSurfaceId = ""): WorkspaceSnapshot | null {
  if (!value || typeof value !== "object") return null;
  const item = value as Record<string, unknown>;
  const surfaceValues = Array.isArray(item.surfaces)
    ? item.surfaces.filter((entry): entry is Record<string, unknown> => (
      Boolean(entry) && typeof entry === "object"
    ))
    : [];
  const surfaces = surfaceValues
    .map(surfaceSnapshot)
    .filter((entry): entry is WorkspaceSurface => entry !== null);
  const latestTemporary = surfaces
    .filter((entry) => entry.status === "temporary")
    .sort((left, right) => right.updatedAt - left.updatedAt)[0];
  const surface = surfaces.find((entry) => entry.id === preferredSurfaceId)
    || latestTemporary
    || surfaces.find((entry) => entry.isDefault)
    || surfaces[0];
  if (typeof item.id !== "string" || typeof item.name !== "string") return null;
  const businessValue = item.business && typeof item.business === "object"
    ? item.business as Record<string, unknown>
    : null;
  const business: BusinessSnapshot | null = businessValue ? {
    summary: businessValue.summary && typeof businessValue.summary === "object"
      ? businessValue.summary as Record<string, number>
      : {},
    dataSources: Array.isArray(businessValue.data_sources)
      ? businessValue.data_sources as BusinessDataSource[]
      : [],
    assets: Array.isArray(businessValue.assets)
      ? businessValue.assets as BusinessAsset[]
      : [],
    collections: Array.isArray(businessValue.collections)
      ? businessValue.collections as BusinessCollection[]
      : [],
    observations: Array.isArray(businessValue.observations)
      ? businessValue.observations as BusinessObservation[]
      : [],
    events: Array.isArray(businessValue.events)
      ? businessValue.events as BusinessEvent[]
      : [],
    actionCandidates: Array.isArray(businessValue.action_candidates)
      ? businessValue.action_candidates as BusinessActionCandidate[]
      : [],
    actions: Array.isArray(businessValue.actions)
      ? businessValue.actions as BusinessActionDefinition[]
      : [],
    actionRuns: Array.isArray(businessValue.action_runs)
      ? businessValue.action_runs as BusinessActionRun[]
      : [],
  } : null;
  return {
    id: item.id,
    name: item.name,
    description: typeof item.description === "string" ? item.description : "",
    revision: typeof item.revision === "number" ? item.revision : 1,
    createdAt: typeof item.created_at === "number" ? item.created_at : 0,
    updatedAt: typeof item.updated_at === "number" ? item.updated_at : 0,
    components: surface?.components || [],
    surfaceId: surface?.id || "",
    surfaceRevision: surface?.revision || 0,
    surfaces,
    business,
  };
}

export function WorkspacesPage({
  preferredWorkspaceId,
  onBackToChat,
  onEnterConversation,
}: {
  preferredWorkspaceId?: string;
  onBackToChat: () => void;
  onEnterConversation: () => void;
}) {
  const { t, i18n } = useTranslation();
  const activeAgentId = useCoreStore((state) => state.activeAgentId || "");
  const activeSessionId = useCoreStore((state) => (
    state.activeSessionByAgent[state.activeAgentId || ""] || ""
  ));
  const connectionStatus = useCoreStore((state) => (
    state.connectionByAgent[state.activeAgentId || ""]?.status || "disconnected"
  ));
  const [items, setItems] = useState<WorkspaceSnapshot[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(false);
  const [enteringConversation, setEnteringConversation] = useState(false);
  const [error, setError] = useState("");
  const selectedIdRef = useRef("");
  const selectedSurfaceByWorkspaceRef = useRef<Record<string, string>>({});
  const loadSequenceRef = useRef(0);
  const eventRefreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  const enterConversation = useCallback(async () => {
    if (!activeAgentId || !activeSessionId || !selectedId || enteringConversation) return;
    setEnteringConversation(true);
    setError("");
    try {
      const response = await window.gateway.focusWorkspace({
        agentId: activeAgentId,
        workspaceId: selectedId,
        sessionId: activeSessionId,
      });
      if (response.error) throw new Error(response.error.message);
      onEnterConversation();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setEnteringConversation(false);
    }
  }, [
    activeAgentId,
    activeSessionId,
    enteringConversation,
    onEnterConversation,
    selectedId,
  ]);

  const openAsset = useCallback(async (asset: BusinessAsset) => {
    if (!activeAgentId || asset.nature === "external") return;
    setError("");
    try {
      const metadata = asset.metadata || {};
      const contentKind = asset.source_type === "asset_evidence_snapshot"
        ? String(metadata.content_source_kind || "")
        : asset.source_type === "conversation_attachment" ? "attachment" : "artifact";
      const sessionId = asset.source_type === "asset_evidence_snapshot"
        ? String(metadata.content_source_session_id || "")
        : String(metadata.latest_artifact_session_id || asset.source_session_id || "");
      const contentId = asset.source_type === "asset_evidence_snapshot"
        ? String(metadata.content_source_id || "")
        : contentKind === "attachment"
          ? asset.source_id
          : String(metadata.latest_artifact_id || asset.source_id || "");
      if (!sessionId || !contentId || !["attachment", "artifact"].includes(contentKind)) {
        throw new Error(t("preview.notFound"));
      }
      const response = contentKind === "attachment"
        ? await window.gateway.openAttachment({
          agentId: activeAgentId,
          sessionId,
          attachmentId: contentId,
        })
        : await window.gateway.openArtifact({
          agentId: activeAgentId,
          sessionId,
          artifactId: contentId,
        });
      if (!response.ok) throw new Error(response.error || t("preview.openFailed"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [activeAgentId, t]);

  const load = useCallback(async (focusWorkspaceId = "", refreshDetail = false) => {
    const sequence = ++loadSequenceRef.current;
    setLoading(true);
    setError("");
    if (!activeAgentId || connectionStatus !== "connected") {
      // Workspace data is Person-scoped. Never leave the previous Person's
      // canvas visible while the authenticated Gateway connection changes.
      setItems([]);
      setSelectedId("");
      setError(t("workspaceUi.notConnected"));
      setLoading(false);
      return;
    }
    try {
      const response = await window.gateway.listWorkspaces({ agentId: activeAgentId, limit: 100 });
      if (response.error) throw new Error(response.error.message);
      const values = Array.isArray(response.result?.workspaces) ? response.result.workspaces : [];
      let next = values.map(snapshot).filter((entry): entry is WorkspaceSnapshot => entry !== null);
      // IDs retained by the renderer may belong to the account that was active
      // before an identity switch. Only request details for a workspace that
      // the freshly authenticated list has already made visible.
      const requestedIds = [focusWorkspaceId, preferredWorkspaceId, selectedIdRef.current];
      const targetId = requestedIds.find((id) => (
        Boolean(id) && next.some((item) => item.id === id)
      )) || next[0]?.id || "";
      if (refreshDetail && targetId) {
        const detailResponse = await window.gateway.getWorkspace({
          agentId: activeAgentId,
          workspaceId: targetId,
        });
        if (detailResponse.error) throw new Error(detailResponse.error.message);
        const detail = snapshot(
          detailResponse.result?.workspace,
          selectedSurfaceByWorkspaceRef.current[targetId] || "",
        );
        if (detail) {
          const existingIndex = next.findIndex((item) => item.id === detail.id);
          next = existingIndex >= 0
            ? next.map((item) => item.id === detail.id ? detail : item)
            : [detail, ...next];
        }
      }
      // Event-driven and manual refreshes may overlap. Never let an older RPC
      // response replace a newer workspace revision in the visible canvas.
      if (sequence !== loadSequenceRef.current) return;
      setItems(next);
      setSelectedId((current) => (
        targetId && next.some((item) => item.id === targetId)
          ? targetId
          : current && next.some((item) => item.id === current) ? current : next[0]?.id || ""
      ));
    } catch (reason) {
      if (sequence !== loadSequenceRef.current) return;
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      if (sequence === loadSequenceRef.current) setLoading(false);
    }
  }, [activeAgentId, connectionStatus, preferredWorkspaceId, t]);

  useEffect(() => { void load(preferredWorkspaceId, true); }, [load, preferredWorkspaceId]);

  useEffect(() => {
    const clearPersonScopedView = () => {
      ++loadSequenceRef.current;
      selectedIdRef.current = "";
      selectedSurfaceByWorkspaceRef.current = {};
      setItems([]);
      setSelectedId("");
      setError("");
      setLoading(false);
    };
    window.addEventListener("xiaomei:identity-status-changed", clearPersonScopedView);
    window.addEventListener("xiaomei:identity-locked", clearPersonScopedView);
    return () => {
      window.removeEventListener("xiaomei:identity-status-changed", clearPersonScopedView);
      window.removeEventListener("xiaomei:identity-locked", clearPersonScopedView);
    };
  }, []);

  useEffect(() => {
    const dispose = window.gateway.onEvent((event: {
      event?: string; agentId?: string; data?: unknown;
    }) => {
      if (event.agentId !== activeAgentId) return;
      const eventName = typeof event.event === "string" ? event.event : "";
      if (![
        "workspace.created", "workspace.updated", "surface.created", "surface.updated",
        "data_source.created", "observation.created", "collection.created", "collection.updated",
        "record.changed", "business_event.created",
        "business_action.candidate",
        "dataset.created", "dataset.updated",
        "data_import.completed",
        "workspace_asset.created", "workspace_asset.updated",
      ].includes(eventName)) return;
      const data = event.data && typeof event.data === "object"
        ? event.data as Record<string, unknown>
        : {};
      const eventWorkspaceId = String(data.workspace_id || data.id || "");
      if (eventName.startsWith("surface.") && eventWorkspaceId && typeof data.id === "string") {
        selectedSurfaceByWorkspaceRef.current[eventWorkspaceId] = data.id;
      }
      if (eventRefreshTimerRef.current !== null) {
        clearTimeout(eventRefreshTimerRef.current);
      }
      eventRefreshTimerRef.current = setTimeout(() => {
        eventRefreshTimerRef.current = null;
        // A background update must not pull the user into another Workspace.
        // Refresh the currently visible detail; use the event target only when
        // no Workspace has been selected yet.
        void load(selectedIdRef.current || eventWorkspaceId, true);
      }, 120);
    });
    return () => {
      dispose();
      if (eventRefreshTimerRef.current !== null) {
        clearTimeout(eventRefreshTimerRef.current);
        eventRefreshTimerRef.current = null;
      }
    };
  }, [activeAgentId, load]);

  const selected = useMemo(
    () => items.find((item) => item.id === selectedId) || null,
    [items, selectedId],
  );
  const locale = i18n.language.startsWith("zh") ? "zh-CN" : "en-US";

  return (
    <main className="workspaces-page">
      <header className="workspaces-topbar">
        <div>
          <h1>{t("workspaceUi.title")}</h1>
          <p>{t("workspaceUi.subtitle")}</p>
        </div>
        <div className="workspaces-topbar-actions">
          <button
            type="button"
            onClick={() => void load(selectedIdRef.current, true)}
            disabled={loading}
            aria-busy={loading}
          >
            <span className={loading ? "workspace-refresh-icon spinning" : "workspace-refresh-icon"}>
              <Icon name="refresh" size={15} />
            </span>
            {loading ? t("workspaceUi.refreshing") : t("workspaceUi.refresh")}
          </button>
          <button type="button" onClick={onBackToChat}>
            <Icon name="chevron-left" size={15} />
            {t("workspaceUi.backToChat")}
          </button>
        </div>
      </header>

      <div className="workspaces-body">
        <aside className="workspace-list-panel">
          <div className="workspace-list-heading">
            <span>{t("workspaceUi.saved")}</span>
            <strong>{items.length}</strong>
          </div>
          {items.map((item) => (
            <button
              type="button"
              key={item.id}
              className={`workspace-list-item ${item.id === selectedId ? "active" : ""}`}
              onClick={() => {
                setSelectedId(item.id);
                void load(item.id, true);
              }}
            >
              <span className="workspace-list-icon"><Icon name="chart-bar" size={17} /></span>
              <span className="workspace-list-copy">
                <strong>{item.name}</strong>
                <small>{new Date(item.updatedAt * 1000).toLocaleString(locale, { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}</small>
              </span>
            </button>
          ))}
          {!loading && !error && items.length === 0 && (
            <div className="workspace-list-empty">{t("workspaceUi.emptyList")}</div>
          )}
        </aside>

        <section className="workspace-canvas-wrap">
          {loading && items.length === 0 && <WorkspaceEmpty text={t("workspaceUi.loading")} />}
          {error && <WorkspaceEmpty text={error} error />}
          {!loading && !error && !selected && (
            <WorkspaceEmpty text={t("workspaceUi.emptyHint")} />
          )}
          {selected && (
            <div className="workspace-canvas">
              <header className="workspace-heading">
                <div>
                  <span className="workspace-eyebrow">WORKSPACE</span>
                  <h2>{selected.name}</h2>
                  {selected.description && <p>{selected.description}</p>}
                </div>
                <span className="workspace-revision">R{selected.revision}</span>
              </header>
              {selected.surfaces.length > 1 && (
                <nav className="workspace-surface-switcher" aria-label="Surface">
                  {selected.surfaces.map((surface) => (
                    <button
                      key={surface.id}
                      type="button"
                      className={surface.id === selected.surfaceId ? "active" : ""}
                      onClick={() => {
                        selectedSurfaceByWorkspaceRef.current[selected.id] = surface.id;
                        setItems((current) => current.map((item) => (
                          item.id === selected.id ? showSurface(item, surface.id) : item
                        )));
                      }}
                    >
                      {surface.name}
                      {surface.status === "temporary" && <span aria-hidden="true">●</span>}
                    </button>
                  ))}
                </nav>
              )}
              <div className="workspace-component-grid">
                {selected.components.map((component) => (
                  <WorkspaceComponentCard
                    key={component.id}
                    component={component}
                    onOpenAsset={openAsset}
                  />
                ))}
              </div>
              {selected.business && (
                <WorkspaceBusinessFacts
                  business={selected.business}
                  locale={locale}
                  onOpenAsset={openAsset}
                />
              )}
              <footer className="workspace-conversation-hint">
                <Icon name="sparkles" size={15} />
                <span>{t("workspaceUi.modifyHint", { name: selected.name })}</span>
                <button
                  type="button"
                  onClick={() => { void enterConversation(); }}
                  disabled={!activeSessionId || enteringConversation}
                >
                  {enteringConversation
                    ? `${t("workspaceUi.openConversation")}…`
                    : t("workspaceUi.openConversation")}
                </button>
              </footer>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

function WorkspaceBusinessFacts({
  business,
  locale,
  onOpenAsset,
}: {
  business: BusinessSnapshot;
  locale: string;
  onOpenAsset: (asset: BusinessAsset) => void;
}) {
  const { t } = useTranslation();
  if (
    !business.collections.length
    && !business.events.length
    && !business.observations.length
    && !business.dataSources.length
    && !business.assets.length
    && !business.actions.length
    && !business.actionCandidates.length
  ) return null;
  return (
    <section className="workspace-business-world">
      <header>
        <div>
          <span className="workspace-eyebrow">BUSINESS WORLD</span>
          <h3>{t("workspaceUi.businessFacts")}</h3>
        </div>
        <div className="workspace-fact-counts">
          <span>{t("workspaceUi.collectionsCount", { count: business.summary.collections || 0 })}</span>
          <span>{t("workspaceUi.recordsCount", { count: business.summary.records || 0 })}</span>
          <span>{t("workspaceUi.eventsCount", { count: business.summary.events || 0 })}</span>
          <span>{t("workspaceUi.pendingObservations", { count: business.summary.unprocessed_observations || 0 })}</span>
          <span>{t("workspaceUi.sourcesCount", { count: business.dataSources.length })}</span>
          <span>{t("workspaceUi.assetsCount", { count: business.assets.length })}</span>
        </div>
      </header>
      {business.collections.map((collection) => (
        <article className="workspace-fact-collection" key={collection.id}>
          <h4>{collection.label || collection.name}</h4>
          <div className="workspace-table-scroll">
            <table>
              <thead>
                <tr>{collection.fields.map((field) => <th key={field.id}>{field.label}</th>)}</tr>
              </thead>
              <tbody>
                {(collection.records || []).map((record) => (
                  <tr key={record.id}>
                    {collection.fields.map((field) => (
                      <td key={field.id}>{formatBusinessValue(record.values?.[field.name], locale)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {!collection.records?.length && (
              <p className="workspace-fact-empty">{t("workspaceUi.noRecords")}</p>
            )}
          </div>
        </article>
      ))}
      {business.observations.length > 0 && (
        <article className="workspace-evidence-list">
          <h4>{t("workspaceUi.businessEvidence")}</h4>
          {business.observations.slice(0, 8).map((observation) => (
            <div key={observation.id} title={[observation.session_id, observation.turn_id].filter(Boolean).join(" / ")}>
              <span className={`workspace-evidence-status ${observation.status}`}>
                {t(`workspaceUi.observationStatus_${observation.status}`)}
              </span>
              <span className="workspace-evidence-copy">
                <strong>{observation.content}</strong>
                <small>{observation.data_source?.kind === "conversation"
                  ? t("workspaceUi.conversationSource")
                  : observation.data_source?.name || t("workspaceUi.unknownSource")}</small>
              </span>
              <time>{new Date(observation.received_at * 1000).toLocaleString(locale)}</time>
            </div>
          ))}
        </article>
      )}
      {(business.dataSources.length > 0 || business.assets.length > 0) && (
        <article className="workspace-resource-list">
          <header>
            <h4>{t("workspaceUi.businessResources")}</h4>
            <div className="workspace-source-strip">
              {business.dataSources.map((source) => (
                <span key={source.id}>{source.name}</span>
              ))}
            </div>
          </header>
          {business.assets.slice(0, 12).map((asset) => {
            const canOpen = asset.nature !== "external";
            return (
              <button
                type="button"
                key={asset.id}
                className="workspace-resource-item"
                disabled={!canOpen}
                onClick={() => canOpen && onOpenAsset(asset)}
                title={canOpen ? t("preview.openExternal") : asset.name}
              >
                <span className={`workspace-asset-nature ${asset.nature}`}>
                  {t(`workspaceUi.assetNature_${asset.nature}`)}
                </span>
                <span className="workspace-resource-copy">
                  <strong>{asset.name}</strong>
                  <small>{asset.mime_type || asset.kind}</small>
                </span>
                <span className="workspace-resource-meta">
                  {asset.size > 0 && <small>{formatFileSize(asset.size)}</small>}
                  <time>{new Date(asset.updated_at * 1000).toLocaleString(locale)}</time>
                </span>
                {canOpen && <Icon name="external-link" size={14} />}
              </button>
            );
          })}
        </article>
      )}
      {business.actions.length > 0 && (
        <article className="workspace-action-candidates workspace-established-actions">
          <h4>{t("workspaceUi.establishedPractices")}</h4>
          {business.actions.map((action) => {
            const lastRun = business.actionRuns.find((run) => run.action_id === action.id);
            return (
              <div key={action.id}>
                <span className="workspace-action-status active">
                  {t("workspaceUi.actionStatus_active")}
                </span>
                <span className="workspace-action-copy">
                  <strong>{action.name}</strong>
                  <small>{action.description || action.completion_criteria}</small>
                </span>
                <span className="workspace-action-count">
                  {lastRun
                    ? t(`workspaceUi.actionRun_${lastRun.status}`)
                    : t("workspaceUi.evidenceCount", { count: action.evidence_count })}
                </span>
              </div>
            );
          })}
        </article>
      )}
      {business.actionCandidates.length > 0 && (
        <article className="workspace-action-candidates">
          <h4>{t("workspaceUi.emergingPractices")}</h4>
          {business.actionCandidates.map((candidate) => {
            const fieldNames = candidate.fields.map((field) => field.label).join("、");
            return (
              <div key={candidate.id}>
                <span className={`workspace-action-status ${candidate.status}`}>
                  {t(`workspaceUi.actionStatus_${candidate.status}`)}
                </span>
                <span className="workspace-action-copy">
                  <strong>{t("workspaceUi.repeatedlyUpdates", {
                    collection: candidate.collection_label,
                    fields: fieldNames || t("workspaceUi.businessFields"),
                  })}</strong>
                  <small>{candidate.example_intents[0] || ""}</small>
                </span>
                <span className="workspace-action-count">
                  {t("workspaceUi.observedTurns", { count: candidate.occurrence_count })}
                </span>
              </div>
            );
          })}
        </article>
      )}
      {business.events.length > 0 && (
        <article className="workspace-event-list">
          <h4>{t("workspaceUi.recentEvents")}</h4>
          {business.events.slice(0, 12).map((event) => (
            <div key={event.id}>
              <i />
              <span>{event.summary}</span>
              <time>{new Date(event.occurred_at * 1000).toLocaleString(locale)}</time>
            </div>
          ))}
        </article>
      )}
    </section>
  );
}

function formatBusinessValue(value: unknown, locale: string) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "✓" : "—";
  if (typeof value === "number") return value.toLocaleString(locale);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function formatFileSize(size: number) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function WorkspaceEmpty({ text, error = false }: { text: string; error?: boolean }) {
  return (
    <div className={`workspace-empty ${error ? "error" : ""}`}>
      <span><Icon name={error ? "info" : "chart-bar"} size={22} /></span>
      <p>{text}</p>
    </div>
  );
}

function WorkspaceComponentCard({
  component,
  onOpenAsset,
}: {
  component: WorkspaceComponent;
  onOpenAsset: (asset: BusinessAsset) => void;
}) {
  if (component.binding_error) {
    return (
      <article className="workspace-component workspace-component-error">
        {component.title && <h3>{component.title}</h3>}
        <p>{component.binding_error}</p>
      </article>
    );
  }
  if (component.type === "metric") {
    return (
      <article className="workspace-component workspace-metric">
        <span>{component.title}</span>
        <strong>{String(component.value ?? "—")}{component.unit || ""}</strong>
        {component.detail && <small>{component.detail}</small>}
      </article>
    );
  }
  if (component.type === "text") {
    return (
      <article className="workspace-component workspace-text">
        {component.title && <h3>{component.title}</h3>}
        <p>{component.content || String(component.value || "")}</p>
      </article>
    );
  }
  if (component.type === "table") return <WorkspaceTable component={component} />;
  if (component.type === "record") return <WorkspaceRecord component={component} />;
  if (component.type === "timeline") return <WorkspaceTimeline component={component} />;
  if (component.type === "asset") {
    return <WorkspaceAssetCard component={component} onOpenAsset={onOpenAsset} />;
  }
  if (component.type === "group") {
    return (
      <section className="workspace-component workspace-component-group">
        {component.title && <h3>{component.title}</h3>}
        <div className="workspace-component-grid workspace-nested-grid">
          {(component.components || []).map((child) => (
            <WorkspaceComponentCard
              key={child.id}
              component={child}
              onOpenAsset={onOpenAsset}
            />
          ))}
        </div>
      </section>
    );
  }
  return <WorkspaceChart component={component} />;
}

function normalizedColumns(component: WorkspaceComponent) {
  const rows = Array.isArray(component.rows) ? component.rows : [];
  return Array.isArray(component.columns) && component.columns.length
    ? component.columns.map((column) => typeof column === "string"
      ? { key: column, label: column }
      : { key: String(column.key || column.label || ""), label: String(column.label || column.key || "") })
    : Object.keys(rows[0] || {}).map((key) => ({ key, label: key }));
}

function WorkspaceTable({ component }: { component: WorkspaceComponent }) {
  const rows = Array.isArray(component.rows) ? component.rows : [];
  const columns = normalizedColumns(component);
  return (
    <article className="workspace-component workspace-table-card">
      {component.title && <h3>{component.title}</h3>}
      <div className="workspace-table-scroll">
        <table>
          <thead><tr>{columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead>
          <tbody>
            {rows.slice(0, 200).map((row, index) => (
              <tr key={index}>{columns.map((column) => <td key={column.key}>{String(row[column.key] ?? "")}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}

function WorkspaceRecord({ component }: { component: WorkspaceComponent }) {
  const rows = Array.isArray(component.rows) ? component.rows : [];
  const columns = normalizedColumns(component);
  return (
    <article className="workspace-component workspace-record-card">
      {component.title && <h3>{component.title}</h3>}
      <div className="workspace-record-list">
        {rows.slice(0, 12).map((row, index) => (
          <dl key={index}>
            {columns.map((column) => (
              <div key={column.key}>
                <dt>{column.label}</dt>
                <dd>{String(row[column.key] ?? "—")}</dd>
              </div>
            ))}
          </dl>
        ))}
      </div>
    </article>
  );
}

function WorkspaceTimeline({ component }: { component: WorkspaceComponent }) {
  const items = Array.isArray(component.items) ? component.items : [];
  return (
    <article className="workspace-component workspace-timeline-card">
      {component.title && <h3>{component.title}</h3>}
      <ol>
        {items.slice(0, 50).map((item, index) => (
          <li key={index}>
            <time>{String(item.time ?? "")}</time>
            <span>
              <strong>{String(item.title ?? "")}</strong>
              {item.detail !== undefined && <small>{String(item.detail)}</small>}
            </span>
          </li>
        ))}
      </ol>
    </article>
  );
}

function WorkspaceAssetCard({
  component,
  onOpenAsset,
}: {
  component: WorkspaceComponent;
  onOpenAsset: (asset: BusinessAsset) => void;
}) {
  const { t } = useTranslation();
  const asset = component.asset;
  if (!asset) return null;
  const canOpen = asset.nature !== "external";
  return (
    <button
      type="button"
      className="workspace-component workspace-surface-asset"
      disabled={!canOpen}
      onClick={() => canOpen && onOpenAsset(asset)}
    >
      <span className={`workspace-asset-nature ${asset.nature}`}>
        {t(`workspaceUi.assetNature_${asset.nature}`)}
      </span>
      <span>
        <strong>{component.title || asset.name}</strong>
        <small>{asset.mime_type || asset.kind}</small>
      </span>
      {canOpen && <Icon name="external-link" size={15} />}
    </button>
  );
}

function WorkspaceChart({ component }: { component: WorkspaceComponent }) {
  const data = (Array.isArray(component.data) ? component.data : [])
    .map((item) => ({
      label: String(item.label || item.name || ""),
      value: Number(item.value || 0),
    }));
  const max = Math.max(1, ...data.map((item) => Math.abs(item.value)));
  if (component.type === "pie_chart") {
    const total = data.reduce((sum, item) => sum + Math.max(0, item.value), 0) || 1;
    let offset = 0;
    const colors = ["#4f7cff", "#50b39a", "#f2b84b", "#e57676", "#9879d8", "#69a9d5"];
    const gradient = data.map((item, index) => {
      const start = offset;
      offset += Math.max(0, item.value) / total * 360;
      return `${colors[index % colors.length]} ${start}deg ${offset}deg`;
    }).join(", ");
    return (
      <article className="workspace-component workspace-chart-card">
        {component.title && <h3>{component.title}</h3>}
        <div className="workspace-pie-layout">
          <div className="workspace-pie" style={{ background: `conic-gradient(${gradient})` }} />
          <div className="workspace-chart-legend">
            {data.map((item, index) => (
              <span key={`${item.label}-${index}`}><i style={{ background: colors[index % colors.length] }} />{item.label}<strong>{item.value}</strong></span>
            ))}
          </div>
        </div>
      </article>
    );
  }
  return (
    <article className="workspace-component workspace-chart-card">
      {component.title && <h3>{component.title}</h3>}
      <div className={`workspace-bars ${component.type === "line_chart" ? "line-like" : ""}`}>
        {data.map((item, index) => (
          <div className="workspace-bar-column" key={`${item.label}-${index}`}>
            <span>{item.value}</span>
            <i style={{ height: `${Math.max(4, Math.abs(item.value) / max * 100)}%` }} />
            <small>{item.label}</small>
          </div>
        ))}
      </div>
    </article>
  );
}
