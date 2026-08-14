import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useCoreStore } from "../store";
import type { VectorTraceCandidate, VectorTraceRecord } from "../types";
import { Icon } from "./ui";

export function VectorTracePanel({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const activeAgentId = useCoreStore((state) => state.activeAgentId || "");
  const activeAgent = useCoreStore((state) => state.agents.find((item) => item.id === state.activeAgentId));
  const activeSessionId = useCoreStore((state) => state.activeSessionByAgent[state.activeAgentId || ""] || "");
  const [records, setRecords] = useState<VectorTraceRecord[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [sessionOnly, setSessionOnly] = useState(true);
  const [source, setSource] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    if (!activeAgentId) return;
    setLoading(true);
    const response = await window.gateway.listVectorTraces({
      agentId: activeAgentId,
      sessionId: sessionOnly ? activeSessionId : "",
      source,
      limit: 500,
    });
    if (response.error) {
      setError(response.error.message || t("vectorTrace.loadFailed"));
    } else {
      const result = response.result as { items?: VectorTraceRecord[] } | undefined;
      setRecords(result?.items || []);
      setError("");
    }
    setLoading(false);
  }, [activeAgentId, activeSessionId, sessionOnly, source, t]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const dispose = window.gateway.onEvent((event: { event?: string; agentId?: string }) => {
      if (event.agentId !== activeAgentId || event.event !== "vector.trace.created") return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => void refresh(), 250);
    });
    return () => {
      if (timer) clearTimeout(timer);
      dispose();
    };
  }, [activeAgentId, refresh]);

  useEffect(() => {
    if (!records.length) setSelectedId("");
    else if (!records.some((item) => item.id === selectedId)) setSelectedId(records[0].id);
  }, [records, selectedId]);

  const selected = records.find((item) => item.id === selectedId) || null;
  const sources = useMemo(() => [...new Set(records.map((item) => item.source))].sort(), [records]);
  const summary = useMemo(() => summarize(records), [records]);

  const clear = async () => {
    if (!activeAgentId || !window.confirm(t("vectorTrace.clearConfirm"))) return;
    const response = await window.gateway.clearVectorTraces({ agentId: activeAgentId });
    if (response.error) setError(response.error.message || t("vectorTrace.clearFailed"));
    else void refresh();
  };

  return <section className="vector-trace" aria-label={t("vectorTrace.title")}>
    <header className="vector-trace-header">
      <div>
        <span>{t("vectorTrace.currentAgentSession", { name: activeAgent?.name || activeAgentId, session: activeSessionId || "—" })}</span>
        <h2>{t("vectorTrace.title")}</h2>
        <p>{t("vectorTrace.subtitle")}</p>
      </div>
      <div>
        <button type="button" onClick={() => void refresh()} title={t("common.refresh")}><Icon name="refresh" size={16} /></button>
        <button type="button" onClick={() => void clear()} title={t("vectorTrace.clear")}><Icon name="trash" size={16} /></button>
        <button type="button" onClick={onClose} title={t("common.close")}><Icon name="x" size={16} /></button>
      </div>
    </header>
    <div className="vector-trace-summary">
      <Metric label={t("vectorTrace.requests")} value={String(records.length)} />
      <Metric label={t("vectorTrace.retrievals")} value={String(summary.retrievals)} />
      <Metric label={t("vectorTrace.totalTime")} value={`${summary.totalMs} ms`} />
      <Metric label={t("vectorTrace.cacheRate")} value={`${summary.cacheRate}%`} />
    </div>
    <div className="vector-trace-toolbar">
      <label><input type="checkbox" checked={sessionOnly} onChange={(event) => setSessionOnly(event.target.checked)} />{t("vectorTrace.currentSessionOnly")}</label>
      <select value={source} onChange={(event) => setSource(event.target.value)}>
        <option value="">{t("vectorTrace.allSources")}</option>
        {sources.map((item) => <option key={item} value={item}>{sourceName(item, t)}</option>)}
      </select>
    </div>
    {error ? <div className="vector-trace-error">{error}</div> : null}
    <div className="vector-trace-body">
      <aside className="vector-trace-list">
        {loading && !records.length ? <div className="vector-trace-empty">{t("common.loading")}</div> : null}
        {!loading && !records.length ? <div className="vector-trace-empty">{t("vectorTrace.empty")}</div> : null}
        {records.map((item) => <button key={item.id} className={item.id === selectedId ? "active" : ""} onClick={() => setSelectedId(item.id)}>
          <span><b>{sourceName(item.source, t)}</b><em className={`is-${item.phase}`}>{phaseName(item.phase, t)}</em></span>
          <strong>{cleanQuery(item.query) || t("vectorTrace.noQuery")}</strong>
          <small><time>{formatTime(item.created_at)}</time><span>{t("vectorTrace.candidateCount", { count: item.candidates?.length || 0 })}</span></small>
        </button>)}
      </aside>
      <main className="vector-trace-detail">
        {!selected ? <div className="vector-trace-empty">{t("vectorTrace.selectHint")}</div> : <TraceDetail trace={selected} />}
      </main>
    </div>
  </section>;
}

