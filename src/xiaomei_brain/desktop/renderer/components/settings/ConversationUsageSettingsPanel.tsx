import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Icon, type IconName } from "../ui";

interface Props { agentId: string; connected: boolean }

type Values = {
  daily_token_budget: number;
  monthly_token_budget: number;
  daily_token_reset_hour: number;
  fresh_tail_count: number;
  flow_tail_count: number;
  reflect_tail_count: number;
};

type Result = { values?: Values; revision?: string };

const DEFAULT_VALUES: Values = {
  daily_token_budget: 0,
  monthly_token_budget: 0,
  daily_token_reset_hour: 4,
  fresh_tail_count: 40,
  flow_tail_count: 4,
  reflect_tail_count: 12,
};

export function ConversationUsageSettingsPanel({ agentId, connected }: Props) {
  const { t } = useTranslation();
  const [saved, setSaved] = useState(DEFAULT_VALUES);
  const [draft, setDraft] = useState(DEFAULT_VALUES);
  const [revision, setRevision] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const dirty = useMemo(() => JSON.stringify(saved) !== JSON.stringify(draft), [draft, saved]);

  const applyResult = useCallback((result?: Result) => {
    const values = result?.values || DEFAULT_VALUES;
    setSaved({ ...values });
    setDraft({ ...values });
    setRevision(result?.revision || "");
  }, []);

  const load = useCallback(async () => {
    if (!agentId || !connected) return;
    setBusy("load");
    setError("");
    try {
      const response = await window.gateway.getAgentConfig({ agentId, section: "conversation" });
      if (response.error) throw new Error(response.error.message);
      applyResult(response.result as Result | undefined);
    } catch (cause) {
      setError(String(cause instanceof Error ? cause.message : cause));
    } finally {
      setBusy("");
    }
  }, [agentId, applyResult, connected]);

  useEffect(() => { void load(); }, [load]);

  const change = (key: keyof Values, value: number) => {
    if (!Number.isFinite(value)) return;
    setDraft((current) => ({ ...current, [key]: Math.max(0, Math.trunc(value)) }));
    setNotice("");
  };

  async function save() {
    if (!dirty || busy) return;
    setBusy("save"); setError(""); setNotice("");
    try {
      const response = await window.gateway.updateAgentConfig({
        agentId, section: "conversation", values: draft, revision,
      });
      if (response.error) throw new Error(response.error.message);
      applyResult(response.result as Result | undefined);
      setNotice(t("conversationSettingsUi.saved"));
    } catch (cause) {
      setError(String(cause instanceof Error ? cause.message : cause));
    } finally { setBusy(""); }
  }

  async function reset() {
    if (busy) return;
    setBusy("reset"); setError(""); setNotice("");
    try {
      const response = await window.gateway.resetAgentConfig({
        agentId, section: "conversation", revision,
      });
      if (response.error) throw new Error(response.error.message);
      applyResult(response.result as Result | undefined);
      setNotice(t("conversationSettingsUi.resetDone"));
    } catch (cause) {
      setError(String(cause instanceof Error ? cause.message : cause));
    } finally { setBusy(""); }
  }

  if (!connected) return <div className="settings-empty">{t("conversationSettingsUi.connectToView")}</div>;
  if (busy === "load") return <div className="settings-empty">{t("conversationSettingsUi.loading")}</div>;

  return (
    <div className="agent-rhythm-settings">
      <header className="model-page-heading"><div>
        <h2>{t("conversationSettingsUi.title")}</h2>
        <p>{t("conversationSettingsUi.description")}</p>
      </div></header>
      <section className="settings-card">
        <div className="settings-card-heading"><div>
          <h3>{t("conversationSettingsUi.budgetTitle")}</h3>
          <p>{t("conversationSettingsUi.budgetHint")}</p>
        </div></div>
        <NumberRow icon="chart-bar" title={t("conversationSettingsUi.dailyBudget")} description={t("conversationSettingsUi.dailyBudgetHint")} value={draft.daily_token_budget} unit="Token" onChange={(v) => change("daily_token_budget", v)} />
        <NumberRow icon="chart-bar" title={t("conversationSettingsUi.monthlyBudget")} description={t("conversationSettingsUi.monthlyBudgetHint")} value={draft.monthly_token_budget} unit="Token" onChange={(v) => change("monthly_token_budget", v)} />
        <NumberRow icon="clock" title={t("conversationSettingsUi.resetHour")} description={t("conversationSettingsUi.resetHourHint")} value={draft.daily_token_reset_hour} unit={t("conversationSettingsUi.hour")} max={23} onChange={(v) => change("daily_token_reset_hour", v)} />
      </section>
      <section className="settings-card">
        <div className="settings-card-heading"><div>
          <h3>{t("conversationSettingsUi.retentionTitle")}</h3>
          <p>{t("conversationSettingsUi.retentionHint")}</p>
        </div></div>
        <NumberRow icon="file-text" title={t("conversationSettingsUi.dailyTail")} description={t("conversationSettingsUi.dailyTailHint")} value={draft.fresh_tail_count} unit={t("conversationSettingsUi.messages")} onChange={(v) => change("fresh_tail_count", v)} />
        <NumberRow icon="file-text" title={t("conversationSettingsUi.flowTail")} description={t("conversationSettingsUi.flowTailHint")} value={draft.flow_tail_count} unit={t("conversationSettingsUi.messages")} onChange={(v) => change("flow_tail_count", v)} />
        <NumberRow icon="file-text" title={t("conversationSettingsUi.reflectTail")} description={t("conversationSettingsUi.reflectTailHint")} value={draft.reflect_tail_count} unit={t("conversationSettingsUi.messages")} onChange={(v) => change("reflect_tail_count", v)} />
      </section>
      {error ? <div className="settings-message error">{error}</div> : null}
      {notice ? <div className="settings-message success">{notice}</div> : null}
      <div className="rhythm-settings-actions">
        <Button variant="ghost" onClick={() => void reset()} disabled={Boolean(busy)}>{busy === "reset" ? t("conversationSettingsUi.resetting") : t("conversationSettingsUi.reset")}</Button>
        <Button variant="primary" onClick={() => void save()} disabled={!dirty || Boolean(busy)}>{busy === "save" ? t("conversationSettingsUi.saving") : t("conversationSettingsUi.save")}</Button>
      </div>
    </div>
  );
}

function NumberRow(props: { icon: IconName; title: string; description: string; value: number; unit: string; max?: number; onChange: (value: number) => void }) {
  return <div className="desktop-setting-row">
    <span className="desktop-setting-icon"><Icon name={props.icon} size={16} /></span>
    <div className="desktop-setting-copy"><strong>{props.title}</strong><p>{props.description}</p></div>
    <label className="rhythm-duration-control">
      <input type="number" min={0} max={props.max} value={props.value} onChange={(event) => props.onChange(Number(event.target.value))} />
      <span>{props.unit}</span>
    </label>
  </div>;
}
