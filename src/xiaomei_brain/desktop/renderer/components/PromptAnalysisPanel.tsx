import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useCoreStore } from "../store";
import type { ModelTraceRecord, ModelTraceSummary, PromptAnalysisSection } from "../types";
import { Icon } from "./ui";

export function PromptAnalysisPanel({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const activeAgentId = useCoreStore((state) => state.activeAgentId || "");
  const activeAgent = useCoreStore((state) => state.agents.find((item) => item.id === state.activeAgentId));
  const activeSessionId = useCoreStore((state) => state.activeSessionByAgent[state.activeAgentId || ""] || "");
  const [records, setRecords] = useState<ModelTraceSummary[]>([]);
  const [selectedTraceId, setSelectedTraceId] = useState("");
  const [selectedSectionKey, setSelectedSectionKey] = useState("");
  const [trace, setTrace] = useState<ModelTraceRecord | null>(null);
  const [sessionOnly, setSessionOnly] = useState(true);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [textExpanded, setTextExpanded] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    if (!activeAgentId) return;
    setLoading(true);
    const response = await window.gateway.listModelTraces({
      agentId: activeAgentId,
      sessionId: sessionOnly ? activeSessionId : "",
      limit: 200,
    });
    if (response.error) {
      setError(response.error.message || t("promptAnalysis.loadFailed"));
    } else {
      setRecords((response.result?.items || []) as ModelTraceSummary[]);
      setError("");
    }
    setLoading(false);
  }, [activeAgentId, activeSessionId, sessionOnly, t]);

  const loadTrace = useCallback(async (traceId: string) => {
    if (!activeAgentId || !traceId) {
      setTrace(null);
      return;
    }
    setDetailLoading(true);
    const response = await window.gateway.getModelTrace({ agentId: activeAgentId, traceId });
    if (response.error) {
      setError(response.error.message || t("promptAnalysis.loadFailed"));
      setTrace(null);
    } else {
      setTrace((response.result?.trace || null) as ModelTraceRecord | null);
      setError("");
    }
    setDetailLoading(false);
  }, [activeAgentId, t]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => window.gateway.onEvent((event: { event?: string; agentId?: string }) => {
    if (event.agentId === activeAgentId && event.event?.startsWith("model.trace.")) void refresh();
  }), [activeAgentId, refresh]);
  useEffect(() => {
    if (!records.length) setSelectedTraceId("");
    else if (!records.some((record) => record.id === selectedTraceId)) setSelectedTraceId(records[0].id);
  }, [records, selectedTraceId]);
  useEffect(() => { void loadTrace(selectedTraceId); }, [loadTrace, selectedTraceId]);

  const sections = trace?.prompt_analysis?.sections || [];
  useEffect(() => {
    if (!sections.length) setSelectedSectionKey("");
    else if (!sections.some((section) => section.key === selectedSectionKey)) setSelectedSectionKey(sections[0].key);
  }, [sections, selectedSectionKey]);
  useEffect(() => { setTextExpanded(false); }, [selectedSectionKey, selectedTraceId]);
  const selectedSection = sections.find((section) => section.key === selectedSectionKey) || null;
  const analysis = trace?.prompt_analysis;
  const conditionalCount = useMemo(
    () => sections.filter((section) => section.present && section.injection === "conditional").length,
    [sections],
  );

  return (
    <section className="prompt-analysis" aria-label={t("promptAnalysis.title")}>
      <header className="prompt-analysis-header">
        <div>
          <span>{t("promptAnalysis.currentAgentSession", {
            name: activeAgent?.name || t("usage.agent"),
            session: activeSessionId || "—",
          })}</span>
          <h2>{t("promptAnalysis.title")}</h2>
          <p>{t("promptAnalysis.subtitle")}</p>
        </div>
        <div>
          <button type="button" onClick={() => void refresh()} title={t("common.refresh")}><Icon name="refresh" size={16} /></button>
          <button type="button" onClick={onClose} title={t("common.close")}><Icon name="x" size={16} /></button>
        </div>
      </header>
      <div className="prompt-analysis-toolbar">
        <label><input type="checkbox" checked={sessionOnly} onChange={(event) => setSessionOnly(event.target.checked)} />{t("promptAnalysis.currentSessionOnly")}</label>
        <span>{t("promptAnalysis.callCount", { count: records.length })}</span>
      </div>
      {error ? <div className="prompt-analysis-error">{error}</div> : null}
      <div className={`prompt-analysis-body${textExpanded ? " is-text-expanded" : ""}`}>
        <aside className="prompt-analysis-calls">
          <div className="prompt-analysis-column-title">{t("promptAnalysis.calls")}</div>
          {loading && records.length === 0 ? <Empty text={t("common.loading")} /> : null}
          {!loading && records.length === 0 ? <Empty text={t("promptAnalysis.empty")} /> : null}
          {records.map((record) => (
            <button
              key={record.id}
              type="button"
              className={record.id === selectedTraceId ? "active" : ""}
              aria-pressed={record.id === selectedTraceId}
              onClick={() => setSelectedTraceId(record.id)}
            >
              <strong>{cleanPrompt(record.prompt_preview) || t("promptAnalysis.internalCall")}</strong>
              <small><time>{formatTime(record.created_at)}</time><span>{record.model}</span></small>
            </button>
          ))}
        </aside>
        <nav className="prompt-analysis-sections">
          <div className="prompt-analysis-column-title">{t("promptAnalysis.sections")}</div>
          {detailLoading ? <Empty text={t("common.loading")} /> : null}
          {!detailLoading && analysis ? (
            <div className="prompt-analysis-summary">
              <strong>{formatTokens(analysis.system_tokens)}</strong>
              <span>{t("promptAnalysis.estimatedTokens")}</span>
              <em className={deltaClass(analysis.delta_tokens)}>{formatDelta(analysis.delta_tokens)}</em>
            </div>
          ) : null}
          {!detailLoading && sections.map((section) => (
            <button
              key={section.key}
              type="button"
              className={`${section.key === selectedSectionKey ? "active " : ""}change-${section.change}${section.present ? "" : " removed"}`}
              aria-pressed={section.key === selectedSectionKey}
              onClick={() => setSelectedSectionKey(section.key)}
            >
              <span><strong>{sectionLabel(section, t)}</strong><em>{t(`promptAnalysis.change.${section.change}`)}</em></span>
              <small><b>{formatTokens(section.tokens)}</b><i>{section.percentage.toFixed(1)}%</i><u className={deltaClass(section.delta_tokens)}>{formatDelta(section.delta_tokens)}</u></small>
            </button>
          ))}
        </nav>
        <main className="prompt-analysis-detail">
          {!selectedSection ? <Empty text={t("promptAnalysis.selectHint")} /> : (
            <SectionDetail section={selectedSection} textExpanded={textExpanded} onTextExpandedChange={setTextExpanded} />
          )}
        </main>
      </div>
    </section>
  );
}

