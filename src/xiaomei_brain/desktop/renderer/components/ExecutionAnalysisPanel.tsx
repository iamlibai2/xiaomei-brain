import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useCoreStore } from "../store";
import type { ExecutionSelection, ModelTraceSummary } from "../types";
import { Icon } from "./ui";

interface ExecutionTurn {
  id: string;
  prompt: string;
  createdAt: number;
  status: ModelTraceSummary["status"];
  records: ModelTraceSummary[];
}

export function ExecutionAnalysisPanel({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const activeAgentId = useCoreStore((state) => state.activeAgentId || "");
  const activeAgent = useCoreStore((state) => state.agents.find((item) => item.id === state.activeAgentId));
  const activeSessionId = useCoreStore((state) => state.activeSessionByAgent[state.activeAgentId || ""] || "");
  const [records, setRecords] = useState<ModelTraceSummary[]>([]);
  const [selectedTurnId, setSelectedTurnId] = useState("");
  const [sessionOnly, setSessionOnly] = useState(true);
  const [loading, setLoading] = useState(false);
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
      setError(response.error.message || t("executionAnalysis.loadFailed"));
    } else {
      setRecords((response.result?.items || []) as ModelTraceSummary[]);
      setError("");
    }
    setLoading(false);
  }, [activeAgentId, activeSessionId, sessionOnly, t]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => window.gateway.onEvent((event: { event?: string; agentId?: string }) => {
    if (event.agentId === activeAgentId && event.event?.startsWith("model.trace.")) void refresh();
  }), [activeAgentId, refresh]);

  const turns = useMemo(() => groupByTurn(records), [records]);
  useEffect(() => {
    if (!turns.length) setSelectedTurnId("");
    else if (!turns.some((turn) => turn.id === selectedTurnId)) setSelectedTurnId(turns[0].id);
  }, [selectedTurnId, turns]);
  const selected = turns.find((turn) => turn.id === selectedTurnId) || null;

  return (
    <section className="execution-analysis" aria-label={t("executionAnalysis.title")}>
      <header className="execution-analysis-header">
        <div>
          <span>{t("executionAnalysis.currentAgentSession", {
            name: activeAgent?.name || t("usage.agent"),
            session: activeSessionId || "—",
          })}</span>
          <h2>{t("executionAnalysis.title")}</h2>
          <p>{t("executionAnalysis.subtitle")}</p>
        </div>
        <div>
          <button type="button" onClick={() => void refresh()} title={t("common.refresh")}><Icon name="refresh" size={16} /></button>
          <button type="button" onClick={onClose} title={t("common.close")}><Icon name="x" size={16} /></button>
        </div>
      </header>
      <div className="execution-analysis-toolbar">
        <label><input type="checkbox" checked={sessionOnly} onChange={(event) => setSessionOnly(event.target.checked)} />{t("executionAnalysis.currentSessionOnly")}</label>
        <span>{t("executionAnalysis.turnCount", { count: turns.length })}</span>
      </div>
      {error ? <div className="execution-analysis-error">{error}</div> : null}
      <div className="execution-analysis-body">
        <aside className="execution-analysis-turns">
          {loading && turns.length === 0 ? <div className="execution-analysis-empty">{t("common.loading")}</div> : null}
          {!loading && turns.length === 0 ? <div className="execution-analysis-empty">{t("executionAnalysis.empty")}</div> : null}
          {turns.map((turn) => (
            <button key={turn.id} className={turn.id === selectedTurnId ? "active" : ""} onClick={() => setSelectedTurnId(turn.id)}>
              <strong>{cleanPrompt(turn.prompt) || t("executionAnalysis.internalTurn")}</strong>
              <small><time>{formatTime(turn.createdAt)}</time><span>{t("executionAnalysis.stepCount", { count: turn.records.length })}</span></small>
            </button>
          ))}
        </aside>
        <main className="execution-analysis-detail">
          {!selected ? <div className="execution-analysis-empty">{t("executionAnalysis.selectHint")}</div> : <TurnExecution turn={selected} />}
        </main>
      </div>
    </section>
  );
}