function TraceDetail({ trace }: { trace: VectorTraceRecord }) {
  const { t } = useTranslation();
  const metadata = trace.metadata || {};
  return <>
    <header className="vector-trace-detail-header">
      <div><span>{sourceName(trace.source, t)} · {phaseName(trace.phase, t)}</span><h3>{cleanQuery(trace.query) || t("vectorTrace.noQuery")}</h3></div>
      <span className={`trace-status is-${trace.status === "ok" ? "completed" : "failed"}`}>{trace.status}</span>
    </header>
    <div className="vector-trace-detail-content">
      <section className="vector-trace-metrics">
        <Metric label={t("vectorTrace.totalTime")} value={metric(metadata.total_ms, "ms")} />
        <Metric label={t("vectorTrace.queueTime")} value={metric(metadata.queue_ms, "ms")} />
        <Metric label={t("vectorTrace.inferenceTime")} value={metric(metadata.inference_ms, "ms")} />
        <Metric label={t("vectorTrace.cache")} value={cacheText(metadata, t)} />
      </section>
      <section className="vector-trace-card">
        <header><strong>{t("vectorTrace.query")}</strong><span>{trace.query.length}</span></header>
        <pre>{trace.query || t("vectorTrace.noQuery")}</pre>
      </section>
      {trace.threshold != null ? <div className="vector-trace-threshold">{t("vectorTrace.threshold")} <strong>{formatNumber(trace.threshold)}</strong></div> : null}
      <section className="vector-trace-candidates">
        <header><strong>{t("vectorTrace.candidates")}</strong><span>{trace.candidates?.length || 0}</span></header>
        {(trace.candidates || []).length ? trace.candidates.map((item, index) => <CandidateRow key={`${item.id || item.name}-${index}`} item={item} all={trace.candidates} />) : <p>{t("vectorTrace.noCandidates")}</p>}
      </section>
      {trace.error ? <div className="vector-trace-error">{trace.error}</div> : null}
    </div>
  </>;
}

function CandidateRow({ item, all }: { item: VectorTraceCandidate; all: VectorTraceCandidate[] }) {
  const { t } = useTranslation();
  const value = candidateValue(item);
  const values = all.map(candidateValue).filter((entry): entry is number => entry != null);
  const maximum = Math.max(...values.map((entry) => Math.abs(entry)), 1);
  const width = value == null ? 0 : Math.max(3, Math.min(100, Math.abs(value) / maximum * 100));
  return <article className={item.selected ? "selected" : ""}>
    <div><strong>{item.name || item.id || t("vectorTrace.unnamed")}</strong>{item.selected ? <span>{t("vectorTrace.selected")}</span> : null}</div>
    <div className="vector-trace-score"><i style={{ width: `${width}%` }} /><code>{candidateMetric(item)}</code></div>
  </article>;
}

function Metric({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div>; }
function cleanQuery(value: string): string { return String(value || "").replace(/^Current user request:\s*/i, "").replace(/\s+/g, " ").trim(); }
function candidateValue(item: VectorTraceCandidate): number | null { const value = item.score ?? item.similarity ?? item.distance; return typeof value === "number" ? value : null; }
function candidateMetric(item: VectorTraceCandidate): string { if (typeof item.score === "number") return `score ${formatNumber(item.score)}`; if (typeof item.similarity === "number") return `similarity ${formatNumber(item.similarity)}`; if (typeof item.distance === "number") return `distance ${formatNumber(item.distance)}`; return "—"; }
function formatNumber(value: number): string { return Number(value).toFixed(4).replace(/0+$/, "").replace(/\.$/, ""); }
function metric(value: unknown, suffix: string): string { return typeof value === "number" ? `${value} ${suffix}` : "—"; }
function cacheText(metadata: Record<string, unknown>, t: (key: string, options?: Record<string, unknown>) => string): string { const hits = Number(metadata.cache_hits || 0); const misses = Number(metadata.cache_misses || 0); return hits || misses ? t("vectorTrace.cacheHits", { hits, misses }) : "—"; }
function formatTime(value: number): string { return value ? new Date(value * 1000).toLocaleString([], { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—"; }
function phaseName(value: string, t: (key: string) => string): string { return value === "embedding" ? t("vectorTrace.embedding") : t("vectorTrace.retrieval"); }
function sourceName(value: string, t: (key: string) => string): string { const key = `vectorTrace.source.${value.replaceAll(".", "_")}`; const translated = t(key); return translated === key ? value : translated; }
function summarize(records: VectorTraceRecord[]) { const retrievals = records.filter((item) => item.phase === "retrieval").length; let totalMs = 0; let hits = 0; let misses = 0; records.forEach((item) => { totalMs += Number(item.metadata?.total_ms || 0); hits += Number(item.metadata?.cache_hits || 0); misses += Number(item.metadata?.cache_misses || 0); }); return { retrievals, totalMs, cacheRate: hits + misses ? Math.round(hits / (hits + misses) * 100) : 0 }; }
