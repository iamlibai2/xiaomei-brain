import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useCoreStore } from "../store";
import type { ModelTraceRecord, ModelTraceSummary } from "../types";
import { formatTokens, useTokenUsage } from "../usage";
import { Icon } from "./ui";

type DetailTab = "overview" | "messages" | "tools" | "response" | "raw";
type RoleFilter = "all" | "system" | "user" | "assistant" | "tool";

interface TurnGroup {
  id: string;
  records: ModelTraceSummary[];
  createdAt: number;
  prompt: string;
  totalTokens: number;
  latencyMs: number;
  status: ModelTraceSummary["status"];
}

export function ModelContextDialog({ onClose, embedded = false }: { onClose: () => void; embedded?: boolean }) {
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
  const [sessionOnly, setSessionOnly] = useState(true);
  const [category, setCategory] = useState("");
  const [detailTab, setDetailTab] = useState<DetailTab>("overview");
  const [query, setQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState<RoleFilter>("all");
  const { summary: tokenUsageSummary } = useTokenUsage(
    activeAgentId,
    activeSessionId,
    Boolean(activeAgentId && activeSessionId),
  );
  const currentSessionUsage = tokenUsageSummary?.current_session;

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

  const groups = useMemo(() => groupByTurn(records), [records]);
  const selectedGroup = useMemo(
    () => groups.find((group) => group.records.some((record) => record.id === selectedId)) || null,
    [groups, selectedId],
  );
  const categories = ["conversation", "assignment", "autonomous", "intent", "memory", "dream", "vision", "other"];

  const content = (
      <section
        className={`model-trace-dialog${embedded ? " is-embedded" : ""}`}
        role={embedded ? "complementary" : "dialog"}
        aria-modal={embedded ? undefined : true}
        aria-label={embedded ? t("modelTrace.title") : undefined}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="model-trace-header">
          <div>
            <span>{t("modelTrace.currentAgentSession", {
              name: activeAgent?.name || t("usage.agent"),
              session: activeSessionId || "—",
            })}</span>
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
          <span className="model-trace-count">
            <span>{t("modelTrace.turnAndRequestCount", { turns: groups.length, requests: records.length })}</span>
            <span className="model-trace-count-separator">·</span>
            <span>{t("modelTrace.currentSessionTokens", {
              value: `${currentSessionUsage?.estimated_calls ? "≈" : ""}${formatTokens(currentSessionUsage?.total_tokens || 0)}`,
            })}</span>
          </span>
        </div>

        {error ? <div className="model-trace-error">{error}</div> : null}
        <div className="model-trace-body">
          <aside className="model-trace-list">
            {loading && records.length === 0 ? <div className="model-trace-empty">{t("common.loading")}</div> : null}
            {!loading && records.length === 0 ? <div className="model-trace-empty">{t("modelTrace.empty")}</div> : null}
            {groups.map((group) => (
              <section className="model-trace-turn" key={group.id}>
                <header>
                  <div>
                    <strong>{cleanPromptPreview(group.prompt) || t("modelTrace.noPromptPreview")}</strong>
                    <time>{formatTime(group.createdAt)}</time>
                  </div>
                  <small>
                    <span className={`trace-status is-${group.status}`}>{t(`modelTrace.status.${group.status}`)}</span>
                    <span>{t("modelTrace.requestSteps", { count: group.records.length })}</span>
                    {group.totalTokens > 0 ? <span>{formatTokens(group.totalTokens)} tokens</span> : null}
                  </small>
                </header>
                <div className="model-trace-turn-steps">
                  {group.records.map((item, index) => (
                    <button
                      type="button"
                      key={item.id}
                      className={selectedId === item.id ? "active" : ""}
                      onClick={() => setSelectedId(item.id)}
                    >
                      <span className="model-trace-step-number">{group.records.length - index}</span>
                      <span className="model-trace-step-copy">
                        <strong>
                          {item.tool_call_names?.length
                            ? t("modelTrace.calledTools", { names: item.tool_call_names.join(", ") })
                            : t("modelTrace.directResponse")}
                        </strong>
                      </span>
                      <span className="model-trace-step-metric">
                        {item.total_tokens > 0 ? formatTokens(item.total_tokens) : "—"}
                        <small>{formatLatency(item.latency_ms)}</small>
                      </span>
                    </button>
                  ))}
                </div>
              </section>
            ))}
          </aside>

          <main className="model-trace-detail">
            {detailLoading && !selected ? <div className="model-trace-empty">{t("common.loading")}</div> : null}
            {!detailLoading && !selected ? <div className="model-trace-empty">{t("modelTrace.selectHint")}</div> : null}
            {selected ? (
              <>
                <TraceHeader trace={selected} group={selectedGroup} t={t} />
                <nav className="model-trace-detail-tabs">
                  {(["overview", "messages", "tools", "response", "raw"] as DetailTab[]).map((tab) => (
                    <button key={tab} className={detailTab === tab ? "active" : ""} onClick={() => setDetailTab(tab)}>
                      {t(`modelTrace.tab.${tab}`)}
                      {tab === "messages" ? <span>{t("modelTrace.messageCount", { count: getMessages(selected).length })}</span> : null}
                      {tab === "tools" ? <span>{t("modelTrace.toolDefinitionCount", { count: getTools(selected).length })}</span> : null}
                    </button>
                  ))}
                </nav>
                <div className={`model-trace-tab-content${detailLoading ? " is-refreshing" : ""}`}>
                  {detailTab === "overview" ? <Overview trace={selected} t={t} /> : null}
                  {detailTab === "messages" ? (
                    <MessagesView trace={selected} query={query} setQuery={setQuery} roleFilter={roleFilter} setRoleFilter={setRoleFilter} t={t} />
                  ) : null}
                  {detailTab === "tools" ? <ToolsView trace={selected} query={query} setQuery={setQuery} t={t} /> : null}
                  {detailTab === "response" ? <ResponseView trace={selected} t={t} /> : null}
                  {detailTab === "raw" ? <JsonBlock value={selected} /> : null}
                </div>
              </>
            ) : null}
          </main>
        </div>
      </section>
  );
  if (embedded) return content;
  return <div className="model-trace-backdrop" onMouseDown={onClose}>{content}</div>;
}

function TraceHeader({ trace, group, t }: { trace: ModelTraceRecord; group: TurnGroup | null; t: Translate }) {
  const step = group ? [...group.records].reverse().findIndex((item) => item.id === trace.id) + 1 : 1;
  return (
    <div className="model-trace-detail-top">
      <div className="model-trace-detail-title">
        <span>{t("modelTrace.stepTitle", { step, total: group?.records.length || 1 })}</span>
        <strong>{trace.provider}/{trace.model}</strong>
      </div>
      <div className="model-trace-metadata">
        <span className={`trace-status is-${trace.status}`}>{t(`modelTrace.status.${trace.status}`)}</span>
        <span className="trace-source">{t(`usage.category.${trace.category || "other"}`, trace.category || "other")}</span>
        <span className="trace-time">{formatTime(trace.created_at)}</span>
      </div>
    </div>
  );
}

function Overview({ trace, t }: { trace: ModelTraceRecord; t: Translate }) {
  const request = trace.request || {};
  const messages = getMessages(trace);
  const tools = getTools(trace);
  const parameters = Object.fromEntries(Object.entries(request).filter(([key]) => !["messages", "tools", "system"].includes(key)));
  const usage = getUsage(trace);
  const toolCalls = extractToolCalls(trace);
  return (
    <div className="model-trace-overview">
      <div className="model-trace-stat-grid">
        <Stat label={t("modelTrace.inputTokens")} value={formatMetric(trace.input_tokens || Number(usage?.input_tokens || usage?.prompt_tokens || 0), "tokens")} />
        <Stat label={t("modelTrace.outputTokens")} value={formatMetric(trace.output_tokens || Number(usage?.output_tokens || usage?.completion_tokens || 0), "tokens")} />
        <Stat label={t("modelTrace.messages")} value={String(messages.length)} />
        <Stat label={t("modelTrace.availableTools")} value={String(tools.length)} />
        <Stat label={t("modelTrace.toolCalls")} value={String(toolCalls.length)} />
        <Stat label={t("modelTrace.latency")} value={formatLatency(trace.latency_ms)} />
      </div>
      {usage ? <TokenBreakdown usage={usage} t={t} /> : null}
      {toolCalls.length > 0 ? (
        <section className="model-trace-summary-card">
          <header><strong>{t("modelTrace.toolCalls")}</strong><span>{toolCalls.length}</span></header>
          <div className="model-trace-call-list">
            {toolCalls.map((call, index) => <code key={`${call}-${index}`}>{call}</code>)}
          </div>
        </section>
      ) : null}
      <section className="model-trace-summary-card">
        <header><strong>{t("modelTrace.parameters")}</strong><span>{Object.keys(parameters).length}</span></header>
        <JsonBlock value={parameters} />
      </section>
      <section className="model-trace-identifiers">
        <span><b>Session</b><code>{trace.session_id || "—"}</code></span>
        <span><b>Turn</b><code>{trace.turn_id || "—"}</code></span>
        <span><b>Trace</b><code>{trace.id}</code></span>
      </section>
    </div>
  );
}

function MessagesView({ trace, query, setQuery, roleFilter, setRoleFilter, t }: {
  trace: ModelTraceRecord;
  query: string;
  setQuery: (value: string) => void;
  roleFilter: RoleFilter;
  setRoleFilter: (value: RoleFilter) => void;
  t: Translate;
}) {
  const messages = getMessages(trace);
  const normalizedQuery = query.trim().toLowerCase();
  const filtered = messages.filter((message) => {
    const role = String(message.role || "unknown");
    return (roleFilter === "all" || role === roleFilter)
      && (!normalizedQuery || JSON.stringify(message).toLowerCase().includes(normalizedQuery));
  });
  return (
    <>
      <div className="model-trace-content-toolbar">
        <div className="model-trace-role-filters">
          {(["all", "system", "user", "assistant", "tool"] as RoleFilter[]).map((role) => (
            <button key={role} className={roleFilter === role ? "active" : ""} onClick={() => setRoleFilter(role)}>
              {t(`modelTrace.role.${role}`)}
            </button>
          ))}
        </div>
        <SearchInput value={query} onChange={setQuery} placeholder={t("modelTrace.searchMessages")} />
      </div>
      <div className="model-trace-messages">
        {filtered.map((message, index) => <MessageCard key={index} message={message} index={messages.indexOf(message) + 1} t={t} />)}
        {filtered.length === 0 ? <div className="model-trace-empty compact">{t("modelTrace.noMatches")}</div> : null}
      </div>
    </>
  );
}

function ToolsView({ trace, query, setQuery, t }: { trace: ModelTraceRecord; query: string; setQuery: (value: string) => void; t: Translate }) {
  const tools = getTools(trace);
  const normalizedQuery = query.trim().toLowerCase();
  const filtered = tools.filter((tool) => JSON.stringify(tool).toLowerCase().includes(normalizedQuery));
  return (
    <>
      <div className="model-trace-content-toolbar is-right">
        <SearchInput value={query} onChange={setQuery} placeholder={t("modelTrace.searchTools")} />
      </div>
      <div className="model-trace-tools">
        {filtered.map((tool, index) => {
          const fn = (tool.function || tool) as Record<string, unknown>;
          const parameters = (fn.parameters || {}) as Record<string, unknown>;
          const required = Array.isArray(parameters.required) ? parameters.required : [];
          return (
            <details key={index}>
              <summary>
                <span><strong>{String(fn.name || `tool ${index + 1}`)}</strong><small>{String(fn.description || t("modelTrace.noToolDescription"))}</small></span>
                <em>{t("modelTrace.requiredParameters", { count: required.length })}</em>
              </summary>
              <JsonBlock value={tool} />
            </details>
          );
        })}
        {filtered.length === 0 ? <div className="model-trace-empty compact">{t("modelTrace.noMatches")}</div> : null}
      </div>
    </>
  );
}

function ResponseView({ trace, t }: { trace: ModelTraceRecord; t: Translate }) {
  return (
    <div className="model-trace-response">
      {trace.error ? <div className="model-trace-response-error"><strong>{t("modelTrace.error")}</strong>{trace.error}</div> : null}
      <JsonBlock value={trace.response || { status: trace.status }} />
    </div>
  );
}

function TokenBreakdown({ usage, t }: { usage: Record<string, unknown>; t: Translate }) {
  const raw = usage.detailed_input_breakdown;
  if (!raw || typeof raw !== "object") return null;
  const breakdown = raw as Record<string, unknown>;
  const items = ["system", "user", "assistant", "tool_definitions", "tool_calls", "tool_results", "skills", "workspace", "other"]
    .map((key) => ({ key, value: Number(breakdown[key] || 0) }))
    .filter((item) => item.value > 0);
  const inputTokens = Number(usage.input_tokens || usage.prompt_tokens || items.reduce((sum, item) => sum + item.value, 0));
  if (items.length === 0) return null;
  return (
    <section className="model-trace-token-card">
      <div className="model-trace-token-heading">
        <div><strong>{t("modelTrace.tokenComposition")}</strong><span>{t(usage.exact ? "modelTrace.tokenEstimateHintExact" : "modelTrace.tokenEstimateHintLocal")}</span></div>
        <b>{formatTokens(inputTokens)} tokens</b>
      </div>
      <div className="model-trace-token-grid">
        {items.map((item) => (
          <div key={item.key}>
            <span>{t(`modelTrace.token.${item.key}`)}</span><strong>{formatTokens(item.value)}</strong>
            <i><em style={{ width: `${Math.max(2, Math.round(item.value / Math.max(1, inputTokens) * 100))}%` }} /></i>
          </div>
        ))}
      </div>
    </section>
  );
}

function MessageCard({ message, index, t }: { message: Record<string, unknown>; index: number; t: Translate }) {
  const role = String(message.role || "unknown");
  const remainder = Object.fromEntries(Object.entries(message).filter(([key]) => key !== "role" && key !== "content"));
  const content = typeof message.content === "string" ? message.content : JSON.stringify(message.content, null, 2);
  const collapsible = role === "system" || role === "tool" || content.length > 1200;
  const body = (
    <>
      {typeof message.content === "string" ? <pre>{message.content || t("modelTrace.emptyContent")}</pre> : <JsonBlock value={message.content} />}
      {Object.keys(remainder).length > 0 ? <details className="model-trace-message-metadata"><summary>{t("modelTrace.messageMetadata")}</summary><JsonBlock value={remainder} /></details> : null}
    </>
  );
  return (
    <article className={`model-trace-message role-${role}`}>
      <header>
        <span>{index}</span><strong>{role}</strong>
        <small>{formatTokens(estimateTextTokens(content))} tokens</small>
        <button type="button" title={t("common.copy")} onClick={() => void navigator.clipboard.writeText(JSON.stringify(message, null, 2))}><Icon name="copy" size={14} /></button>
      </header>
      {collapsible ? <details><summary>{content.slice(0, 140) || t("modelTrace.emptyContent")}</summary>{body}</details> : body}
    </article>
  );
}

function SearchInput({ value, onChange, placeholder }: { value: string; onChange: (value: string) => void; placeholder: string }) {
  return <label className="model-trace-search"><Icon name="search" size={14} /><input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} /></label>;
}

