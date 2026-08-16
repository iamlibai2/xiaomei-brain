import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Icon } from "./ui";

const SECTION_GROUPS = [
  { key: "identity", sections: ["header", "being", "cornerstone", "essence"] },
  { key: "state", sections: ["body", "observed"] },
  {
    key: "memory",
    sections: [
      "short_term_memories", "long_term_memories", "relation_chains", "dag_summaries",
      "narratives", "internal_narratives", "experience", "experience_timeline",
    ],
  },
  { key: "continuity", sections: ["procedures", "recent_dialog", "cross_user_dialog"] },
  { key: "work", sections: ["learn_queue", "desk"] },
  {
    key: "execution",
    sections: [
      "capabilities", "skills", "tool_discovery", "explicit_files", "group_observations",
      "project", "workspace", "process", "assignment", "memory_policy",
    ],
  },
] as const;

type ContextConfigResult = {
  values?: { prompt_sections?: Record<string, boolean> };
  revision?: string;
};

export function ContextControlPanel({
  agentId,
  agentName,
  connected = true,
  embedded = false,
  onClose,
}: {
  agentId: string;
  agentName?: string;
  connected?: boolean;
  embedded?: boolean;
  onClose?: () => void;
}) {
  const { t } = useTranslation();
  const [sections, setSections] = useState<Record<string, boolean>>({});
  const [revision, setRevision] = useState("");
  const [loading, setLoading] = useState(false);
  const [savingKey, setSavingKey] = useState("");
  const [error, setError] = useState("");

  const applyResult = useCallback((result: ContextConfigResult | undefined) => {
    setSections(result?.values?.prompt_sections || {});
    setRevision(result?.revision || "");
  }, []);

  const refresh = useCallback(async () => {
    if (!agentId || !connected) return;
    setLoading(true);
    const response = await window.gateway.getAgentConfig({ agentId, section: "context" });
    if (response.error) setError(response.error.message || t("contextControl.loadFailed"));
    else {
      applyResult(response.result as ContextConfigResult | undefined);
      setError("");
    }
    setLoading(false);
  }, [agentId, applyResult, connected, t]);

  useEffect(() => { void refresh(); }, [refresh]);

  const toggle = async (key: string) => {
    if (!agentId || savingKey) return;
    const nextValue = sections[key] === false;
    setSavingKey(key);
    setSections((current) => ({ ...current, [key]: nextValue }));
    const response = await window.gateway.updateAgentConfig({
      agentId,
      section: "context",
      values: { prompt_sections: { [key]: nextValue } },
      revision,
    });
    if (response.error) {
      setError(response.error.message || t("contextControl.updateFailed"));
      await refresh();
    } else {
      applyResult(response.result as ContextConfigResult | undefined);
      setError("");
    }
    setSavingKey("");
  };

  const reset = async () => {
    if (!agentId || savingKey) return;
    setSavingKey("reset");
    const response = await window.gateway.resetAgentConfig({
      agentId,
      section: "context",
      revision,
    });
    if (response.error) setError(response.error.message || t("contextControl.resetFailed"));
    else {
      applyResult(response.result as ContextConfigResult | undefined);
      setError("");
    }
    setSavingKey("");
  };

  const allSections = useMemo(() => SECTION_GROUPS.flatMap((group) => [...group.sections]), []);
  const enabledCount = allSections.filter((key) => sections[key] !== false).length;

  if (!connected) return <div className="settings-empty">{t("contextControl.connectToView")}</div>;

  return (
    <section className={`context-control${embedded ? " is-embedded" : ""}`} aria-label={t("contextControl.title")}>
      <header className="context-control-header">
        <div>
          <span>{t("contextControl.currentAgent", { name: agentName || agentId })}</span>
          <h2>{t("contextControl.title")}</h2>
          <p>{t("contextControl.subtitle")}</p>
        </div>
        <div className="context-control-actions">
          <button type="button" onClick={() => void refresh()} disabled={loading} title={t("common.refresh")}>
            <Icon name="refresh" size={16} />
          </button>
          {!embedded && onClose ? <button type="button" onClick={onClose} title={t("common.close")}><Icon name="x" size={16} /></button> : null}
        </div>
      </header>
      <div className="context-control-toolbar">
        <strong>{t("contextControl.enabledCount", { enabled: enabledCount, total: allSections.length })}</strong>
        <button type="button" onClick={() => void reset()} disabled={Boolean(savingKey)}>{t("contextControl.reset")}</button>
      </div>
      {error ? <div className="context-control-error">{error}</div> : null}
      <div className="context-control-content">
        {SECTION_GROUPS.map((group) => (
          <section className="context-control-group" key={group.key}>
            <header>
              <h3>{t(`contextControl.groups.${group.key}.title`)}</h3>
              <p>{t(`contextControl.groups.${group.key}.description`)}</p>
            </header>
            <div className="context-control-list">
              {group.sections.map((key) => {
                const checked = sections[key] !== false;
                return (
                  <div className="context-control-row" key={key}>
                    <div>
                      <strong>{t(`contextControl.sections.${key}.title`)}</strong>
                      <p>{t(`contextControl.sections.${key}.description`)}</p>
                    </div>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={checked}
                      className={`desktop-switch ${checked ? "is-on" : ""}`}
                      disabled={loading || Boolean(savingKey)}
                      onClick={() => void toggle(key)}
                    ><span /></button>
                  </div>
                );
              })}
            </div>
          </section>
        ))}
      </div>
    </section>
  );
}