function TurnExecution({ turn }: { turn: ExecutionTurn }) {
  const { t } = useTranslation();
  const firstSelection = turn.records.find((record) => record.execution_selection)?.execution_selection;
  const capability = firstSelection?.capability || {};
  const skills = uniqueSkills(turn.records.flatMap((record) => record.execution_selection?.skills || []));
  const calls = unique(turn.records.flatMap((record) => record.tool_call_names || []));
  return (
    <>
      <header className="execution-analysis-detail-header">
        <div><span>{t("executionAnalysis.turn")}</span><strong>{cleanPrompt(turn.prompt) || t("executionAnalysis.internalTurn")}</strong></div>
        <span className={`trace-status is-${turn.status}`}>{t(`modelTrace.status.${turn.status}`)}</span>
      </header>
      <div className="execution-analysis-content">
        <AnalysisSection title={t("executionAnalysis.capabilities")} hint={t("executionAnalysis.capabilitiesHint")}>
          <ChipList values={unique((capability.capabilities || []).map((item) => item.name || item.id))} empty={t("executionAnalysis.noneSelected")} />
          {(capability.tools || []).length || (capability.skills || []).length ? <div className="execution-analysis-dependencies"><span>{t("executionAnalysis.capabilityDependencies")}</span><ChipList values={unique([...(capability.skills || []), ...(capability.tools || [])])} empty="" /></div> : null}
        </AnalysisSection>
        <AnalysisSection title={t("executionAnalysis.skills")} hint={t("executionAnalysis.skillsHint")}>
          {skills.length ? <div className="execution-analysis-skill-list">{skills.map((skill) => <article key={skill.name}><strong>{skill.name}</strong><span>{t(`executionAnalysis.source.${skill.source || "semantic"}`)}</span><p>{skill.description || t("executionAnalysis.noDescription")}</p></article>)}</div> : <p className="execution-analysis-muted">{t("executionAnalysis.noneSelected")}</p>}
        </AnalysisSection>
        <AnalysisSection title={t("executionAnalysis.steps")} hint={t("executionAnalysis.stepsHint")}>
          <div className="execution-analysis-steps">{[...turn.records].reverse().map((record, index) => <ExecutionStep key={record.id} record={record} index={index + 1} />)}</div>
        </AnalysisSection>
        <AnalysisSection title={t("executionAnalysis.actualCalls")} hint={t("executionAnalysis.actualCallsHint")}>
          <ChipList values={calls} empty={t("executionAnalysis.noCalls")} emphasis />
        </AnalysisSection>
      </div>
    </>
  );
}

function ExecutionStep({ record, index }: { record: ModelTraceSummary; index: number }) {
  const { t } = useTranslation();
  const tools = record.execution_selection?.tools;
  const semantic = tools?.semantic || [];
  const required = tools?.required || [];
  const core = tools?.core || [];
  return <article><header><b>{index}</b><strong>{record.tool_call_names?.length ? t("executionAnalysis.called", { names: record.tool_call_names.join(", ") }) : t("executionAnalysis.responded")}</strong><time>{formatTime(record.created_at)}</time></header><div><ToolGroup label={t("executionAnalysis.coreTools")} values={core} /><ToolGroup label={t("executionAnalysis.requiredTools")} values={required} /><ToolGroup label={t("executionAnalysis.semanticTools")} values={semantic} /></div>{!tools ? <p>{t("executionAnalysis.legacyRecord")}</p> : null}</article>;
}

function AnalysisSection({ title, hint, children }: { title: string; hint: string; children: React.ReactNode }) {
  return <section className="execution-analysis-section"><header><strong>{title}</strong><span>{hint}</span></header>{children}</section>;
}
function ToolGroup({ label, values }: { label: string; values: string[] }) { return values.length ? <div className="execution-analysis-tool-group"><span>{label}</span><ChipList values={values} empty="" /></div> : null; }
function ChipList({ values, empty, emphasis = false }: { values: string[]; empty: string; emphasis?: boolean }) { return values.length ? <div className={`execution-analysis-chips${emphasis ? " is-emphasis" : ""}`}>{values.map((value) => <code key={value}>{value}</code>)}</div> : <p className="execution-analysis-muted">{empty}</p>; }
function groupByTurn(records: ModelTraceSummary[]): ExecutionTurn[] { const groups = new Map<string, ExecutionTurn>(); records.forEach((record) => { const id = record.turn_id || record.id; const group = groups.get(id) || { id, prompt: record.prompt_preview || "", createdAt: record.created_at, status: record.status, records: [] }; group.records.push(record); group.prompt ||= record.prompt_preview || ""; group.createdAt = Math.min(group.createdAt, record.created_at); if (record.status === "running" || (record.status === "failed" && group.status !== "running")) group.status = record.status; groups.set(id, group); }); return [...groups.values()]; }
function unique(values: string[]): string[] { return [...new Set(values.filter(Boolean))]; }
function uniqueSkills(values: NonNullable<ExecutionSelection["skills"]>): NonNullable<ExecutionSelection["skills"]> { const result = new Map<string, NonNullable<ExecutionSelection["skills"]>[number]>(); values.forEach((item) => { if (item.name && !result.has(item.name)) result.set(item.name, item); }); return [...result.values()]; }
function cleanPrompt(value: string): string { return String(value || "").replace(/^\[[\d\s:/.-]+]\s*/, "").trim(); }
function formatTime(value: number): string { return value ? new Date(value * 1000).toLocaleString([], { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—"; }
