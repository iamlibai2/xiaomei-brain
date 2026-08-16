import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Icon, type IconName } from "../ui";

interface Props {
  agentId: string;
  connected: boolean;
}

type RhythmValues = {
  idle_after_minutes: number;
  sleep_after_idle_minutes: number;
  dream_after_minutes: number;
  dream_interval_minutes: number;
  dream_report: boolean;
  intent_decision_enabled: boolean;
  intent_min_interval_minutes: number;
  intent_periodic_interval_minutes: number;
  intent_idle_trigger_minutes: number;
  intent_belonging_threshold_percent: number;
  intent_cognition_threshold_percent: number;
  intent_achievement_threshold_percent: number;
  intent_expression_threshold_percent: number;
  emergence_enabled: boolean;
  emergence_min_interval_minutes: number;
  emergence_periodic_interval_minutes: number;
  emergence_changes_trigger: number;
  emergence_energy_threshold_percent: number;
};

type RhythmResult = {
  values?: RhythmValues;
  revision?: string;
  restart_required?: boolean;
};

const DEFAULT_VALUES: RhythmValues = {
  idle_after_minutes: 5,
  sleep_after_idle_minutes: 180,
  dream_after_minutes: 5,
  dream_interval_minutes: 50,
  dream_report: true,
  intent_decision_enabled: true,
  intent_min_interval_minutes: 5,
  intent_periodic_interval_minutes: 30,
  intent_idle_trigger_minutes: 5,
  intent_belonging_threshold_percent: 60,
  intent_cognition_threshold_percent: 60,
  intent_achievement_threshold_percent: 50,
  intent_expression_threshold_percent: 60,
  emergence_enabled: true,
  emergence_min_interval_minutes: 10,
  emergence_periodic_interval_minutes: 30,
  emergence_changes_trigger: 5,
  emergence_energy_threshold_percent: 20,
};

