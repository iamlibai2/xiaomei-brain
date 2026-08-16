import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useCoreStore } from "../store";
import type {
  BrainActivitySnapshot,
  BrainBodySnapshot,
  BrainMetric,
  BrainSnapshot,
} from "../types";
import { Icon } from "./ui";

type TrendPoint = { at: number; value: number };
type Trends = Record<string, TrendPoint[]>;

export function BrainPanel({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const agentId = useCoreStore((state) => state.activeAgentId || "");
  const agentName = useCoreStore((state) => (
    state.connectionByAgent[state.activeAgentId || ""]?.agentName
    || state.agents.find((item) => item.id === state.activeAgentId)?.name
    || state.activeAgentId
    || "Agent"
  ));
  const [brain, setBrain] = useState<BrainSnapshot | null>(null);
  const brainRef = useRef<BrainSnapshot | null>(null);
  const [trends, setTrends] = useState<Trends>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { brainRef.current = brain; }, [brain]);

  const watch = useCallback(async () => {
    if (!agentId) return;
    setLoading(true);
    const response = await window.gateway.watchBrain({ agentId });
    const snapshot = response.result?.brain as BrainSnapshot | undefined;
    if (response.error || !snapshot) {
      setError(response.error?.message || t("brainUi.loadFailed"));
    } else {
      setBrain(snapshot);
      setTrends(seedTrends(snapshot.body, snapshot.observed_at));
      setError("");
    }
    setLoading(false);
  }, [agentId, t]);

  useEffect(() => {
    void watch();
    return () => {
      if (agentId) void window.gateway.unwatchBrain({ agentId });
    };
  }, [agentId, watch]);

  useEffect(() => window.gateway.onEvent((event: {
    event?: string;
    agentId?: string;
    data?: unknown;
  }) => {
    if (event.agentId !== agentId || event.event !== "brain.changed") return;
    const payload = event.data && typeof event.data === "object"
      ? event.data as { revision?: number; observed_at?: number; changed?: Partial<BrainSnapshot> }
      : {};
    const current = brainRef.current;
    if (!current || !payload.revision || payload.revision !== current.revision + 1) {
      void watch();
      return;
    }
    const next = {
      ...current,
      ...(payload.changed || {}),
      revision: payload.revision,
      observed_at: payload.observed_at || Date.now() / 1000,
    } as BrainSnapshot;
    setBrain(next);
    appendTrendSample(setTrends, next.body, next.observed_at);
  }), [agentId, watch]);

  // Extend unchanged values as a truthful flat line while the page is open.
  // This is renderer-only chart sampling and never drives Agent state.
  useEffect(() => {
    const timer = window.setInterval(() => {
      const current = brainRef.current;
      if (current?.body) appendTrendSample(setTrends, current.body, Date.now() / 1000);
    }, 1_000);
    return () => window.clearInterval(timer);
  }, []);

  const current = brain?.current_activity || null;
  const secondary = (brain?.active_activities || []).filter((item) => (
    item.status === "running" && item.id !== current?.id
  ));
  const recent = (brain?.recent_activities || []).filter((item) => (
    item.status !== "running"
  )).slice(0, 16);

  return <section className="brain-panel" aria-label={t("brainUi.title")}>
    <header className="brain-header">
      <div className="brain-title">
        <span>{t("brainUi.currentAgent", { name: agentName })}</span>
        <h2>{t("brainUi.title")}</h2>
        <p>{t("brainUi.subtitle")}</p>
      </div>
      <div className="brain-header-state">
        {brain ? <>
          <i className={`brain-live-dot is-${brain.living.living || "unknown"}`} />
          <span>{livingName(brain.living.living, t)}</span>
          <time>{formatClock(brain.observed_at)}</time>
        </> : null}
        <button type="button" onClick={() => void watch()} title={t("common.refresh")}><Icon name="refresh" size={16} /></button>
        <button type="button" onClick={onClose} title={t("common.close")}><Icon name="x" size={16} /></button>
      </div>
    </header>

    {error ? <div className="brain-error">{error}</div> : null}
    {loading && !brain ? <div className="brain-loading"><span /><p>{t("brainUi.loading")}</p></div> : null}
    {!loading && !brain && !error ? <div className="brain-loading"><p>{t("brainUi.empty")}</p></div> : null}

    {brain ? <div className="brain-body">
      <main className="brain-activity-column">
        <section className="brain-now">
          <SectionTitle eyebrow={t("brainUi.nowEyebrow")} title={t("brainUi.doing")} />
          {current ? <CurrentActivity activity={current} /> : <div className="brain-quiet">
            <span className="brain-quiet-orbit"><i /></span>
            <div><strong>{t("brainUi.noCurrent")}</strong><p>{brain.living.focus_summary || t("brainUi.noCurrentHint")}</p></div>
          </div>}
          {secondary.length ? <div className="brain-secondary-activities">
            {secondary.slice(0, 4).map((item) => <ActivityStrip key={item.id} activity={item} />)}
          </div> : null}
        </section>

        <section className="brain-intents">
          <SectionTitle eyebrow={t("brainUi.intentEyebrow")} title={t("brainUi.wants")} count={brain.pending_intents.length} />
          {brain.pending_intents.length ? <div className="brain-intent-list">
            {brain.pending_intents.map((intent) => <article key={intent.id || `${intent.type}-${intent.created_at}`}>
              <i />
              <div><strong>{intent.content || intentName(intent.type, t)}</strong><small>{intentName(intent.type, t)} · {scopeName(intent.scope_type, t)} · {relativeTime(intent.created_at, t)}</small></div>
              <span>{intent.priority}</span>
            </article>)}
          </div> : <p className="brain-section-empty">{t("brainUi.noIntent")}</p>}
        </section>

        <section className="brain-stream">
          <SectionTitle eyebrow={t("brainUi.streamEyebrow")} title={t("brainUi.recentActivity")} />
          <div className="brain-timeline">
            {recent.length ? recent.map((item) => <TimelineItem key={item.id} activity={item} />) : <p className="brain-section-empty">{t("brainUi.noRecent")}</p>}
          </div>
        </section>
      </main>

      <aside className="brain-monitor-column">
        <section className="brain-monitor-head">
          <div><span>{t("brainUi.monitor")}</span><strong>{brain.body?.mood_summary || t("brainUi.stable")}</strong></div>
          <em>{Math.round((brain.body?.energy || 0) * 100)}%</em>
        </section>
        {brain.body ? <>
          <MetricGroup title={t("brainUi.emotions")} metrics={brain.body.emotions || []} trends={trends} prefix="emotion" />
          <MetricGroup title={t("brainUi.desires")} metrics={brain.body.desires || []} trends={trends} prefix="desire" />
          <MetricGroup title={t("brainUi.hormones")} metrics={brain.body.hormones || []} trends={trends} prefix="hormone" />
          {brain.body.somatic ? <section className="brain-somatic"><span>{t("brainUi.bodyFeeling")}</span><p>{brain.body.somatic}</p></section> : null}
        </> : <p className="brain-section-empty">{t("brainUi.noBody")}</p>}
        {brain.relationship ? <Relationship snapshot={brain.relationship} /> : null}
      </aside>
    </div> : null}
  </section>;
}

