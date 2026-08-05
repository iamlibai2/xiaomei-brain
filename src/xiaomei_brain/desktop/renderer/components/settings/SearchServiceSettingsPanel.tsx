import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type {
  MediaServiceField,
  ToolServiceConfig,
} from "../../types";
import { Button, Icon, SelectMenu } from "../ui";
import { notifyCapabilityStatusChanged } from "./events";

interface Props {
  agentId: string;
  connected: boolean;
  target?: string;
  onTargetConsumed?: () => void;
}

export function SearchServiceSettingsPanel({
  agentId,
  connected,
  target = "",
  onTargetConsumed,
}: Props) {
  const { t } = useTranslation();
  const [services, setServices] = useState<ToolServiceConfig[]>([]);
  const [editing, setEditing] = useState<ToolServiceConfig | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!agentId || !connected) {
      setServices([]);
      return;
    }
    setBusy("load");
    setError("");
    try {
      const response = await window.gateway.listToolServices({
        agentId,
        capability: "web_search",
      });
      if (response.error) throw new Error(response.error.message);
      const result = response.result?.services;
      setServices(Array.isArray(result) ? result as unknown as ToolServiceConfig[] : []);
    } catch (loadError) {
      setError(String(loadError instanceof Error ? loadError.message : loadError));
    } finally {
      setBusy("");
    }
  }, [agentId, connected]);

  useEffect(() => {
    void load();
  }, [load]);

  function openEditor(service: ToolServiceConfig) {
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

  useEffect(() => {
    if (!target || !services.length) return;
    const service = services.find((item) => item.id === target);
    if (service) openEditor(service);
    onTargetConsumed?.();
  }, [target, services, onTargetConsumed]);

  function validateRequired(): boolean {
    if (!editing) return false;
    const missing = editing.fields.find((field) => {
      if (!field.required) return false;
      if (field.type === "secret" && editing.secret_configured) return false;
      return values[field.key] == null || String(values[field.key]).trim() === "";
    });
    if (missing) {
      setError(t("searchSettingsUi.required", { label: missing.label }));
      return false;
    }
    return true;
  }

  async function save() {
    if (!editing || !validateRequired()) return;
    setBusy("save");
    setError("");
    try {
      const response = await window.gateway.configureToolService({
        agentId,
        serviceId: editing.id,
        config: values,
        enabled: true,
      });
      if (response.error) throw new Error(response.error.message);
      setEditing(null);
      await load();
      notifyCapabilityStatusChanged(agentId, "web_search");
      setNotice(t("searchSettingsUi.saved"));
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
      const response = await window.gateway.testToolService({
        agentId,
        serviceId: editing.id,
        config: values,
      });
      if (response.error) throw new Error(response.error.message);
      setNotice(t("searchSettingsUi.testSuccess"));
    } catch (testError) {
      setError(String(testError instanceof Error ? testError.message : testError));
    } finally {
      setBusy("");
    }
  }

  async function remove(serviceId: string) {
    if (!window.confirm(t("searchSettingsUi.confirmRemove"))) return;
    setBusy(`remove:${serviceId}`);
    setError("");
    try {
      const response = await window.gateway.removeToolService({ agentId, serviceId });
      if (response.error) throw new Error(response.error.message);
      setEditing(null);
      await load();
      notifyCapabilityStatusChanged(agentId, "web_search");
      setNotice(t("searchSettingsUi.removed"));
    } catch (removeError) {
      setError(String(removeError instanceof Error ? removeError.message : removeError));
    } finally {
      setBusy("");
    }
  }

  if (!agentId) return <EmptyState text={t("searchSettingsUi.selectAgent")} />;
  if (!connected) return <EmptyState text={t("searchSettingsUi.connectToView")} />;
  if (!services.length && busy === "load") {
    return <EmptyState text={t("searchSettingsUi.loading")} />;
  }

  const visibleFields = editing?.fields.filter(
    (field) => showAdvanced || !field.advanced,
  ) || [];
  const hasAdvanced = Boolean(editing?.fields.some((field) => field.advanced));

  return (
    <div className="image-provider-settings">
      <header className="model-page-heading">
        <div>
          <h2>{t("searchSettingsUi.title")}</h2>
          <p>{t("searchSettingsUi.description")}</p>
        </div>
      </header>

      <section className="settings-card image-provider-library">
        <div className="settings-card-heading">
          <div>
            <h3>{t("searchSettingsUi.services")}</h3>
            <p>{t("searchSettingsUi.servicesHint")}</p>
          </div>
        </div>
        {services.length ? (
          <div className="image-provider-list">
            {services.map((service) => (
              <article key={service.id} className="image-provider-row">
                <span className="model-library-icon">
                  <Icon name="search" size={16} />
                </span>
                <div className="image-provider-copy">
                  <strong>{service.name}</strong>
                  <span>{service.vendor || service.plugin}</span>
                  <small>
                    {service.configured
                      ? `${t("searchSettingsUi.configured")}${service.secret_hint ? ` · ${service.secret_hint}` : ""}`
                      : t("searchSettingsUi.pluginProvided")}
                  </small>
                </div>
                <span className={service.enabled && service.configured
                  ? "image-provider-status active"
                  : "image-provider-status"}
                >
                  {service.enabled && service.configured ? t("searchSettingsUi.enabled") : t("searchSettingsUi.notConfigured")}
                </span>
                <Button variant="secondary" onClick={() => openEditor(service)}>
                  {service.configured ? t("searchSettingsUi.edit") : t("searchSettingsUi.configure")}
                </Button>
              </article>
            ))}
          </div>
        ) : (
          <div className="settings-empty">{t("searchSettingsUi.noPlugin")}</div>
        )}
      </section>

      {notice && !editing && <div className="settings-notice">{notice}</div>}
      {error && !editing && <div className="settings-error">{error}</div>}

      {editing && (
        <div className="model-editor-backdrop" onMouseDown={() => !busy && setEditing(null)}>
          <section
            className="model-editor-dialog image-provider-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="search-service-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <header className="model-editor-header">
              <div>
                <h2 id="search-service-title">{editing.name}</h2>
                <p>{t("searchSettingsUi.editorHint")}</p>
              </div>
              <button
                type="button"
                aria-label={t("searchSettingsUi.close")}
                disabled={Boolean(busy)}
                onClick={() => setEditing(null)}
              >
                <Icon name="x" size={18} />
              </button>
            </header>

            <div className="model-editor-body model-provider-editor">
              {visibleFields.map((field) => (
                <ServiceField
                  key={field.key}
                  field={field}
                  value={values[field.key]}
                  secretConfigured={editing.secret_configured}
                  secretHint={editing.secret_hint}
                  onChange={(value) => setValues((current) => ({
                    ...current,
                    [field.key]: value,
                  }))}
                />
              ))}
              {hasAdvanced && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowAdvanced((current) => !current)}
                >
                  {showAdvanced ? t("searchSettingsUi.advancedCollapse") : t("searchSettingsUi.advanced")}
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
                    {t("searchSettingsUi.removeConfig")}
                  </Button>
                )}
              </div>
              <div>
                <Button variant="secondary" disabled={Boolean(busy)} onClick={() => setEditing(null)}>
                  {t("searchSettingsUi.cancel")}
                </Button>
                <Button variant="secondary" disabled={Boolean(busy)} onClick={() => void testConnection()}>
                  {busy === "test" ? t("searchSettingsUi.testing") : t("searchSettingsUi.test")}
                </Button>
                <Button variant="primary" disabled={Boolean(busy)} onClick={() => void save()}>
                  {busy === "save" ? t("searchSettingsUi.saving") : t("searchSettingsUi.save")}
                </Button>
              </div>
            </footer>
          </section>
        </div>
      )}
    </div>
  );
}

function ServiceField({
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
          placeholder={t("searchSettingsUi.selectField", { label: field.label })}
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
        value={String(value ?? "")}
        min={field.minimum}
        max={field.maximum}
        step={field.step}
        placeholder={field.type === "secret" && secretConfigured
          ? t("searchSettingsUi.configuredSecret", { hint: secretHint })
          : t("searchSettingsUi.enterField", { label: field.label })}
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
  return (
    <div className="settings-empty-state">
      <Icon name="search" size={24} />
      <span>{text}</span>
    </div>
  );
}