export function AgentRhythmSettingsPanel({ agentId, connected }: Props) {
  const { t } = useTranslation();
  const [saved, setSaved] = useState(DEFAULT_VALUES);
  const [draft, setDraft] = useState(DEFAULT_VALUES);
  const [revision, setRevision] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const dirty = useMemo(
    () => JSON.stringify(saved) !== JSON.stringify(draft),
    [draft, saved],
  );

  const applyResult = useCallback((result: RhythmResult | undefined) => {
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
      const response = await window.gateway.getAgentConfig({ agentId, section: "rhythm" });
      if (response.error) throw new Error(response.error.message);
      applyResult(response.result as RhythmResult | undefined);
    } catch (loadError) {
      setError(String(loadError instanceof Error ? loadError.message : loadError));
    } finally {
      setBusy("");
    }
  }, [agentId, applyResult, connected]);

  useEffect(() => { void load(); }, [load]);

  async function save() {
    if (!dirty || busy) return;
    setBusy("save");
    setError("");
    setNotice("");
    try {
      const response = await window.gateway.updateAgentConfig({
        agentId,
        section: "rhythm",
        values: draft,
        revision,
      });
      if (response.error) throw new Error(response.error.message);
      applyResult(response.result as RhythmResult | undefined);
      setNotice(t("rhythmSettingsUi.saved"));
    } catch (saveError) {
      setError(String(saveError instanceof Error ? saveError.message : saveError));
    } finally {
      setBusy("");
    }
  }

  async function reset() {
    if (busy) return;
    setBusy("reset");
    setError("");
    setNotice("");
    try {
      const response = await window.gateway.resetAgentConfig({
        agentId,
        section: "rhythm",
        revision,
      });
      if (response.error) throw new Error(response.error.message);
      applyResult(response.result as RhythmResult | undefined);
      setNotice(t("rhythmSettingsUi.resetDone"));
    } catch (resetError) {
      setError(String(resetError instanceof Error ? resetError.message : resetError));
    } finally {
      setBusy("");
    }
  }

  function updateNumber(key: keyof RhythmValues, value: number) {
    if (!Number.isFinite(value)) return;
    setDraft((current) => ({ ...current, [key]: value }));
    setNotice("");
  }

  function updateBoolean(key: keyof RhythmValues, value: boolean) {
    setDraft((current) => ({ ...current, [key]: value }));
    setNotice("");
  }

  if (!connected) {
    return <div className="settings-empty">{t("rhythmSettingsUi.connectToView")}</div>;
  }
  if (busy === "load") {
    return <div className="settings-empty">{t("rhythmSettingsUi.loading")}</div>;
  }

  return (
    <div className="agent-rhythm-settings">
      <header className="model-page-heading">
        <div>
          <h2>{t("rhythmSettingsUi.title")}</h2>
          <p>{t("rhythmSettingsUi.description")}</p>
        </div>
      </header>

      <section className="settings-card">
        <div className="settings-card-heading">
          <div>
            <h3>{t("rhythmSettingsUi.lifecycleTitle")}</h3>
            <p>{t("rhythmSettingsUi.lifecycleHint")}</p>
          </div>
        </div>
        <div className="rhythm-lifecycle-summary">
          <span>{t("rhythmSettingsUi.awakeState")}</span>
          <Icon name="chevron-right" size={14} />
          <span>{t("rhythmSettingsUi.idleState", { minutes: draft.idle_after_minutes })}</span>
          <Icon name="chevron-right" size={14} />
          <span>{t("rhythmSettingsUi.sleepState", { hours: Number((draft.sleep_after_idle_minutes / 60).toFixed(2)) })}</span>
          <Icon name="chevron-right" size={14} />
          <span>{t("rhythmSettingsUi.dreamState", { minutes: draft.dream_after_minutes })}</span>
        </div>
        <DurationRow
          icon="clock"
          title={t("rhythmSettingsUi.idleAfter")}
          description={t("rhythmSettingsUi.idleAfterHint")}
          value={draft.idle_after_minutes}
          unit={t("rhythmSettingsUi.minutes")}
          min={0.5}
          max={1440}
          onChange={(value) => updateNumber("idle_after_minutes", value)}
        />
        <DurationRow
          icon="moon"
          title={t("rhythmSettingsUi.sleepAfter")}
          description={t("rhythmSettingsUi.sleepAfterHint")}
          value={draft.sleep_after_idle_minutes / 60}
          unit={t("rhythmSettingsUi.hours")}
          min={1 / 60}
          max={168}
          onChange={(value) => updateNumber("sleep_after_idle_minutes", value * 60)}
        />
        <DurationRow
          icon="sparkles"
          title={t("rhythmSettingsUi.dreamAfter")}
          description={t("rhythmSettingsUi.dreamAfterHint")}
          value={draft.dream_after_minutes}
          unit={t("rhythmSettingsUi.minutes")}
          min={0.5}
          max={1440}
          onChange={(value) => updateNumber("dream_after_minutes", value)}
        />
        <DurationRow
          icon="clock"
          title={t("rhythmSettingsUi.dreamInterval")}
          description={t("rhythmSettingsUi.dreamIntervalHint")}
          value={draft.dream_interval_minutes}
          unit={t("rhythmSettingsUi.minutes")}
          min={1}
          max={10080}
          onChange={(value) => updateNumber("dream_interval_minutes", value)}
        />
        <SwitchRow
          icon="moon"
          title={t("rhythmSettingsUi.dreamReport")}
          description={t("rhythmSettingsUi.dreamReportHint")}
          checked={draft.dream_report}
          onChange={(value) => updateBoolean("dream_report", value)}
        />
      </section>

      <section className="settings-card">
        <div className="settings-card-heading">
          <div>
            <h3>{t("rhythmSettingsUi.intentTitle")}</h3>
            <p>{t("rhythmSettingsUi.intentHint")}</p>
          </div>
        </div>
        <SwitchRow
          icon="sparkles"
          title={t("rhythmSettingsUi.intentEnabled")}
          description={t("rhythmSettingsUi.intentEnabledHint")}
          checked={draft.intent_decision_enabled}
          onChange={(value) => updateBoolean("intent_decision_enabled", value)}
        />
        <DurationRow
          icon="clock"
          title={t("rhythmSettingsUi.intentMinInterval")}
          description={t("rhythmSettingsUi.intentMinIntervalHint")}
          value={draft.intent_min_interval_minutes}
          unit={t("rhythmSettingsUi.minutes")}
          min={0.5}
          max={1440}
          onChange={(value) => updateNumber("intent_min_interval_minutes", value)}
        />
        <DurationRow
          icon="clock"
          title={t("rhythmSettingsUi.intentPeriodic")}
          description={t("rhythmSettingsUi.intentPeriodicHint", {
            minutes: Math.max(
              draft.intent_min_interval_minutes,
              draft.intent_periodic_interval_minutes,
            ),
          })}
          value={draft.intent_periodic_interval_minutes}
          unit={t("rhythmSettingsUi.minutes")}
          min={1}
          max={10080}
          onChange={(value) => updateNumber("intent_periodic_interval_minutes", value)}
        />
        <DurationRow
          icon="clock"
          title={t("rhythmSettingsUi.intentIdle")}
          description={t("rhythmSettingsUi.intentIdleHint")}
          value={draft.intent_idle_trigger_minutes}
          unit={t("rhythmSettingsUi.minutes")}
          min={0.5}
          max={10080}
          onChange={(value) => updateNumber("intent_idle_trigger_minutes", value)}
        />
        <div className="rhythm-thresholds">
          <div className="rhythm-thresholds-heading">
            <strong>{t("rhythmSettingsUi.intentDesireTitle")}</strong>
            <p>{t("rhythmSettingsUi.intentDesireHint")}</p>
          </div>
          <div className="rhythm-threshold-grid">
            <ThresholdRow
              label={t("rhythmSettingsUi.belonging")}
              value={draft.intent_belonging_threshold_percent}
              onChange={(value) => updateNumber("intent_belonging_threshold_percent", value)}
            />
            <ThresholdRow
              label={t("rhythmSettingsUi.cognition")}
              value={draft.intent_cognition_threshold_percent}
              onChange={(value) => updateNumber("intent_cognition_threshold_percent", value)}
            />
            <ThresholdRow
              label={t("rhythmSettingsUi.achievement")}
              value={draft.intent_achievement_threshold_percent}
              onChange={(value) => updateNumber("intent_achievement_threshold_percent", value)}
            />
            <ThresholdRow
              label={t("rhythmSettingsUi.expression")}
              value={draft.intent_expression_threshold_percent}
              onChange={(value) => updateNumber("intent_expression_threshold_percent", value)}
            />
          </div>
        </div>
      </section>

      <section className="settings-card">
        <div className="settings-card-heading">
          <div>
            <h3>{t("rhythmSettingsUi.emergenceTitle")}</h3>
            <p>{t("rhythmSettingsUi.emergenceHint")}</p>
          </div>
        </div>
        <SwitchRow
          icon="sparkles"
          title={t("rhythmSettingsUi.emergenceEnabled")}
          description={t("rhythmSettingsUi.emergenceEnabledHint")}
          checked={draft.emergence_enabled}
          onChange={(value) => updateBoolean("emergence_enabled", value)}
        />
        <DurationRow
          icon="clock"
          title={t("rhythmSettingsUi.emergenceMinInterval")}
          description={t("rhythmSettingsUi.emergenceMinIntervalHint")}
          value={draft.emergence_min_interval_minutes}
          unit={t("rhythmSettingsUi.minutes")}
          min={0.5}
          max={1440}
          onChange={(value) => updateNumber("emergence_min_interval_minutes", value)}
        />
        <DurationRow
          icon="clock"
          title={t("rhythmSettingsUi.emergencePeriodic")}
          description={t("rhythmSettingsUi.emergencePeriodicHint", {
            minutes: Math.max(
              draft.emergence_min_interval_minutes,
              draft.emergence_periodic_interval_minutes,
            ),
          })}
          value={draft.emergence_periodic_interval_minutes}
          unit={t("rhythmSettingsUi.minutes")}
          min={1}
          max={10080}
          onChange={(value) => updateNumber("emergence_periodic_interval_minutes", value)}
        />
        <DurationRow
          icon="sparkles"
          title={t("rhythmSettingsUi.emergenceChanges")}
          description={t("rhythmSettingsUi.emergenceChangesHint")}
          value={draft.emergence_changes_trigger}
          unit={t("rhythmSettingsUi.items")}
          min={1}
          max={30}
          onChange={(value) => updateNumber("emergence_changes_trigger", value)}
        />
        <div className="rhythm-thresholds">
          <div className="rhythm-thresholds-heading">
            <strong>{t("rhythmSettingsUi.emergenceEnergy")}</strong>
            <p>{t("rhythmSettingsUi.emergenceEnergyHint")}</p>
          </div>
          <div className="rhythm-threshold-grid">
            <ThresholdRow
              label={t("rhythmSettingsUi.energy")}
              value={draft.emergence_energy_threshold_percent}
              onChange={(value) => updateNumber("emergence_energy_threshold_percent", value)}
            />
          </div>
        </div>
      </section>

      {error ? <div className="settings-message error">{error}</div> : null}
      {notice ? <div className="settings-message success">{notice}</div> : null}
      <div className="rhythm-settings-actions">
        <Button variant="ghost" onClick={() => void reset()} disabled={Boolean(busy)}>
          {busy === "reset" ? t("rhythmSettingsUi.resetting") : t("rhythmSettingsUi.reset")}
        </Button>
        <Button variant="primary" onClick={() => void save()} disabled={!dirty || Boolean(busy)}>
          {busy === "save" ? t("rhythmSettingsUi.saving") : t("rhythmSettingsUi.save")}
        </Button>
      </div>
    </div>
  );
}

