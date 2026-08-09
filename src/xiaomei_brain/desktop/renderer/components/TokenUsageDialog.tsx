import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useCoreStore } from "../store";
import { formatTokens, useTokenUsage } from "../usage";
import { Icon } from "./ui";

type Period = "today" | "seven_days" | "month";

export function TokenUsageDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const [period, setPeriod] = useState<Period>("today");
  const activeAgentId = useCoreStore((state) => state.activeAgentId || "");
  const activeAgent = useCoreStore((state) => state.agents.find((item) => item.id === state.activeAgentId));
  const sessionId = useCoreStore((state) => state.activeSessionByAgent[state.activeAgentId || ""] || "");
  const { summary, loading, error, refresh } = useTokenUsage(activeAgentId, sessionId, true);
  const totals = summary?.periods[period];
  const breakdown = summary?.breakdowns?.[period];
  const categories = breakdown?.categories || summary?.categories || [];
  const categoryTotal = Math.max(1, totals?.total_tokens || 0);
  const periodLabel = t(`usage.period.${period}`);
  const firstRecorded = summary?.first_recorded_at
    ? new Date(summary.first_recorded_at * 1000).toLocaleString()
    : "";
  const models = useMemo(
    () => breakdown?.models || summary?.models || [],
    [breakdown, summary],
  );

  return (
    <div className="usage-dialog-backdrop" onMouseDown={onClose}>
      <section className="usage-dialog" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
        <header className="usage-dialog-header">
          <div>
            <span className="usage-dialog-eyebrow">{activeAgent?.name || t("usage.agent")}</span>
            <h2>{t("usage.title")}</h2>
            <p>{t("usage.subtitle")}</p>
          </div>
          <div className="usage-dialog-header-actions">
            <button type="button" onClick={() => void refresh()} title={t("common.refresh")}>
              <Icon name="refresh" size={16} />
            </button>
            <button type="button" onClick={onClose} title={t("common.close")}>
              <Icon name="x" size={16} />
            </button>
          </div>
        </header>

        <div className="usage-period-tabs">
          {(["today", "seven_days", "month"] as Period[]).map((item) => (
            <button key={item} className={period === item ? "active" : ""} onClick={() => setPeriod(item)}>
              {t(`usage.period.${item}`)}
            </button>
          ))}
        </div>

        {loading && !summary ? <div className="usage-dialog-state">{t("usage.loading")}</div> : null}
        {error ? <div className="usage-dialog-state is-error">{error}</div> : null}
        {summary && totals ? (
          <div className="usage-dialog-body">
            <section className="usage-hero-card">
              <span>{periodLabel}</span>
              <strong>{formatTokens(totals.total_tokens)}</strong>
              <div className="usage-hero-details">
                <Metric label={t("usage.input")} value={formatTokens(totals.input_tokens)} />
                <Metric label={t("usage.output")} value={formatTokens(totals.output_tokens)} />
                <Metric label={t("usage.calls")} value={String(totals.calls)} />
                <Metric label={t("usage.cached")} value={formatTokens(totals.cached_input_tokens)} />
              </div>
              {totals.estimated_calls > 0 && (
                <small>{t("usage.estimatedNotice", { count: totals.estimated_calls })}</small>
              )}
            </section>

            <div className="usage-grid">
              <section className="usage-card">
                <h3>{t("usage.inputComposition")}</h3>
                <div className="usage-breakdown-list">
                  {([
                    ["messages", totals.message_input_tokens],
                    ["system", totals.system_input_tokens],
                    ["tools", totals.tool_input_tokens],
                    ["skills", totals.skill_input_tokens],
                    ["workspace", totals.workspace_input_tokens],
                  ] as Array<[string, number]>).map(([name, value]) => {
                    const width = Math.max(3, Math.round((value / Math.max(1, totals.input_tokens)) * 100));
                    return (
                      <div className="usage-breakdown" key={name}>
                        <div><span>{t(`usage.component.${name}`)}</span><strong>{formatTokens(value)}</strong></div>
                        <span className="usage-breakdown-track"><i style={{ width: `${width}%` }} /></span>
                      </div>
                    );
                  })}
                </div>
              </section>
              <section className="usage-card">
                <h3>{t("usage.byCategory")}</h3>
                <div className="usage-breakdown-list">
                  {categories.length === 0 ? <p>{t("usage.empty")}</p> : categories.map((item) => {
                    const width = Math.max(3, Math.round((item.total_tokens / categoryTotal) * 100));
                    return (
                      <div className="usage-breakdown" key={item.category}>
                        <div><span>{t(`usage.category.${item.category || "other"}`)}</span><strong>{formatTokens(item.total_tokens)}</strong></div>
                        <span className="usage-breakdown-track"><i style={{ width: `${width}%` }} /></span>
                      </div>
                    );
                  })}
                </div>
              </section>

              <section className="usage-card">
                <h3>{t("usage.byModel")}</h3>
                <div className="usage-model-list">
                  {models.length === 0 ? <p>{t("usage.empty")}</p> : models.map((item) => (
                    <div key={`${item.provider}/${item.model}`}>
                      <span>{item.model || item.provider}</span>
                      <strong>{formatTokens(item.total_tokens)}</strong>
                      <small>{t("usage.callCount", { count: item.calls })}</small>
                    </div>
                  ))}
                </div>
              </section>
            </div>

            <section className="usage-session-card">
              <div>
                <span>{t("usage.currentSession")}</span>
                <strong>{formatTokens(summary.current_session.total_tokens)}</strong>
              </div>
              <div>
                <span>{t("usage.sessionCalls")}</span>
                <strong>{summary.current_session.calls}</strong>
              </div>
            </section>

            <footer className="usage-dialog-footer">
              {firstRecorded ? t("usage.since", { value: firstRecorded }) : t("usage.noRecords")}
            </footer>
          </div>
        ) : null}
      </section>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}
