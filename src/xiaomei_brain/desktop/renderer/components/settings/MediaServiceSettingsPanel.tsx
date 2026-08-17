import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type {
  MediaCapability,
  MediaRuntimeStatus,
  MediaServiceConfig,
  MediaServiceField,
} from "../../types";
import { Button, Icon, SelectMenu, type IconName } from "../ui";

interface Props {
  agentId: string;
  connected: boolean;
}

const CAPABILITIES: Array<{
  id: MediaCapability;
  label: string;
  description: string;
  icon: IconName;
}> = [
  { id: "image", label: "mediaUi.imageLabel", description: "mediaUi.imageDescription", icon: "image" },
  { id: "tts", label: "mediaUi.ttsLabel", description: "mediaUi.ttsDescription", icon: "microphone" },
  { id: "music", label: "mediaUi.musicLabel", description: "mediaUi.musicDescription", icon: "sparkles" },
  { id: "video", label: "mediaUi.videoLabel", description: "mediaUi.videoDescription", icon: "play" },
];

export function MediaServiceSettingsPanel({ agentId, connected }: Props) {
  const { t } = useTranslation();
  const [services, setServices] = useState<MediaServiceConfig[]>([]);
  const [runtime, setRuntime] = useState<MediaRuntimeStatus | null>(null);
  const [editing, setEditing] = useState<MediaServiceConfig | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!agentId || !connected) {
      setServices([]);
      setRuntime(null);
      return;
    }
    setBusy("load");
    setError("");
    try {
      const [response, runtimeResponse] = await Promise.all([
        window.gateway.listMediaServices({ agentId }),
        window.gateway.getMediaRuntimeStatus({ agentId }),
      ]);
      if (response.error) throw new Error(response.error.message);
      if (runtimeResponse.error) throw new Error(runtimeResponse.error.message);
      const result = response.result?.services;
      setServices(Array.isArray(result) ? result as unknown as MediaServiceConfig[] : []);
      setRuntime(runtimeResponse.result as unknown as MediaRuntimeStatus);
    } catch (loadError) {
      setError(String(loadError instanceof Error ? loadError.message : loadError));
    } finally {
      setBusy("");
    }
  }, [agentId, connected]);

  useEffect(() => {
    void load();
  }, [load]);

  const grouped = useMemo(() => new Map(
    CAPABILITIES.map((capability) => [
      capability.id,
      services.filter((service) => service.capability === capability.id),
    ]),
  ), [services]);

  function openEditor(service: MediaServiceConfig) {
    const initial: Record<string, unknown> = { ...service.values };
    for (const field of service.fields) {
      if (field.type === "secret") initial[field.key] = "";
      else if (initial[field.key] == null && field.default != null) {
        initial[field.key] = field.default;
      }
    }
    setEditing(service);
    setValues(initial);
    setShowAdvanced(false);
    setNotice("");
    setError("");
  }

  function updateValue(key: string, value: unknown) {
    setValues((current) => ({ ...current, [key]: value }));
  }

  function validateRequired(): boolean {
    if (!editing) return false;
    const missing = editing.fields.find((field) => {
      if (!field.required) return false;
      if (field.type === "secret" && editing.secret_configured) return false;
      return values[field.key] == null || String(values[field.key]).trim() === "";
    });
    if (missing) {
      setError(t("mediaUi.required", { label: missing.label }));
      return false;
    }
    return true;
  }

  async function save() {
    if (!editing || !validateRequired()) return;
    setBusy("save");
    setError("");
    try {
      const response = await window.gateway.configureMediaService({
        agentId,
        serviceId: editing.id,
        config: values,
        enabled: true,
      });
      if (response.error) throw new Error(response.error.message);
      setEditing(null);
      await load();
      setNotice(t("mediaUi.saved"));
    } catch (saveError) {
      setError(String(saveError instanceof Error ? saveError.message : saveError));
    } finally {
      setBusy("");
    }
  }

  async function testConnection() {
    if (!editing || !validateRequired()) return;
    setBusy("test");
    setError("");
    setNotice("");
    try {
      const response = await window.gateway.testMediaService({
        agentId,
        serviceId: editing.id,
        config: values,
      });
      if (response.error) throw new Error(response.error.message);
      setNotice(t("mediaUi.testSuccess"));
    } catch (testError) {
      setError(String(testError instanceof Error ? testError.message : testError));
    } finally {
      setBusy("");
    }
  }

  async function remove(serviceId: string) {
    if (!window.confirm(t("mediaUi.confirmRemove"))) return;
    setBusy(`remove:${serviceId}`);
    setError("");
    try {
      const response = await window.gateway.removeMediaService({ agentId, serviceId });
      if (response.error) throw new Error(response.error.message);
      setEditing(null);
      await load();
      setNotice(t("mediaUi.removed"));
    } catch (removeError) {
      setError(String(removeError instanceof Error ? removeError.message : removeError));
    } finally {
      setBusy("");
    }
  }

  if (!agentId) return <EmptyState text={t("mediaUi.selectAgent")} />;
  if (!connected) return <EmptyState text={t("mediaUi.connectToView")} />;
  if (!services.length && busy === "load") {
    return <EmptyState text={t("mediaUi.loading")} />;
  }

  const visibleFields = editing?.fields.filter(
    (field) => showAdvanced || !field.advanced,
  ) || [];
  const hasAdvanced = Boolean(editing?.fields.some((field) => field.advanced));

  return (
    <div className="image-provider-settings">
      <header className="model-page-heading">
        <div>
          <h2>{t("mediaUi.title")}</h2>
          <p>{t("mediaUi.description")}</p>
        </div>
      </header>

      <section className="settings-card image-provider-library">
        <div className="settings-card-heading">
          <div>
            <h3>{t("mediaUi.localRuntime")}</h3>
            <p>{t("mediaUi.localRuntimeHint")}</p>
          </div>
          <span className={runtime?.ready ? "image-provider-status active" : "image-provider-status"}>
            {runtime?.ready ? t("mediaUi.available") : t("mediaUi.needsConfig")}
          </span>
        </div>
        <div className="image-provider-list">
          {(runtime?.tools || []).map((tool) => (
            <article key={tool.id} className="image-provider-row">
              <span className="model-library-icon"><Icon name="terminal" size={16} /></span>
              <div className="image-provider-copy">
                <strong>{tool.name}</strong>
                <span>{tool.version || tool.error || (tool.available ? t("mediaUi.foundExecutable") : t("mediaUi.unavailable"))}</span>
                {tool.path && <small>{tool.path}</small>}
              </div>
              <span className={tool.available ? "image-provider-status active" : "image-provider-status"}>
                {tool.available ? t("mediaUi.ready") : t("mediaUi.unavailable")}
              </span>
            </article>
          ))}
          {!runtime?.tools?.length && <div className="settings-empty">{t("mediaUi.checkingTools")}</div>}
        </div>
      </section>

      {CAPABILITIES.map((capability) => {
        const items = grouped.get(capability.id) || [];
        return (
          <section className="settings-card image-provider-library" key={capability.id}>
            <div className="settings-card-heading">
              <div>
                <h3>{t(capability.label)}</h3>
                <p>{t(capability.description)}</p>
              </div>
            </div>
            {items.length ? (
              <div className="image-provider-list">
                {items.map((service) => (
                  <article key={service.id} className="image-provider-row">
                    <span className="model-library-icon">
                      <Icon name={capability.icon} size={16} />
                    </span>
                    <div className="image-provider-copy">
                      <strong>{service.name}</strong>
                      <span>{service.vendor || service.plugin}</span>
                      <small>
                        {service.configured
                          ? `${service.connection_kind === "local" ? t("mediaUi.localRunning") : t("mediaUi.configured")}${service.secret_hint ? ` · ${service.secret_hint}` : ""}`
                          : t("mediaUi.pluginProvided")}
                      </small>
                    </div>
                    <span className={service.enabled && service.configured
                      ? "image-provider-status active"
                      : "image-provider-status"}
                    >
                      {service.enabled && service.configured ? t("mediaUi.enabled") : t("mediaUi.notConfigured")}
                    </span>
                    <Button variant="secondary" onClick={() => openEditor(service)}>
                      {service.configured ? t("mediaUi.edit") : t("mediaUi.configure")}
                    </Button>
                  </article>
                ))}
              </div>
            ) : (
              <div className="settings-empty">{t("mediaUi.noPlugin")}</div>
            )}
          </section>
        );
      })}

      {notice && !editing && <div className="settings-notice">{notice}</div>}
      {error && !editing && <div className="settings-error">{error}</div>}

      {editing && (
        <div className="model-editor-backdrop" onMouseDown={() => !busy && setEditing(null)}>
          <section
            className="model-editor-dialog image-provider-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="media-service-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <header className="model-editor-header">
              <div>
                <h2 id="media-service-title">{editing.name}</h2>
                <p>{t("mediaUi.editorHint")}</p>
              </div>
              <button
                type="button"
                aria-label={t("mediaUi.close")}
                disabled={Boolean(busy)}
                onClick={() => setEditing(null)}
              >
                <Icon name="x" size={18} />
              </button>
            </header>

            <div className="model-editor-body model-provider-editor">
              {visibleFields.map((field) => (
                <MediaField
                  key={field.key}
                  field={field}
                  value={values[field.key]}
                  secretConfigured={editing.secret_configured}
                  secretHint={editing.secret_hint}
                  onChange={(value) => updateValue(field.key, value)}
                />
              ))}
              {hasAdvanced && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowAdvanced((current) => !current)}
                >
                  {showAdvanced ? t("mediaUi.advancedCollapse") : t("mediaUi.advanced")}
                </Button>
              )}
              {notice && <div className="settings-notice">{notice}</div>}
              {error && <div className="settings-error">{error}</div>}
            </div>

            <footer className="model-editor-footer">
              <div>
                {editing.configured && (
                  <Button
                    variant="ghost"
                    disabled={Boolean(busy)}
                    onClick={() => void remove(editing.id)}
                  >
                    {t("mediaUi.removeConfig")}
                  </Button>
                )}
              </div>
              <div>
                <Button variant="secondary" disabled={Boolean(busy)} onClick={() => setEditing(null)}>
                  {t("mediaUi.cancel")}
                </Button>
                <Button variant="secondary" disabled={Boolean(busy)} onClick={() => void testConnection()}>
                  {busy === "test" ? t("mediaUi.testing") : t("mediaUi.test")}
                </Button>
                <Button variant="primary" disabled={Boolean(busy)} onClick={() => void save()}>
                  {busy === "save" ? t("mediaUi.saving") : t("mediaUi.save")}
                </Button>
              </div>
            </footer>
          </section>
        </div>
      )}
    </div>
  );
}