function Stat({ label, value }: { label: string; value: string }) {
  return <div className="model-trace-stat"><span>{label}</span><strong>{value}</strong></div>;
}

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="model-trace-json">{JSON.stringify(value, null, 2)}</pre>;
}

function groupByTurn(records: ModelTraceSummary[]): TurnGroup[] {
  const groups = new Map<string, TurnGroup>();
  records.forEach((record) => {
    const id = record.turn_id || record.id;
    const group = groups.get(id) || {
      id,
      records: [],
      createdAt: record.created_at,
      prompt: record.prompt_preview || "",
      totalTokens: 0,
      latencyMs: 0,
      status: record.status,
    };
    group.records.push(record);
    group.createdAt = Math.min(group.createdAt, record.created_at);
    group.prompt ||= record.prompt_preview || "";
    group.totalTokens += record.total_tokens || 0;
    group.latencyMs += record.latency_ms || 0;
    if (record.status === "running" || (record.status === "failed" && group.status !== "running")) group.status = record.status;
    groups.set(id, group);
  });
  return [...groups.values()];
}

function getMessages(trace: ModelTraceRecord): Record<string, unknown>[] {
  const request = trace.request || {};
  const messages = Array.isArray(request.messages) ? request.messages as Record<string, unknown>[] : [];
  return request.system === undefined || request.system === null || request.system === ""
    ? messages
    : [{ role: "system", content: request.system }, ...messages];
}