function DurationRow(props: {
  icon: IconName;
  title: string;
  description: string;
  value: number;
  unit: string;
  min: number;
  max: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="desktop-setting-row">
      <span className="desktop-setting-icon"><Icon name={props.icon} size={16} /></span>
      <div className="desktop-setting-copy">
        <strong>{props.title}</strong>
        <p>{props.description}</p>
      </div>
      <label className="rhythm-duration-control">
        <input
          type="number"
          min={props.min}
          max={props.max}
          value={Number.isInteger(props.value) ? props.value : Number(props.value.toFixed(2))}
          onChange={(event) => props.onChange(Number(event.target.value))}
        />
        <span>{props.unit}</span>
      </label>
    </div>
  );
}

function SwitchRow(props: {
  icon: IconName;
  title: string;
  description: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div className="desktop-setting-row">
      <span className="desktop-setting-icon"><Icon name={props.icon} size={16} /></span>
      <div className="desktop-setting-copy">
        <strong>{props.title}</strong>
        <p>{props.description}</p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={props.checked}
        className={`desktop-switch ${props.checked ? "is-on" : ""}`}
        onClick={() => props.onChange(!props.checked)}
      ><span /></button>
    </div>
  );
}

function ThresholdRow(props: {
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="rhythm-threshold-control">
      <span>{props.label}</span>
      <span className="rhythm-threshold-input">
        <input
          type="number"
          min={0}
          max={100}
          value={Number.isInteger(props.value) ? props.value : Number(props.value.toFixed(1))}
          onChange={(event) => props.onChange(Number(event.target.value))}
        />
        <span>%</span>
      </span>
    </label>
  );
}
