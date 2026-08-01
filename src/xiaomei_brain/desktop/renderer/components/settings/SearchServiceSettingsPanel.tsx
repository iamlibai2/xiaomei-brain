import { useCallback, useEffect, useState } from "react";
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
      setError(`请输入${missing.label}`);
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
      setNotice("搜索服务已保存。重启 Agent 后，联网搜索工具会使用此配置。");
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
      setNotice("连接成功。测试会执行一次轻量搜索，以确认凭证和搜索接口均可使用。");
    } catch (testError) {
      setError(String(testError instanceof Error ? testError.message : testError));
    } finally {
      setBusy("");
    }
  }

  async function remove(serviceId: string) {
    if (!window.confirm("移除该搜索服务配置？重启 Agent 后将不能再使用此搜索服务。")) return;
    setBusy(`remove:${serviceId}`);
    setError("");
    try {
      const response = await window.gateway.removeToolService({ agentId, serviceId });
      if (response.error) throw new Error(response.error.message);
      setEditing(null);
      await load();
      notifyCapabilityStatusChanged(agentId, "web_search");
      setNotice("搜索服务配置已移除，重启 Agent 后完全生效。");
    } catch (removeError) {
      setError(String(removeError instanceof Error ? removeError.message : removeError));
    } finally {
      setBusy("");
    }
  }

  if (!agentId) return <EmptyState text="请先选择一个 Agent。" />;
  if (!connected) return <EmptyState text="连接 Agent 后才能管理它的联网搜索服务。" />;
  if (!services.length && busy === "load") {
    return <EmptyState text="正在读取搜索服务配置…" />;
  }

  const visibleFields = editing?.fields.filter(
    (field) => showAdvanced || !field.advanced,
  ) || [];
  const hasAdvanced = Boolean(editing?.fields.some((field) => field.advanced));

  return (
    <div className="image-provider-settings">
      <header className="model-page-heading">
        <div>
          <h2>联网搜索</h2>
          <p>为当前 Agent 配置网页搜索能力。凭证只保存在这个 Agent 的配置中。</p>
        </div>
      </header>

      <section className="settings-card image-provider-library">
        <div className="settings-card-heading">
          <div>
            <h3>搜索服务</h3>
            <p>Agent 在需要获取实时信息时，可以自主调用已启用的搜索服务。</p>
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
                      ? `已配置${service.secret_hint ? ` · ${service.secret_hint}` : ""}`
                      : "由插件提供，配置后启用"}
                  </small>
                </div>
                <span className={service.enabled && service.configured
                  ? "image-provider-status active"
                  : "image-provider-status"}
                >
                  {service.enabled && service.configured ? "已启用" : "未配置"}
                </span>
                <Button variant="secondary" onClick={() => openEditor(service)}>
                  {service.configured ? "编辑" : "配置"}
                </Button>
              </article>
            ))}
          </div>
        ) : (
          <div className="settings-empty">暂时没有安装可配置的搜索插件。</div>
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
                <p>配置只属于当前 Agent，API Key 不会返回给 Desktop。</p>
              </div>
              <button
                type="button"
                aria-label="关闭"
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
                  {showAdvanced ? "收起高级设置" : "高级设置"}
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
                    移除配置
                  </Button>
                )}
              </div>
              <div>
                <Button variant="secondary" disabled={Boolean(busy)} onClick={() => setEditing(null)}>
                  取消
                </Button>
                <Button variant="secondary" disabled={Boolean(busy)} onClick={() => void testConnection()}>
                  {busy === "test" ? "测试中…" : "测试连接"}
                </Button>
                <Button variant="primary" disabled={Boolean(busy)} onClick={() => void save()}>
                  {busy === "save" ? "保存中…" : "保存"}
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
          placeholder={`请选择${field.label}`}
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
          ? `已配置 ${secretHint}，留空表示不修改`
          : `请输入${field.label}`}
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