function MediaField({
  field,
  value,
  secretConfigured,
  secretHint,
  onChange,
}: {
  field: MediaServiceField;
  value: unknown;
  secretConfigured: boolean;
  secretHint: string;
  onChange: (value: unknown) => void;
}) {
  const { t } = useTranslation();
  if (field.type === "boolean") {
    return (
      <label className="image-provider-checkbox">
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(event.target.checked)}
        />
        {field.label}
      </label>
    );
  }
  if (field.type === "select") {
    return (
      <label>
        {field.label}
        <SelectMenu
          value={String(value ?? "")}
          options={(field.options || []).map((option) => ({ value: option, label: option }))}
          placeholder={t("mediaUi.selectField", { label: field.label })}
          onChange={onChange}
        />
      </label>
    );
  }
  return (
    <label>
      {field.label}
      <input
        type={field.type === "secret" ? "password" : field.type}
        name={`media-service-${field.key}`}
        autoComplete={field.type === "secret" ? "new-password" : "off"}
        data-1p-ignore={field.type === "secret" ? "true" : undefined}
        data-lpignore={field.type === "secret" ? "true" : undefined}
        spellCheck={false}
        value={String(value ?? "")}
        min={field.minimum}
        max={field.maximum}
        step={field.step}
        placeholder={field.type === "secret" && secretConfigured
          ? t("mediaUi.configuredSecret", { hint: secretHint })
          : t("mediaUi.enterField", { label: field.label })}
        onChange={(event) => onChange(
          field.type === "number" && event.target.value !== ""
            ? Number(event.target.value)
            : event.target.value,
        )}
      />
    </label>
  );
}

function EmptyState({ text }: { text: string }) {
  return <div className="settings-empty">{text}</div>;
}
