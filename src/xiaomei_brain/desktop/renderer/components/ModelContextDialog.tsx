import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useCoreStore } from "../store";
import type { ModelTraceRecord, ModelTraceSummary } from "../types";
import { formatTokens } from "../usage";
import { Icon } from "./ui";

type ViewMode = "structured" | "raw";

export function ModelContextDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const activeAgentId = useCoreStore((state) => state.activeAgentId || "");
  const activeAgent = useCoreStore((state) => state.agents.find((item) => item.id === state.activeAgentId));
  const activeSessionId = useCoreStore((state) => state.activeSessionByAgent[state.activeAgentId || ""] || "");
  const [records, setRecords] = useState<ModelTraceSummary[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [selected, setSelected] = useState<ModelTraceRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [sessionOnly, setSessionOnly] = useState(false);
  const [category, setCategory] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("structured");

  const refresh = useCallback(async () => {
    if (!activeAgentId) return;
    setLoading(true);
    const response = await window.gateway.listModelTraces({
      agentId: activeAgentId,
      sessionId: sessionOnly ? activeSessionId : "",
      category,
      limit: 200,
    });
    if (response.error) {
      setError(response.error.message || t("modelTrace.loadFailed"));
    } else {
      const items = (response.result?.items || []) as ModelTraceSummary[];
      setRecords(items);
      setError("");
      setSelectedId((current) => (
        current && items.some((item) => item.id === current) ? current : (items[0]?.id || "")
      ));
    }
    setLoading(false);
  }, [activeAgentId, activeSessionId, category, sessionOnly, t]);

  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    if (!activeAgentId || !selectedId) {
      setSelected(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    void window.gateway.getModelTrace({ agentId: activeAgentId, traceId: selectedId }).then((response) => {
      if (cancelled) return;
      if (response.error) setError(response.error.message || t("modelTrace.loadFailed"));
      else setSelected((response.result?.trace || null) as ModelTraceRecord | null);
      setDetailLoading(false);
    });
    return () => { cancelled = true; };
  }, [activeAgentId, selectedId, t]);

  useEffect(() => window.gateway.onEvent((event: { event?: string; agentId?: string }) => {
    if (!event.event?.startsWith("model.trace.") || event.agentId !== activeAgentId) return;
    void refresh();
  }), [activeAgentId, refresh]);

  const clear = useCallback(async () => {
    if (!activeAgentId || !window.confirm(t("modelTrace.clearConfirm"))) return;
    const response = await window.gateway.clearModelTraces({ agentId: activeAgentId });
    if (response.error) setError(response.error.message || t("modelTrace.clearFailed"));
    else {
      setSelected(null);
      setSelectedId("");
      await refresh();
    }
  }, [activeAgentId, refresh, t]);

  const categories = ["conversation", "assignment", "autonomous", "intent", "memory", "dream", "vision", "other"];

  return (
    <div className="model-trace-backdrop" onMouseDown={onClose}>
      <section className="model-trace-dialog" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
        <header className="model-trace-header">
          <div>
            <span>{t("modelTrace.currentAgent", { name: activeAgent?.name || t("usage.agent") })}</span>
            <h2>{t("modelTrace.title")}</h2>
            <p>{t("modelTrace.subtitle")}</p>
          </div>
          <div className="model-trace-header-actions">
            <button type="button" onClick={() => void refresh()} title={t("common.refresh")}><Icon name="refresh" size={16} /></button>
            <button type="button" onClick={() => void clear()} title={t("modelTrace.clear")}><Icon name="trash" size={16} /></button>
            <button type="button" onClick={onClose} title={t("common.close")}><Icon name="x" size={16} /></button>
          </div>
        </header>

        <div className="model-trace-toolbar">
          <label className="model-trace-check">
            <input type="checkbox" checked={sessionOnly} onChange={(event) => setSessionOnly(event.target.checked)} />
            <span>{t("modelTrace.currentSessionOnly")}</span>
          </label>
          <select value={category} onChange={(event) => setCategory(event.target.value)}>
            <option value="">{t("modelTrace.allCategories")}</option>
            {categories.map((item) => <option key={item} value={item}>{t(`usage.category.${item}`, item)}</option>)}
          </select>
          <span className="model-trace-count">{t("modelTrace.recordCount", { count: records.length })}</span>
        </div>

        {error ? <div className="model-trace-error">{error}</div> : null}
        <div className="model-trace-body">
          <aside className="model-trace-list">
            {loading && records.length === 0 ? <div className="model-trace-empty">{t("common.loading")}</div> : null}
            {!loading && records.length === 0 ? <div className="model-trace-empty">{t("modelTrace.empty")}</div> : null}
            {records.map((item) => (
              <button
                type="button"
                key={item.id}
                className={selectedId === item.id ? "active" : ""}
                onClick={() => setSelectedId(item.id)}
              >
                <div className="model-trace-list-top">
                  <strong>{item.model || item.provider}</strong>
                  <time>{formatTime(item.created_at)}</time>
                </div>
                <div className="model-trace-list-meta">
                  <span className={`trace-status is-${item.status}`}>{t(`modelTrace.status.${item.status}`)}</span>
                  <span>{t(`usage.category.${item.category || "other"}`, item.category || "other")}</span>
                  <span>{item.message_count} msg</span>
                  {item.tool_count > 0 ? <span>{item.tool_count} tools</span> : null}
                </div>
                <small>{item.total_tokens > 0 ? `${formatTokens(item.total_tokens)} tokens · ` : ""}{formatLatency(item.latency_ms)}</small>
              </button>
            ))}
          </aside>

          <main className="model-trace-detail">
            {detailLoading ? <div className="model-trace-empty">{t("common.loading")}</div> : null}
            {!detailLoading && !selected ? <div className="model-trace-empty">{t("modelTrace.selectHint")}</div> : null}
            {selected ? (
              <>
                <div className="model-trace-detail-top">
                  <TraceMetadata trace={selected} t={t} />
                  <div className="model-trace-view-tabs">
                    <button className={viewMode === "structured" ? "active" : ""} onClick={() => setViewMode("structured")}>{t("modelTrace.structured")}</button>
                    <button className={viewMode === "raw" ? "active" : ""} onClick={() => setViewMode("raw")}>{t("modelTrace.raw")}</button>
                  </div>
                </div>
                {viewMode === "raw" ? <JsonBlock value={selected} /> : <StructuredTrace trace={selected} t={t} />}
              </>
            ) : null}
          </main>
        </div>
      </section>
    </div>
  );
}