function SectionTitle({ eyebrow, title, count }: { eyebrow: string; title: string; count?: number }) {
  return <header className="brain-section-title"><div><span>{eyebrow}</span><h3>{title}</h3></div>{typeof count === "number" ? <b>{count}</b> : null}</header>;
}

function CurrentActivity({ activity }: { activity: BrainActivitySnapshot }) {
  const { t } = useTranslation();
  const progress = activity.total_steps
    ? Math.min(100, Math.round((activity.completed_steps || 0) / activity.total_steps * 100))
    : null;
  return <article className={`brain-current is-${activity.status}`}>
    <div className="brain-current-pulse"><i /><span /></div>
    <div className="brain-current-copy">
      <div><span>{categoryName(activity.category, t)}</span><em>{statusName(activity.status, t)}</em></div>
      <h4>{activity.title}</h4>
      <p>{activity.progress_summary || activity.current_step || statusName(activity.status, t)}</p>
      {progress != null ? <div className="brain-progress"><i style={{ width: `${progress}%` }} /><span>{activity.completed_steps || 0}/{activity.total_steps}</span></div> : null}
      {activity.pause_reason ? <small>{t("brainUi.pauseReason", { reason: activity.pause_reason })}</small> : null}
    </div>
  </article>;
}

function ActivityStrip({ activity }: { activity: BrainActivitySnapshot }) {
  const { t } = useTranslation();
  return <div><i className={`is-${activity.category}`} /><span><strong>{activity.title}</strong><small>{activity.progress_summary || statusName(activity.status, t)}</small></span><em>{statusName(activity.status, t)}</em></div>;
}

function TimelineItem({ activity }: { activity: BrainActivitySnapshot }) {
  const { t } = useTranslation();
  const summary = activitySummary(activity, t);
  return <article className={`is-${activity.category}`}>
    <time>{formatClock(activity.updated_at)}</time>
    <span className="brain-timeline-node"><i /></span>
    <div><small>{categoryName(activity.category, t)} · {statusName(activity.status, t)}</small><strong>{activity.title}</strong><p>{summary}</p></div>
  </article>;
}