function getTools(trace: ModelTraceRecord): Record<string, unknown>[] {
  return Array.isArray(trace.request?.tools) ? trace.request.tools as Record<string, unknown>[] : [];
}

function getUsage(trace: ModelTraceRecord): Record<string, unknown> | null {
  return trace.response && typeof trace.response.usage === "object" && trace.response.usage
    ? trace.response.usage as Record<string, unknown>
    : null;
}

function extractToolCalls(trace: ModelTraceRecord): string[] {
  const calls = trace.response && Array.isArray(trace.response.tool_calls) ? trace.response.tool_calls : [];
  return calls.map((call) => {
    if (!call || typeof call !== "object") return "unknown";
    const typed = call as Record<string, unknown>;
    const fn = typed.function && typeof typed.function === "object" ? typed.function as Record<string, unknown> : {};
    return String(fn.name || typed.name || "unknown");
  });
}

function estimateTextTokens(value: string): number {
  if (!value) return 0;
  const cjk = (value.match(/[\u3400-\u9fff]/g) || []).length;
  return Math.max(1, Math.round(cjk * 0.75 + (value.length - cjk) / 4));
}

function formatMetric(value: number, suffix: string): string {
  return value > 0 ? `${formatTokens(value)} ${suffix}` : "—";
}

function cleanPromptPreview(value: string): string {
  let text = String(value || "").trim();
  // Internal time context is useful to the model but should not become the
  // human-facing title of a trace group.
  if (/^<当前时间>/.test(text)) return "";
  text = text.replace(/^\[[\d\s:/.-]+]\s*/, "");
  text = text.replace(/^距上条消息\s*\d+(?:\.\d+)?\s*(?:秒|分钟|小时|天)\s*/, "");
  return text.trim();
}

function formatTime(timestamp: number): string {
  return timestamp ? new Date(timestamp * 1000).toLocaleString([], { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
}

function formatLatency(value: number): string {
  if (!value) return "—";
  return value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${Math.round(value)}ms`;
}

type Translate = (key: string, options?: Record<string, unknown> | string) => string;