function TraceMetadata({ trace, t }: { trace: ModelTraceRecord; t: (key: string, options?: unknown) => string }) {
  return (
    <div className="model-trace-metadata">
      <span><b>{t("modelTrace.model")}</b>{trace.provider}/{trace.model}</span>
      <span><b>{t("modelTrace.source")}</b>{t(`usage.category.${trace.category || "other"}`, trace.category || "other")}</span>
      <span><b>Session</b>{trace.session_id || "—"}</span>
      <span><b>Turn</b>{trace.turn_id || "—"}</span>
    </div>
  );
}

function StructuredTrace({ trace, t }: { trace: ModelTraceRecord; t: (key: string, options?: unknown) => string }) {
  const request = trace.request || {};
  const messages = Array.isArray(request.messages) ? request.messages as Record<string, unknown>[] : [];
  const topLevelSystem = request.system;
  const displayMessages = topLevelSystem === undefined || topLevelSystem === null || topLevelSystem === ""
    ? messages
    : [{ role: "system", content: topLevelSystem }, ...messages];
  const tools = Array.isArray(request.tools) ? request.tools as Record<string, unknown>[] : [];
  const parameters = Object.fromEntries(Object.entries(request).filter(([key]) => key !== "messages" && key !== "tools" && key !== "system"));
  const responseUsage = trace.response && typeof trace.response.usage === "object" && trace.response.usage
    ? trace.response.usage as Record<string, unknown>
    : null;
  return (
    <div className="model-trace-sections">
      {responseUsage ? <TokenBreakdown usage={responseUsage} t={t} /> : null}
      <TraceSection title={t("modelTrace.parameters")} count={Object.keys(parameters).length} initiallyOpen>
        <JsonBlock value={parameters} />
      </TraceSection>
      <TraceSection title={t("modelTrace.messages")} count={displayMessages.length} initiallyOpen>
        <div className="model-trace-messages">
          {displayMessages.map((message, index) => <MessageCard key={index} message={message} index={index + 1} />)}
        </div>
      </TraceSection>
      <TraceSection title={t("modelTrace.toolDefinitions")} count={tools.length}>
        <div className="model-trace-tools">
          {tools.map((tool, index) => {
            const fn = (tool.function || {}) as Record<string, unknown>;
            return <details key={index}><summary>{String(fn.name || tool.name || `tool ${index + 1}`)}</summary><JsonBlock value={tool} /></details>;
          })}
        </div>
      </TraceSection>
      <TraceSection title={t("modelTrace.response")} count={trace.response ? 1 : 0} initiallyOpen>
        {trace.error ? <div className="model-trace-response-error">{trace.error}</div> : null}
        <JsonBlock value={trace.response || { status: trace.status }} />
      </TraceSection>
    </div>
  );
}