function SectionDetail({ section, textExpanded, onTextExpandedChange }: {
  section: PromptAnalysisSection;
  textExpanded: boolean;
  onTextExpandedChange: (expanded: boolean) => void;
}) {
  const { t } = useTranslation();
  if (textExpanded) return <PromptTextComparison section={section} onClose={() => onTextExpandedChange(false)} />;
  return (
    <>
      <header className="prompt-analysis-detail-header">
        <div><span>{t("promptAnalysis.section")}</span><h3>{sectionLabel(section, t)}</h3></div>
        <div>
          <span className={`prompt-analysis-badge is-${section.injection}`}>{t(`promptAnalysis.injection.${section.injection}`)}</span>
          <span className={`prompt-analysis-badge is-${section.change}`}>{t(`promptAnalysis.change.${section.change}`)}</span>
        </div>
      </header>
      <div className="prompt-analysis-detail-content">
        <div className="prompt-analysis-metrics">
          <Metric label={t("promptAnalysis.tokens")} value={formatTokens(section.tokens)} />
          <Metric label={t("promptAnalysis.percentage")} value={`${section.percentage.toFixed(1)}%`} />
          <Metric label={t("promptAnalysis.previousTokens")} value={formatTokens(section.previous_tokens)} />
          <Metric label={t("promptAnalysis.delta")} value={formatDelta(section.delta_tokens)} className={deltaClass(section.delta_tokens)} />
        </div>
        <section className="prompt-analysis-card">
          <header>{t("promptAnalysis.source")}</header>
          <code>{section.source}</code>
          <strong>{section.symbol}</strong>
        </section>
        <section className="prompt-analysis-card">
          <header>{t("promptAnalysis.reason")}</header>
          <p>{section.reason}</p>
        </section>
        <section className="prompt-analysis-text-card">
          <header>
            <strong>{t("promptAnalysis.currentText")}</strong>
            <div>
              <span>{formatTokens(section.tokens)} tokens</span>
              <button type="button" onClick={() => onTextExpandedChange(true)} title={t("promptAnalysis.expandComparison")}>
                <Icon name="maximize" size={14} />
              </button>
            </div>
          </header>
          {section.text ? <pre>{section.text}</pre> : <p>{t("promptAnalysis.notPresent")}</p>}
        </section>
        {section.previous_text || section.change === "removed" ? (
          <section className="prompt-analysis-text-card is-previous">
            <header><strong>{t("promptAnalysis.previousText")}</strong><span>{formatTokens(section.previous_tokens)} tokens</span></header>
            {section.previous_text ? <pre>{section.previous_text}</pre> : <p>{t("promptAnalysis.noPrevious")}</p>}
          </section>
        ) : null}
      </div>
    </>
  );
}

