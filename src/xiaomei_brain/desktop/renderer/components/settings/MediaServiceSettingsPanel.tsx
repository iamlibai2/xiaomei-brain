import { useCallback, useEffect, useMemo, useState } from "react";
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
  { id: "image", label: "图片生成", description: "根据文字描述生成图片", icon: "image" },
  { id: "tts", label: "语音合成", description: "朗读文字并生成音频文件", icon: "microphone" },
  { id: "music", label: "音乐生成", description: "根据描述和歌词生成音乐", icon: "sparkles" },
  { id: "video", label: "视频生成", description: "生成视频片段并参与项目合成", icon: "play" },
];

export function MediaServiceSettingsPanel({ agentId, connected }: Props) {
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
      const response = await window.gateway.configureMediaService({
        agentId,
        serviceId: editing.id,
        config: values,
        enabled: true,
      });
      if (response.error) throw new Error(response.error.message);
      setEditing(null);
      await load();
      setNotice("媒体服务已保存。重启 Agent 后，相应工具会生效。");
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
      setNotice("连接成功，服务地址和凭据可以访问。测试不会生成媒体内容。");
    } catch (testError) {
      setError(String(testError instanceof Error ? testError.message : testError));
    } finally {
      setBusy("");
    }
  }

  async function remove(serviceId: string) {
    if (!window.confirm("移除该媒体服务配置？重启 Agent 后对应工具将不再可用。")) return;
    setBusy(`remove:${serviceId}`);
    setError("");
    try {
      const response = await window.gateway.removeMediaService({ agentId, serviceId });
      if (response.error) throw new Error(response.error.message);
      setEditing(null);
      await load();
      setNotice("媒体服务配置已移除，重启 Agent 后完全生效。");
    } catch (removeError) {
      setError(String(removeError instanceof Error ? removeError.message : removeError));
    } finally {
      setBusy("");
    }
  }

  if (!agentId) return <EmptyState text="请先选择一个 Agent。" />;
  if (!connected) return <EmptyState text="连接 Agent 后才能管理它的媒体服务。" />;
  if (!services.length && busy === "load") {
    return <EmptyState text="正在读取媒体服务配置…" />;
  }

  const visibleFields = editing?.fields.filter(
    (field) => showAdvanced || !field.advanced,
  ) || [];
  const hasAdvanced = Boolean(editing?.fields.some((field) => field.advanced));

  return (
    <div className="image-provider-settings">
      <header className="model-page-heading">
        <div>
          <h2>媒体服务</h2>
          <p>为当前 Agent 配置图片、语音、音乐和视频生成服务，并检查本地媒体运行环境。</p>
        </div>
      </header>

      <section className="settings-card image-provider-library">
        <div className="settings-card-heading">
          <div>
            <h3>本地媒体运行环境</h3>
            <p>视频合成与验收由 Agent 所在机器上的确定性工具完成。</p>
          </div>
          <span className={runtime?.ready ? "image-provider-status active" : "image-provider-status"}>
            {runtime?.ready ? "可用" : "需要配置"}
          </span>
        </div>
        <div className="image-provider-list">
          {(runtime?.tools || []).map((tool) => (
            <article key={tool.id} className="image-provider-row">
              <span className="model-library-icon"><Icon name="terminal" size={16} /></span>
              <div className="image-provider-copy">
                <strong>{tool.name}</strong>
                <span>{tool.version || tool.error || (tool.available ? "已找到可执行文件" : "不可用")}</span>
                {tool.path && <small>{tool.path}</small>}
              </div>
              <span className={tool.available ? "image-provider-status active" : "image-provider-status"}>
                {tool.available ? "已就绪" : "不可用"}
              </span>
            </article>
          ))}
          {!runtime?.tools?.length && <div className="settings-empty">正在检查本地媒体工具…</div>}
        </div>
      </section>

      {CAPABILITIES.map((capability) => {
        const items = grouped.get(capability.id) || [];
        return (
          <section className="settings-card image-provider-library" key={capability.id}>
            <div className="settings-card-heading">
              <div>
                <h3>{capability.label}</h3>
                <p>{capability.description}</p>
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
                          ? `${service.connection_kind === "local" ? "本地运行" : "已配置"}${service.secret_hint ? ` · ${service.secret_hint}` : ""}`
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
              <div className="settings-empty">暂时没有安装此类媒体插件。</div>
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
  return <div className="settings-empty">{text}</div>;
}
