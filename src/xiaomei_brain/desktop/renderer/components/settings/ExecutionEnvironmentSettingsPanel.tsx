import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type {
  ExecutionBackend,
  ExecutionEnvironmentConfiguration,
  ExecutionEnvironmentRuntime,
} from "../../types";
import { Button, Icon } from "../ui";

interface Props {
  agentId: string;
  connected: boolean;
}

const DEFAULT_CONFIGURATION: ExecutionEnvironmentConfiguration = {
  backend: "protected_host",
  network: "enabled",
  resources: { cpu: 2, memory_mb: 4096, pids: 256 },
  docker: { image: "python:3.11-slim-bookworm" },
};

function copyConfiguration(
  value: ExecutionEnvironmentConfiguration,
): ExecutionEnvironmentConfiguration {
  return {
    ...value,
    resources: { ...value.resources },
    docker: { ...value.docker },
  };
}

export function ExecutionEnvironmentSettingsPanel({ agentId, connected }: Props) {
  const { t } = useTranslation();
  const [saved, setSaved] = useState(DEFAULT_CONFIGURATION);
  const [draft, setDraft] = useState(DEFAULT_CONFIGURATION);
  const [runtime, setRuntime] = useState<ExecutionEnvironmentRuntime | null>(null);
  const [candidate, setCandidate] = useState<ExecutionEnvironmentRuntime | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const dirty = useMemo(
    () => JSON.stringify(saved) !== JSON.stringify(draft),
    [draft, saved],
  );
  const dockerReady = draft.backend !== "docker" || Boolean(
    candidate && candidate.state !== "unavailable",
  );

  const load = useCallback(async () => {
    if (!agentId || !connected) return;
    setBusy("load");
    setError("");
    try {
      const response = await window.gateway.getExecutionEnvironment({ agentId });
      if (response.error) throw new Error(response.error.message);
      const configuration = response.result?.configuration as unknown as ExecutionEnvironmentConfiguration;
      const activeRuntime = response.result?.runtime as unknown as ExecutionEnvironmentRuntime;
      const next = configuration?.backend ? configuration : DEFAULT_CONFIGURATION;
      setSaved(copyConfiguration(next));
      setDraft(copyConfiguration(next));
      setRuntime(activeRuntime || null);
      setCandidate(null);
    } catch (loadError) {
      setError(String(loadError instanceof Error ? loadError.message : loadError));
    } finally {
      setBusy("");
    }
  }, [agentId, connected]);

  useEffect(() => {
    void load();
  }, [load]);

  function selectBackend(backend: ExecutionBackend) {
    setDraft((current) => ({ ...current, backend }));
    setCandidate(null);
    setNotice("");
    setError("");
  }

  async function testEnvironment() {
    setBusy("test");
    setError("");
    setNotice("");
    try {
      const response = await window.gateway.testExecutionEnvironment({
        agentId,
        configuration: draft,
      });
      if (response.error) throw new Error(response.error.message);
      const tested = response.result?.runtime as unknown as ExecutionEnvironmentRuntime;
      setCandidate(tested || null);
      setNotice(
        tested?.state === "unavailable"
          ? ""
          : t("executionSettingsUi.testPassed"),
      );
    } catch (testError) {
      setError(String(testError instanceof Error ? testError.message : testError));
    } finally {
      setBusy("");
    }
  }

  async function save() {
    setBusy("save");
    setError("");
    setNotice("");
    try {
      const response = await window.gateway.saveExecutionEnvironment({
        agentId,
        configuration: draft,
      });
      if (response.error) throw new Error(response.error.message);
      const configuration = response.result?.configuration as unknown as ExecutionEnvironmentConfiguration;
      setSaved(copyConfiguration(configuration));
      setDraft(copyConfiguration(configuration));
      setNotice(
        response.result?.restart_required
          ? t("executionSettingsUi.savedRestart")
          : t("executionSettingsUi.saved"),
      );
    } catch (saveError) {
      setError(String(saveError instanceof Error ? saveError.message : saveError));
    } finally {
      setBusy("");
    }
  }

  if (!connected) {
    return <div className="settings-empty">{t("executionSettingsUi.connectToView")}</div>;
  }
  if (busy === "load" && !runtime) {
    return <div className="settings-empty">{t("executionSettingsUi.loading")}</div>;
  }

  const testedRuntime = candidate || (
    runtime?.backend === draft.backend ? runtime : null
  );

  return (
    <div className="execution-environment-settings">
      <header className="model-page-heading">
        <div>
          <h2>{t("executionSettingsUi.title")}</h2>
          <p>{t("executionSettingsUi.description")}</p>
        </div>
      </header>

      <section className="settings-card">
        <div className="settings-card-heading">
          <div>
            <h3>{t("executionSettingsUi.chooseTitle")}</h3>
            <p>{t("executionSettingsUi.chooseHint")}</p>
          </div>
          {runtime && <RuntimeBadge runtime={runtime} />}
        </div>

        <div className="execution-backend-grid">
          <BackendCard
            backend="protected_host"
            selected={draft.backend === "protected_host"}
            title={t("executionSettingsUi.protectedHost")}
            description={t("executionSettingsUi.protectedHostDescription")}
            detail={t("executionSettingsUi.protectedHostDetail")}
            icon="terminal"
            onSelect={selectBackend}
          />
          <BackendCard
            backend="docker"
            selected={draft.backend === "docker"}
            title={t("executionSettingsUi.docker")}
            description={t("executionSettingsUi.dockerDescription")}
            detail={t("executionSettingsUi.dockerDetail")}
            icon="shield"
            onSelect={selectBackend}
          />
        </div>
      </section>

      {draft.backend === "docker" && (
        <section className="settings-card execution-docker-options model-provider-editor">
          <div className="settings-card-heading">
            <div>
              <h3>{t("executionSettingsUi.dockerOptions")}</h3>
              <p>{t("executionSettingsUi.dockerOptionsHint")}</p>
            </div>
          </div>
          <label>
            <span>{t("executionSettingsUi.image")}</span>
            <input
              value={draft.docker.image}
              onChange={(event) => setDraft((current) => ({
                ...current,
                docker: { image: event.target.value },
              }))}
            />
          </label>
          <div className="execution-resource-grid">
            <NumberField
              label={t("executionSettingsUi.cpu")}
              value={draft.resources.cpu}
              min={0}
              step={0.5}
              onChange={(cpu) => setDraft((current) => ({
                ...current,
                resources: { ...current.resources, cpu },
              }))}
            />
            <NumberField
              label={t("executionSettingsUi.memory")}
              value={draft.resources.memory_mb}
              min={0}
              step={256}
              onChange={(memory_mb) => setDraft((current) => ({
                ...current,
                resources: { ...current.resources, memory_mb },
              }))}
            />
            <NumberField
              label={t("executionSettingsUi.pids")}
              value={draft.resources.pids}
              min={0}
              step={16}
              onChange={(pids) => setDraft((current) => ({
                ...current,
                resources: { ...current.resources, pids },
              }))}
            />
          </div>
          <div className="execution-network-row">
            <div>
              <strong>{t("executionSettingsUi.network")}</strong>
              <span>{t("executionSettingsUi.networkHint")}</span>
            </div>
            <div className="execution-segmented" role="group" aria-label={t("executionSettingsUi.network")}>
              {(["enabled", "disabled"] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  className={draft.network === value ? "active" : ""}
                  onClick={() => setDraft((current) => ({ ...current, network: value }))}
                >
                  {t(`executionSettingsUi.networkValues.${value}`)}
                </button>
              ))}
            </div>
          </div>
        </section>
      )}

      <section className="settings-card execution-runtime-card">
        <div className="settings-card-heading">
          <div>
            <h3>{t("executionSettingsUi.statusTitle")}</h3>
            <p>{t("executionSettingsUi.statusHint")}</p>
          </div>
          <Button
            variant="secondary"
            size="sm"
            icon="refresh"
            disabled={Boolean(busy)}
            onClick={() => void testEnvironment()}
          >
            {busy === "test" ? t("executionSettingsUi.testing") : t("executionSettingsUi.test")}
          </Button>
        </div>
        {testedRuntime ? (
          <RuntimeDetails runtime={testedRuntime} />
        ) : (
          <div className="settings-empty compact">
            {draft.backend === "docker"
              ? t("executionSettingsUi.dockerCheckRequired")
              : t("executionSettingsUi.notTested")}
          </div>
        )}
      </section>

      {notice && <div className="settings-notice">{notice}</div>}
      {error && <div className="settings-error">{error}</div>}

      <div className="execution-settings-actions">
        <Button
          variant="ghost"
          disabled={!dirty || Boolean(busy)}
          onClick={() => {
            setDraft(copyConfiguration(saved));
            setCandidate(null);
            setNotice("");
            setError("");
          }}
        >
          {t("executionSettingsUi.reset")}
        </Button>
        <Button
          variant="primary"
          disabled={!dirty || Boolean(busy) || !draft.docker.image.trim() || !dockerReady}
          onClick={() => void save()}
        >
          {busy === "save" ? t("executionSettingsUi.saving") : t("executionSettingsUi.save")}
        </Button>
      </div>
    </div>
  );
}