function PromptTextComparison({ section, onClose }: { section: PromptAnalysisSection; onClose: () => void }) {
  const { t } = useTranslation();
  const comparison = useMemo(() => comparePromptLines(section.text || "", section.previous_text || ""), [section.previous_text, section.text]);
  return (
    <section className="prompt-analysis-comparison">
      <header>
        <div><span>{t("promptAnalysis.section")}</span><strong>{sectionLabel(section, t)}</strong></div>
        <button type="button" onClick={onClose} title={t("promptAnalysis.restoreLayout")}><Icon name="minimize" size={16} /></button>
      </header>
      <div className="prompt-analysis-comparison-grid">
        <ComparisonPane title={t("promptAnalysis.currentText")} tokens={section.tokens} lines={comparison.current} emptyText={t("promptAnalysis.notPresent")} />
        <ComparisonPane title={t("promptAnalysis.previousText")} tokens={section.previous_tokens} lines={comparison.previous} emptyText={t("promptAnalysis.noPrevious")} />
      </div>
    </section>
  );
}

function ComparisonPane({ title, tokens, lines, emptyText }: { title: string; tokens: number; lines: ComparedLine[]; emptyText: string }) {
  return (
    <section className="prompt-analysis-comparison-pane">
      <header><strong>{title}</strong><span>{formatTokens(tokens)} tokens</span></header>
      {lines.length ? (
        <div className="prompt-analysis-diff-lines">
          {lines.map((line, index) => <div key={`${index}-${line.kind}`} className={`is-${line.kind}`}><span>{index + 1}</span><code>{line.text || "\u00a0"}</code></div>)}
        </div>
      ) : <p>{emptyText}</p>}
    </section>
  );
}

type ComparedLine = { text: string; kind: "same" | "added" | "removed" };

function comparePromptLines(currentText: string, previousText: string): { current: ComparedLine[]; previous: ComparedLine[] } {
  const current = currentText ? currentText.split("\n") : [];
  const previous = previousText ? previousText.split("\n") : [];
  const matrix = Array.from({ length: previous.length + 1 }, () => new Uint32Array(current.length + 1));
  for (let oldIndex = previous.length - 1; oldIndex >= 0; oldIndex -= 1) {
    for (let newIndex = current.length - 1; newIndex >= 0; newIndex -= 1) {
      matrix[oldIndex][newIndex] = previous[oldIndex] === current[newIndex]
        ? matrix[oldIndex + 1][newIndex + 1] + 1
        : Math.max(matrix[oldIndex + 1][newIndex], matrix[oldIndex][newIndex + 1]);
    }
  }
  const samePrevious = new Set<number>();
  const sameCurrent = new Set<number>();
  let oldIndex = 0;
  let newIndex = 0;
  while (oldIndex < previous.length && newIndex < current.length) {
    if (previous[oldIndex] === current[newIndex]) {
      samePrevious.add(oldIndex);
      sameCurrent.add(newIndex);
      oldIndex += 1;
      newIndex += 1;
    } else if (matrix[oldIndex + 1][newIndex] >= matrix[oldIndex][newIndex + 1]) oldIndex += 1;
    else newIndex += 1;
  }
  return {
    current: current.map((text, index) => ({ text, kind: sameCurrent.has(index) ? "same" : "added" })),
    previous: previous.map((text, index) => ({ text, kind: samePrevious.has(index) ? "same" : "removed" })),
  };
}

function Metric({ label, value, className = "" }: { label: string; value: string; className?: string }) {
  return <div><span>{label}</span><strong className={className}>{value}</strong></div>;
}

function Empty({ text }: { text: string }) {
  return <div className="prompt-analysis-empty">{text}</div>;
}

function sectionLabel(section: PromptAnalysisSection, t: (key: string) => string): string {
  return section.key === "__other__" ? t("promptAnalysis.untagged") : `<${section.key}>`;
}

function cleanPrompt(value: string): string {
  const text = String(value || "").replace(/^<当前时间>[\s\S]*?<\/当前时间>\s*/, "").trim();
  return text.slice(0, 120);
}

function formatTime(timestamp: number): string {
  return timestamp ? new Date(timestamp * 1000).toLocaleString([], { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
}

function formatTokens(value: number): string {
  if (!value) return "0";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return String(value);
}

function formatDelta(value: number): string {
  if (!value) return "±0";
  return `${value > 0 ? "+" : "−"}${formatTokens(Math.abs(value))}`;
}

function deltaClass(value: number): string {
  return value > 0 ? "is-positive" : value < 0 ? "is-negative" : "is-neutral";
}