function MetricGroup({ title, metrics, trends, prefix }: { title: string; metrics: BrainMetric[]; trends: Trends; prefix: string }) {
  return <section className="brain-metric-group">
    <header><strong>{title}</strong><span>{metrics.length}</span></header>
    <div>{metrics.map((metric) => {
      const value = clamp(metric.value);
      return <article key={metric.key} title={metric.description || metric.label}>
        <span>{metric.label}</span><b>{Math.round(value * 100)}</b>
        <div className="brain-metric-bar"><i style={{ width: `${value * 100}%` }} /></div>
        <Sparkline points={trends[`${prefix}.${metric.key}`] || []} />
      </article>;
    })}</div>
  </section>;
}

function Sparkline({ points }: { points: TrendPoint[] }) {
  const values = points.slice(-60);
  if (values.length < 2) return <svg className="brain-sparkline" viewBox="0 0 72 22" aria-hidden="true"><path d="M0 11 L72 11" /></svg>;
  const path = values.map((point, index) => {
    const x = values.length === 1 ? 0 : index / (values.length - 1) * 72;
    const y = 20 - clamp(point.value) * 18;
    return `${index ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(" ");
  return <svg className="brain-sparkline" viewBox="0 0 72 22" preserveAspectRatio="none" aria-hidden="true"><path d={path} /></svg>;
}

function Relationship({ snapshot }: { snapshot: Record<string, unknown> }) {
  const { t } = useTranslation();
  const items = [
    [t("brainUi.familiarity"), Number(snapshot.depth || 0)],
    [t("brainUi.trust"), Number(snapshot.trust || 0)],
    [t("brainUi.closeness"), Number(snapshot.closeness || 0)],
  ] as const;
  return <section className="brain-relationship">
    <header><span>{t("brainUi.relationship")}</span><strong>{String(snapshot.display_name || "")}</strong></header>
    {items.map(([label, value]) => <div key={label}><span>{label}</span><i><b style={{ width: `${clamp(value) * 100}%` }} /></i><em>{Math.round(clamp(value) * 100)}</em></div>)}
  </section>;
}

function seedTrends(body: BrainBodySnapshot | null, at: number): Trends {
  const next: Trends = {};
  metricEntries(body).forEach(([key, value]) => { next[key] = [{ at, value }]; });
  return next;
}

function appendTrendSample(setter: (value: Trends | ((current: Trends) => Trends)) => void, body: BrainBodySnapshot | null, at: number) {
  if (!body) return;
  setter((current) => {
    const next = { ...current };
    metricEntries(body).forEach(([key, value]) => {
      const existing = next[key] || [];
      const last = existing[existing.length - 1];
      if (last && Math.floor(last.at) === Math.floor(at)) return;
      next[key] = [...existing, { at, value }].slice(-90);
    });
    return next;
  });
}

function metricEntries(body: BrainBodySnapshot | null): Array<[string, number]> {
  if (!body) return [];
  return [
    ["energy", body.energy],
    ...(body.emotions || []).map((item): [string, number] => [`emotion.${item.key}`, item.value]),
    ...(body.desires || []).map((item): [string, number] => [`desire.${item.key}`, item.value]),
    ...(body.hormones || []).map((item): [string, number] => [`hormone.${item.key}`, item.value]),
  ];
}

function clamp(value: number): number { return Math.max(0, Math.min(1, Number(value) || 0)); }
function formatClock(value?: number | null): string { return value ? new Date(value * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—"; }
function relativeTime(value: number, t: (key: string, options?: Record<string, unknown>) => string): string {
  if (!value) return t("brainUi.now");
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - value));
  if (seconds < 60) return t("brainUi.now");
  if (seconds < 3600) return t("brainUi.minutesAgo", { count: Math.floor(seconds / 60) });
  return t("brainUi.hoursAgo", { count: Math.floor(seconds / 3600) });
}
function livingName(value: string | undefined, t: (key: string) => string): string { return t(`brainUi.living.${value || "unknown"}`); }
function categoryName(value: string, t: (key: string) => string): string { return t(`brainUi.category.${value}`); }
function statusName(value: string, t: (key: string) => string): string { return t(`brainUi.status.${value}`); }
function activitySummary(activity: BrainActivitySnapshot, t: (key: string) => string): string {
  if (activity.status === "paused") {
    const key = `brainUi.pause.${activity.pause_reason || "unknown"}`;
    const translated = t(key);
    return translated === key ? statusName(activity.status, t) : translated;
  }
  if (activity.status === "failed") return t("brainUi.activityFailed");
  if (activity.status === "cancelled") return t("brainUi.activityCancelled");
  const summary = activity.result_summary || activity.progress_summary || activity.current_step;
  if (summary === "Autonomous behavior started") return statusName(activity.status, t);
  return summary || statusName(activity.status, t);
}
function intentName(value: string, t: (key: string) => string): string { const key = `brainUi.intent.${String(value || "unknown").toLowerCase()}`; const translated = t(key); return translated === key ? value : translated; }
function scopeName(value: string, t: (key: string) => string): string { return value === "person" ? t("brainUi.personScope") : t("brainUi.agentScope"); }