function TokenBreakdown({ usage, t }: { usage: Record<string, unknown>; t: (key: string, options?: unknown) => string }) {
  const raw = usage.detailed_input_breakdown;
  if (!raw || typeof raw !== "object") return null;
  const breakdown = raw as Record<string, unknown>;
  const items = [
    "system", "user", "assistant", "tool_definitions", "tool_calls",
    "tool_results", "skills", "workspace", "other",
  ].map((key) => ({ key, value: Number(breakdown[key] || 0) }))
    .filter((item) => item.value > 0);
  const inputTokens = Number(usage.input_tokens || items.reduce((sum, item) => sum + item.value, 0));
  if (items.length === 0) return null;
  return (
    <section className="model-trace-token-card">
      <div className="model-trace-token-heading">
        <div>
          <strong>{t("modelTrace.tokenComposition")}</strong>
          <span>{t(usage.exact ? "modelTrace.tokenEstimateHintExact" : "modelTrace.tokenEstimateHintLocal")}</span>
        </div>
        <b>{formatTokens(inputTokens)} tokens</b>
      </div>
      <div className="model-trace-token-grid">
        {items.map((item) => (
          <div key={item.key}>
            <span>{t(`modelTrace.token.${item.key}`)}</span>
            <strong>{formatTokens(item.value)}</strong>
            <i><em style={{ width: `${Math.max(2, Math.round(item.value / Math.max(1, inputTokens) * 100))}%` }} /></i>
          </div>
        ))}
      </div>
    </section>
  );
}

function MessageCard({ message, index }: { message: Record<string, unknown>; index: number }) {
  const role = String(message.role || "unknown");
  const remainder = Object.fromEntries(Object.entries(message).filter(([key]) => key !== "role" && key !== "content"));
  return (
    <article className={`model-trace-message role-${role}`}>
      <header><span>{index}</span><strong>{role}</strong></header>
      {typeof message.content === "string" ? <pre>{message.content || "(empty)"}</pre> : <JsonBlock value={message.content} />}
      {Object.keys(remainder).length > 0 ? <details><summary>metadata / tool calls</summary><JsonBlock value={remainder} /></details> : null}
    </article>
  );
}

function TraceSection({ title, count, initiallyOpen = false, children }: { title: string; count: number; initiallyOpen?: boolean; children: React.ReactNode }) {
  return <details className="model-trace-section" open={initiallyOpen}><summary><strong>{title}</strong><span>{count}</span></summary>{children}</details>;
}

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="model-trace-json">{JSON.stringify(value, null, 2)}</pre>;
}

function formatTime(timestamp: number): string {
  return timestamp ? new Date(timestamp * 1000).toLocaleString([], { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
}

function formatLatency(value: number): string {
  if (!value) return "—";
  return value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${Math.round(value)}ms`;
}
