import { useCallback, useEffect, useMemo, useState } from "react";
import type {
  ModelConfigSnapshot,
  ModelDefinition,
  ModelProviderConfig,
  ThinkingEffort,
} from "../../types";
import { Button, Icon, SelectMenu } from "../ui";

interface Props {
  agentId: string;
  connected: boolean;
}

interface CatalogProvider {
  id: string;
  base_url: string;
  api_mode: string;
}

const EMPTY_MODEL: ModelDefinition = {
  id: "",
  name: "",
  context_window: 0,
  max_tokens: 8192,
  reasoning: false,
  thinking_toggle: false,
  thinking_efforts: [],
  thinking_default_enabled: true,
  thinking_default_effort: "default",
  requires_reasoning_content_for_tools: false,
  supports_tools: true,
  input_modes: ["text"],
  supports_vision: false,
};

export function ModelSettingsPanel({ agentId, connected }: Props) {
  const [snapshot, setSnapshot] = useState<ModelConfigSnapshot | null>(null);
  const [catalog, setCatalog] = useState<CatalogProvider[]>([]);
  const [primary, setPrimary] = useState("");
  const [vision, setVision] = useState("");
  const [thinkingEnabled, setThinkingEnabled] = useState(true);
  const [thinkingEffort, setThinkingEffort] = useState<ThinkingEffort>("default");
  const [editorOpen, setEditorOpen] = useState(false);
  const [providerId, setProviderId] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiMode, setApiMode] = useState("openai-completions");
  const [models, setModels] = useState<ModelDefinition[]>([]);
  const [availableModels, setAvailableModels] = useState<ModelDefinition[]>([]);
  const [manualModelId, setManualModelId] = useState("");
  const [manualModelVision, setManualModelVision] = useState(false);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!agentId || !connected) {
      setSnapshot(null);
      return;
    }
    setBusy("load");
    setError("");
    try {
      const [configResponse, catalogResponse] = await Promise.all([
        window.gateway.getModelConfig({ agentId }),
        window.gateway.getModelCatalog({ agentId }),
      ]);
      if (configResponse.error) throw new Error(configResponse.error.message);
      const next = configResponse.result as unknown as ModelConfigSnapshot;
      setSnapshot(next);
      setPrimary(next.selection.primary || "");
      setVision(next.selection.vision || "");
      const [selectedProviderId, selectedModelId] = (
        next.selection.primary || ""
      ).split("/", 2);
      const selectedModel = next.providers
        .find((provider) => provider.id === selectedProviderId)
        ?.models.find((model) => model.id === selectedModelId);
      setThinkingEnabled(
        typeof next.selection.thinking?.enabled === "boolean"
          ? next.selection.thinking.enabled
          : selectedModel?.thinking_default_enabled ?? true,
      );
      setThinkingEffort(
        next.selection.thinking?.effort
        || selectedModel?.thinking_default_effort
        || "default",
      );
      const values = catalogResponse.result?.providers;
      setCatalog(Array.isArray(values) ? values as unknown as CatalogProvider[] : []);
    } catch (loadError) {
      setError(String(loadError instanceof Error ? loadError.message : loadError));
    } finally {
      setBusy("");
    }
  }, [agentId, connected]);

  useEffect(() => {
    void load();
  }, [load]);

  const configuredModels = useMemo(() => (
    snapshot?.providers.flatMap((provider) => provider.models.map((model) => ({
      value: `${provider.id}/${model.id}`,
      label: `${model.name || model.id} · ${provider.id}`,
      vision: model.supports_vision || model.input_modes.includes("image"),
      model,
    }))) || []
  ), [snapshot]);
  const primaryOptions = useMemo(() => configuredModels.map((model) => ({
    value: model.value,
    label: model.label,
  })), [configuredModels]);
  const visionOptions = useMemo(() => {
    const supported = configuredModels
      .filter((model) => model.vision)
      .map((model) => ({ value: model.value, label: model.label }));
    const invalidSelection = vision
      && !supported.some((model) => model.value === vision)
      ? [{
        value: vision,
        label: `${configuredModels.find((model) => model.value === vision)?.label || vision}（不支持图片，需更换）`,
      }]
      : [];
    return [
      { value: "", label: "不设置备用视觉模型" },
      ...invalidSelection,
      ...supported,
    ];
  }, [configuredModels, vision]);
  const selectedPrimaryModel = useMemo(
    () => configuredModels.find((model) => model.value === primary)?.model,
    [configuredModels, primary],
  );
  const supportsThinkingControls = Boolean(
    selectedPrimaryModel?.thinking_toggle
    || selectedPrimaryModel?.thinking_efforts.length,
  );
  const thinkingEffortOptions = useMemo(() => {
    const labels: Record<ThinkingEffort, string> = {
      default: "默认",
      low: "低",
      medium: "中",
      high: "高",
      max: "最大",
    };
    return (selectedPrimaryModel?.thinking_efforts || []).map((effort) => ({
      value: effort,
      label: labels[effort],
    }));
  }, [selectedPrimaryModel]);

  function selectPrimary(value: string) {
    setPrimary(value);
    const model = configuredModels.find((item) => item.value === value)?.model;
    setThinkingEnabled(model?.thinking_default_enabled ?? true);
    setThinkingEffort(model?.thinking_default_effort || "default");
  }

  const editingExistingProvider = Boolean(
    snapshot?.providers.some((provider) => provider.id === providerId),
  );

  function fillEditor(provider?: ModelProviderConfig) {
    setProviderId(provider?.id || "");
    setBaseUrl(provider?.base_url || "");
    setApiMode(provider?.api_mode || "openai-completions");
    setModels(provider?.models || []);
    setAvailableModels([]);
    setApiKey("");
    setManualModelId("");
    setManualModelVision(false);
    setNotice("");
    setError("");
    setEditorOpen(true);
    if (provider && catalog.some((item) => item.id === provider.id)) {
      void loadCatalogProvider(provider.id, false);
    }
  }

  async function loadCatalogProvider(id: string, applyDefaults: boolean) {
    setProviderId(id);
    setBusy("catalog");
    setError("");
    try {
      const response = await window.gateway.getModelCatalog({ agentId, providerId: id });
      if (response.error) throw new Error(response.error.message);
      const provider = response.result?.provider as unknown as CatalogProvider & {
        models?: ModelDefinition[];
      };
      setAvailableModels(provider.models || []);
      if (applyDefaults) {
        const configured = snapshot?.providers.find((item) => item.id === id);
        setBaseUrl(configured?.base_url || provider.base_url || "");
        setApiMode(configured?.api_mode || provider.api_mode || "openai-completions");
        setModels(configured?.models || []);
      }
    } catch (catalogError) {
      setError(String(catalogError instanceof Error ? catalogError.message : catalogError));
    } finally {
      setBusy("");
    }
  }

  function selectCatalogModel(modelId: string) {
    const model = availableModels.find((item) => item.id === modelId);
    if (!model || models.some((item) => item.id === modelId)) return;
    setModels((current) => [...current, model]);
  }

  function addManualModel() {
    const id = manualModelId.trim();
    if (!id || models.some((model) => model.id === id)) return;
    setModels((current) => [...current, {
      ...EMPTY_MODEL,
      id,
      name: id,
      input_modes: manualModelVision ? ["text", "image"] : ["text"],
      supports_vision: manualModelVision,
    }]);
    setManualModelId("");
    setManualModelVision(false);
  }

  async function saveProvider() {
    if (!providerId.trim() || !baseUrl.trim() || models.length === 0) return;
    setBusy("save-provider");
    setError("");
    setNotice("");
    try {
      const response = await window.gateway.configureModelProvider({
        agentId,
        providerId: providerId.trim(),
        baseUrl: baseUrl.trim(),
        apiKey,
        apiMode,
        models,
        baseHash: snapshot?.hashes.global,
      });
      if (response.error) throw new Error(response.error.message);
      const savedMessage = response.result?.restart_required
        ? "模型已保存，将在 Agent 重启后完全生效。"
        : "模型已保存并生效。";
      setApiKey("");
      await load();
      setEditorOpen(false);
      setNotice(savedMessage);
    } catch (saveError) {
      setError(String(saveError instanceof Error ? saveError.message : saveError));
    } finally {
      setBusy("");
    }
  }

  async function testProvider() {
    const modelId = models[0]?.id;
    if (!providerId || !baseUrl || !modelId) return;
    setBusy("test");
    setError("");
    setNotice("");
    try {
      const response = await window.gateway.testModelProvider({
        agentId,
        providerId,
        baseUrl,
        apiKey,
        apiMode,
        modelId,
      });
      if (response.error) throw new Error(response.error.message);
      setNotice("连接成功，模型已返回响应。");
    } catch (testError) {
      setError(String(testError instanceof Error ? testError.message : testError));
    } finally {
      setBusy("");
    }
  }

  async function saveSelection() {
    if (!primary) return;
    setBusy("selection");
    setError("");
    setNotice("");
    try {
      const response = await window.gateway.setModelSelection({
        agentId,
        primary,
        vision,
        thinking: supportsThinkingControls ? {
          enabled: thinkingEnabled,
          effort: thinkingEffort,
        } : undefined,
        baseHash: snapshot?.hashes.agent,
      });
      if (response.error) throw new Error(response.error.message);
      setNotice(response.result?.applied
        ? "当前 Agent 的模型已切换。"
        : "模型选择已保存，将在 Agent 重启后生效。");
      await load();
      window.dispatchEvent(new CustomEvent(
        "xiaomei:model-selection-changed",
        { detail: { agentId } },
      ));
    } catch (selectionError) {
      setError(String(selectionError instanceof Error ? selectionError.message : selectionError));
    } finally {
      setBusy("");
    }
  }

  async function removeModel(provider: ModelProviderConfig, model: ModelDefinition) {
    if (!snapshot) return;
    const value = `${provider.id}/${model.id}`;
    if ([snapshot.selection.primary, snapshot.selection.vision].includes(value)) {
      setError("该模型正在被当前 Agent 使用，请先切换主模型或视觉模型。");
      return;
    }
    if (!window.confirm(`删除模型 ${model.name || model.id}？`)) return;

    setBusy(`remove-model:${value}`);
    setError("");
    setNotice("");
    try {
      const remaining = provider.models.filter((item) => item.id !== model.id);
      const response = remaining.length > 0
        ? await window.gateway.configureModelProvider({
          agentId,
          providerId: provider.id,
          baseUrl: provider.base_url,
          apiKey: "",
          apiMode: provider.api_mode,
          models: remaining,
          baseHash: snapshot.hashes.global,
        })
        : await window.gateway.removeModelProvider({
          agentId,
          providerId: provider.id,
          baseHash: snapshot.hashes.global,
        });
      if (response.error) throw new Error(response.error.message);
      await load();
      setNotice(remaining.length > 0
        ? "模型已删除。"
        : "模型及空的供应商配置已删除。");
    } catch (removeError) {
      setError(String(removeError instanceof Error ? removeError.message : removeError));
    } finally {
      setBusy("");
    }
  }

  async function removeProvider() {
    if (!providerId || !window.confirm(`移除 ${providerId} 及其模型配置？`)) return;
    setBusy("remove");
    setError("");
    try {
      const response = await window.gateway.removeModelProvider({
        agentId,
        providerId,
        baseHash: snapshot?.hashes.global,
      });
      if (response.error) throw new Error(response.error.message);
      await load();
      setEditorOpen(false);
      setNotice("模型配置已移除。");
    } catch (removeError) {
      setError(String(removeError instanceof Error ? removeError.message : removeError));
    } finally {
      setBusy("");
    }
  }

  if (!agentId) return <EmptyState text="请先选择一个 Agent。" />;
  if (!connected) return <EmptyState text="连接 Agent 后才能查看和修改它的模型配置。" />;
  if (!snapshot && busy === "load") return <EmptyState text="正在读取模型配置…" />;

  return (
    <div className="model-settings model-settings-library">
      <header className="model-page-heading">
        <div>
          <h2>模型</h2>
          <p>查看当前 Agent 可用的模型，或添加新的模型服务。</p>
        </div>
        <Button variant="primary" onClick={() => fillEditor()}>
          <Icon name="plus" size={15} /> 添加模型
        </Button>
      </header>

      <section className="settings-card model-selection-card">
        <div className="settings-card-heading">
          <div>
            <h3>当前使用</h3>
            <p>切换主模型和处理图片时使用的视觉模型。</p>
          </div>
          {snapshot?.active.primary && (
            <span className="settings-badge">运行中 · {snapshot.active.primary}</span>
          )}
        </div>
        <div className="settings-form-grid">
          <label>
            主模型
            <SelectMenu
              value={primary}
              options={primaryOptions}
              placeholder="请选择主模型"
              searchable={primaryOptions.length > 6}
              searchPlaceholder="搜索主模型"
              emptyText="没有已配置的模型"
              onChange={selectPrimary}
            />
          </label>
          <label>
            视觉模型
            <SelectMenu
              value={vision}
              options={visionOptions}
              placeholder="不设置备用视觉模型"
              searchable={visionOptions.length > 7}
              searchPlaceholder="搜索视觉模型"
              emptyText="没有支持图片的模型"
              onChange={setVision}
            />
          </label>
        </div>
        {supportsThinkingControls && selectedPrimaryModel && (
          <div className="model-thinking-settings">
            <div className="model-thinking-copy">
              <strong>思考模式</strong>
              <span>{selectedPrimaryModel.name || selectedPrimaryModel.id}</span>
            </div>
            {selectedPrimaryModel.thinking_toggle && (
              <button
                type="button"
                className={`desktop-switch ${thinkingEnabled ? "is-on" : ""}`}
                role="switch"
                aria-label="思考模式"
                aria-checked={thinkingEnabled}
                onClick={() => setThinkingEnabled((current) => !current)}
              >
                <span />
              </button>
            )}
            {thinkingEffortOptions.length > 0 && (
              <div className={`model-thinking-effort ${!thinkingEnabled ? "disabled" : ""}`}>
                <span>思考强度</span>
                <SelectMenu
                  value={thinkingEffort}
                  options={thinkingEffortOptions}
                  placeholder="默认"
                  disabled={!thinkingEnabled}
                  onChange={(value) => setThinkingEffort(value as ThinkingEffort)}
                />
              </div>
            )}
            <Button
              variant="primary"
              size="sm"
              disabled={!primary || Boolean(busy)}
              onClick={() => void saveSelection()}
            >
              {busy === "selection" ? "保存中…" : "保存"}
            </Button>
          </div>
        )}
        {configuredModels.every((model) => !model.vision) && (
          <p className="model-selection-hint">
            当前没有标记为支持图片的模型。添加模型时请选择支持图片的型号，或在手动添加时开启“支持图片”。
          </p>
        )}
        {!supportsThinkingControls && (
          <div className="settings-actions">
            <Button
              variant="primary"
              disabled={!primary || Boolean(busy)}
              onClick={() => void saveSelection()}
            >
              {busy === "selection" ? "切换中…" : "保存选择"}
            </Button>
          </div>
        )}
      </section>

      <section className="settings-card model-library-card">
        <div className="settings-card-heading">
          <div>
            <h3>已添加的模型</h3>
            <p>{configuredModels.length} 个模型，来自 {snapshot?.providers.length || 0} 个服务。</p>
          </div>
        </div>

        {snapshot?.providers.length ? (
          <div className="model-library-list">
            {snapshot.providers.map((provider) => (
              <div className="model-provider-group" key={provider.id}>
                <div className="model-provider-summary">
                  <div>
                    <strong>{provider.id}</strong>
                    <span>{provider.base_url}</span>
                  </div>
                  <button type="button" onClick={() => fillEditor(provider)}>编辑</button>
                </div>
                {provider.models.map((model) => {
                  const value = `${provider.id}/${model.id}`;
                  const selected = [
                    snapshot.selection.primary,
                    snapshot.selection.vision,
                  ].includes(value);
                  return (
                    <div className="model-library-row" key={model.id}>
                      <span className="model-library-icon">
                        <Icon name="sparkles" size={16} />
                      </span>
                      <div>
                        <strong>{model.name || model.id}</strong>
                        <code>{model.id}</code>
                      </div>
                      <div className="model-library-tags">
                        {snapshot.selection.primary === value && <span className="active">主模型</span>}
                        {snapshot.selection.vision === value && (
                          <span className={model.supports_vision || model.input_modes.includes("image") ? "active" : "invalid"}>
                            {model.supports_vision || model.input_modes.includes("image")
                              ? "视觉模型"
                              : "视觉配置异常"}
                          </span>
                        )}
                        {(model.supports_vision || model.input_modes.includes("image")) && <span>图片</span>}
                        {model.supports_tools && <span>工具</span>}
                        {(model.thinking_toggle || model.thinking_efforts.length > 0) && <span>思考</span>}
                      </div>
                      <button
                        type="button"
                        className="model-library-delete"
                        aria-label={`删除 ${model.name || model.id}`}
                        title={selected ? "请先切换当前使用的模型" : "删除模型"}
                        disabled={selected || Boolean(busy)}
                        onClick={() => void removeModel(provider, model)}
                      >
                        <Icon name="trash" size={14} />
                      </button>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        ) : (
          <div className="model-library-empty">
            <Icon name="sparkles" size={24} />
            <strong>还没有添加模型</strong>
            <p>添加一个模型服务后，才能开始与 Agent 对话。</p>
            <Button variant="secondary" onClick={() => fillEditor()}>添加模型</Button>
          </div>
        )}
      </section>

      {notice && <div className="settings-notice">{notice}</div>}
      {!editorOpen && error && <div className="settings-error">{error}</div>}

      {editorOpen && (
        <div className="model-editor-backdrop" onMouseDown={() => !busy && setEditorOpen(false)}>
          <section
            className="model-editor-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="model-editor-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <header className="model-editor-header">
              <div>
                <h2 id="model-editor-title">{editingExistingProvider ? "编辑模型" : "添加模型"}</h2>
                <p>连接信息保存在 Agent 主机，Desktop 不会读取已保存的 API Key 明文。</p>
              </div>
              <button type="button" aria-label="关闭" disabled={Boolean(busy)} onClick={() => setEditorOpen(false)}>
                <Icon name="x" size={18} />
              </button>
            </header>

            <div className="model-editor-body model-provider-editor">
              {!editingExistingProvider && (
                <label>
                  供应商
                  <SelectMenu
                    value={catalog.some((item) => item.id === providerId) ? providerId : ""}
                    options={catalog.map((provider) => ({
                      value: provider.id,
                      label: provider.id,
                    }))}
                    placeholder="请选择供应商"
                    searchable={catalog.length > 6}
                    onChange={(value) => {
                      if (value) void loadCatalogProvider(value, true);
                    }}
                    disabled={busy === "catalog"}
                  />
                </label>
              )}

              {editingExistingProvider && (
                <label>
                  供应商
                  <input value={providerId} disabled />
                </label>
              )}
              <label>
                API Key
                <input
                  type="password"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  placeholder={editingExistingProvider
                    ? "已配置；留空表示不修改"
                    : "请输入 API Key"}
                />
              </label>

              <div className="model-list-heading">
                <strong>模型名称</strong>
                <span>已选择 {models.length} 个</span>
              </div>
              {availableModels.length > 0 && (
                <SelectMenu
                  value=""
                  disabled={busy === "catalog"}
                  searchable
                  placeholder={busy === "catalog" ? "正在加载模型…" : "请选择模型"}
                  options={availableModels
                    .filter((model) => !models.some((selected) => selected.id === model.id))
                    .map((model) => (
                      {
                        value: model.id,
                        label: model.name || model.id,
                        description: model.name && model.name !== model.id ? model.id : "",
                      }
                    ))}
                  onChange={selectCatalogModel}
                />
              )}
              <div className="model-chip-list">
                {models.map((model) => (
                  <span className="model-chip" key={model.id}>
                    <span>{model.name || model.id}</span>
                    {(model.supports_vision || model.input_modes.includes("image")) && <small>图片</small>}
                    {model.supports_tools && <small>工具</small>}
                    <button
                      type="button"
                      aria-label={`移除 ${model.id}`}
                      onClick={() => setModels((current) => current.filter((item) => item.id !== model.id))}
                    >×</button>
                  </span>
                ))}
              </div>
              <details className="model-manual-entry" open={availableModels.length === 0}>
                <summary>{availableModels.length > 0 ? "找不到需要的模型？" : "手动填写模型名称"}</summary>
                <div className="model-add-row">
                  <input
                    value={manualModelId}
                    onChange={(event) => setManualModelId(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") addManualModel();
                    }}
                    placeholder="输入模型 ID，例如 deepseek-chat"
                  />
                  <label className="model-vision-toggle">
                    <input
                      type="checkbox"
                      checked={manualModelVision}
                      onChange={(event) => setManualModelVision(event.target.checked)}
                    />
                    支持图片
                  </label>
                  <Button variant="secondary" onClick={addManualModel} disabled={!manualModelId.trim()}>
                    添加
                  </Button>
                </div>
              </details>

              <details className="model-advanced-settings">
                <summary>高级设置</summary>
                {!catalog.some((item) => item.id === providerId) && (
                  <label>
                    Provider ID
                    <input
                      value={providerId}
                      disabled={editingExistingProvider}
                      onChange={(event) => setProviderId(event.target.value.toLowerCase())}
                      placeholder="custom-provider"
                    />
                  </label>
                )}
                <div className="settings-form-grid">
                  <label>
                    Base URL
                    <input
                      value={baseUrl}
                      onChange={(event) => setBaseUrl(event.target.value)}
                      placeholder="https://api.example.com/v1"
                    />
                  </label>
                  <label>
                    API 协议
                    <select value={apiMode} onChange={(event) => setApiMode(event.target.value)}>
                      <option value="openai-completions">OpenAI Completions</option>
                      <option value="chat-completions">Chat Completions</option>
                      <option value="anthropic-messages">Anthropic Messages</option>
                    </select>
                  </label>
                </div>
              </details>

              {notice && <div className="settings-notice">{notice}</div>}
              {error && <div className="settings-error">{error}</div>}
            </div>

            <footer className="model-editor-footer">
              <div>
                {editingExistingProvider && (
                  <Button variant="ghost" disabled={Boolean(busy)} onClick={() => void removeProvider()}>
                    移除配置
                  </Button>
                )}
              </div>
              <div>
                <Button variant="secondary" disabled={Boolean(busy)} onClick={() => setEditorOpen(false)}>
                  取消
                </Button>
                <Button
                  variant="secondary"
                  disabled={!providerId || !baseUrl || !models.length || Boolean(busy)}
                  onClick={() => void testProvider()}
                >
                  {busy === "test" ? "测试中…" : "测试连接"}
                </Button>
                <Button
                  variant="primary"
                  disabled={!providerId || !baseUrl || !models.length || Boolean(busy)}
                  onClick={() => void saveProvider()}
                >
                  {busy === "save-provider" ? "保存中…" : "保存"}
                </Button>
              </div>
            </footer>
          </section>
        </div>
      )}
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return <div className="settings-empty">{text}</div>;
}