function BackendCard({
  backend,
  selected,
  title,
  description,
  detail,
  icon,
  onSelect,
}: {
  backend: ExecutionBackend;
  selected: boolean;
  title: string;
  description: string;
  detail: string;
  icon: "terminal" | "shield";
  onSelect: (backend: ExecutionBackend) => void;
}) {
  return (
    <button
      type="button"
      className={`execution-backend-card${selected ? " selected" : ""}`}
      aria-pressed={selected}
      onClick={() => onSelect(backend)}
    >
      <span className="execution-backend-icon"><Icon name={icon} size={18} /></span>
      <span className="execution-backend-copy">
        <strong>{title}</strong>
        <span>{description}</span>
        <small>{detail}</small>
      </span>
      <span className="execution-radio" aria-hidden="true" />
    </button>
  );
}

function RuntimeBadge({ runtime }: { runtime: ExecutionEnvironmentRuntime }) {
  const { t } = useTranslation();
  return (
    <span className={`execution-runtime-badge state-${runtime.state}`}>
      {t(`executionSettingsUi.states.${runtime.state}`, { defaultValue: runtime.state })}
    </span>
  );
}

function RuntimeDetails({ runtime }: { runtime: ExecutionEnvironmentRuntime }) {
  const { t } = useTranslation();
  const rows = [
    [t("executionSettingsUi.runtimeEnvironment"), runtime.display_name],
    [t("executionSettingsUi.runtimeState"), t(`executionSettingsUi.states.${runtime.state}`, { defaultValue: runtime.state })],
    [t("executionSettingsUi.shell"), runtime.shell_runtime || runtime.shell],
    [t("executionSettingsUi.workspace"), runtime.workspace_root],
    [t("executionSettingsUi.container"), runtime.container_name],
    [t("executionSettingsUi.dockerVersion"), runtime.docker_version],
  ].filter((row) => row[1]);
  return (
    <div className="execution-runtime-details">
      {rows.map(([label, value]) => (
        <div key={label}>
          <span>{label}</span>
          <strong>{value}</strong>
        </div>
      ))}
      {runtime.error && <div className="settings-error execution-runtime-error">{runtime.error}</div>}
    </div>
  );
}

function NumberField({
  label,
  value,
  min,
  step,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  step: number;
  onChange: (value: number) => void;
}) {
  return (
    <label>
      <span>{label}</span>
      <input
        type="number"
        min={min}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}
