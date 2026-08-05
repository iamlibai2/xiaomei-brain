import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
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
  const { t } = useTranslation();
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
        label: `${configuredModels.find((model) => model.value === vision)?.label || vision} (${t("modelUi.visionInvalid")})`,
      }]
      : [];
    return [
      { value: "", label: t("modelUi.visionPlaceholder") },
      ...invalidSelection,
      ...supported,
    ];
  }, [configuredModels, vision, t]);
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
      default: t("modelUi.effortDefault"),
      low: t("modelUi.effortLow"),
      medium: t("modelUi.effortMedium"),
      high: t("modelUi.effortHigh"),
      max: t("modelUi.effortMax"),
    };
    return (selectedPrimaryModel?.thinking_efforts || []).map((effort) => ({
      value: effort,
      label: labels[effort],
    }));
  }, [selectedPrimaryModel, t]);

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
        ? t("modelUi.savedRestart")
        : t("modelUi.savedApplied");
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
      setNotice(t("modelUi.testSuccess"));
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
        ? t("modelUi.selectionApplied")
        : t("modelUi.selectionRestart"));
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
      setError(t("modelUi.modelInUse"));
      return;
    }
    if (!window.confirm(t("modelUi.confirmDelete", { model: model.name || model.id }))) return;

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
        ? t("modelUi.deleted")
        : t("modelUi.providerDeleted"));
    } catch (removeError) {
      setError(String(removeError instanceof Error ? removeError.message : removeError));
    } finally {
      setBusy("");
    }
  }

  async function removeProvider() {
    if (!providerId || !window.confirm(t("modelUi.confirmRemoveProvider", { provider: providerId }))) return;
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
      setNotice(t("modelUi.configRemoved"));
    } catch (removeError) {
      setError(String(removeError instanceof Error ? removeError.message : removeError));
    } finally {
      setBusy("");
    }
  }

  if (!agentId) return <EmptyState text={t("modelUi.selectAgent")} />;
  if (!connected) return <EmptyState text={t("modelUi.connectToView")} />;
  if (!snapshot && busy === "load") return <EmptyState text={t("modelUi.loading")} />;

  return (
    <div className="model-settings model-settings-library">
      <header className="model-page-heading">
        <div>
          <h2>{t("modelUi.title")}</h2>
          <p>{t("modelUi.description")}</p>
        </div>
        <Button variant="primary" onClick={() => fillEditor()}>
          <Icon name="plus" size={15} /> {t("modelUi.add")}
        </Button>
      </header>

      <section className="settings-card model-selection-card">
        <div className="settings-card-heading">
          <div>
            <h3>{t("modelUi.currentUse")}</h3>
            <p>{t("modelUi.currentUseHint")}</p>
          </div>
          {snapshot?.active.primary && (
            <span className="settings-badge">{t("modelUi.running")} · {snapshot.active.primary}</span>
          )}
        </div>
        <div className="settings-form-grid">
          <label>
            {t("modelUi.primary")}
            <SelectMenu
              value={primary}
              options={primaryOptions}
              placeholder={t("modelUi.primaryPlaceholder")}
              searchable={primaryOptions.length > 6}
              searchPlaceholder={t("modelUi.primarySearch")}
              emptyText={t("modelUi.noModels")}
              onChange={selectPrimary}
            />
          </label>
          <label>
            {t("modelUi.vision")}
            <SelectMenu
              value={vision}
              options={visionOptions}
              placeholder={t("modelUi.visionPlaceholder")}
              searchable={visionOptions.length > 7}
              searchPlaceholder={t("modelUi.visionSearch")}
              emptyText={t("modelUi.noVisionModels")}
              onChange={setVision}
            />
          </label>
        </div>
        {supportsThinkingControls && selectedPrimaryModel && (
          <div className="model-thinking-settings">
            <div className="model-thinking-copy">
              <strong>{t("modelUi.thinking")}</strong>
              <span>{selectedPrimaryModel.name || selectedPrimaryModel.id}</span>
            </div>
            {selectedPrimaryModel.thinking_toggle && (
              <button
                type="button"
                className={`desktop-switch ${thinkingEnabled ? "is-on" : ""}`}
                role="switch"
                aria-label={t("modelUi.thinking")}
                aria-checked={thinkingEnabled}
                onClick={() => setThinkingEnabled((current) => !current)}
              >
                <span />
              </button>
            )}
            {thinkingEffortOptions.length > 0 && (
              <div className={`model-thinking-effort ${!thinkingEnabled ? "disabled" : ""}`}>
                <span>{t("modelUi.thinkingEffort")}</span>
                <SelectMenu
                  value={thinkingEffort}
                  options={thinkingEffortOptions}
                  placeholder={t("modelUi.effortDefault")}
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
              {busy === "selection" ? t("modelUi.saving") : t("modelUi.save")}
            </Button>
          </div>
        )}
        {configuredModels.every((model) => !model.vision) && (
          <p className="model-selection-hint">
            {t("modelUi.noVisionHint")}
          </p>
        )}
        {!supportsThinkingControls && (
          <div className="settings-actions">
            <Button
              variant="primary"
              disabled={!primary || Boolean(busy)}
              onClick={() => void saveSelection()}
            >
              {busy === "selection" ? t("modelUi.switching") : t("modelUi.saveSelection")}
            </Button>
          </div>
        )}
      </section>

      <section className="settings-card model-library-card">
        <div className="settings-card-heading">
          <div>
            <h3>{t("modelUi.addedModels")}</h3>
            <p>{t("modelUi.modelCount", { models: configuredModels.length, providers: snapshot?.providers.length || 0 })}</p>
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
                  <button type="button" onClick={() => fillEditor(provider)}>{t("modelUi.edit")}</button>
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
                        {snapshot.selection.primary === value && <span className="active">{t("modelUi.primaryBadge")}</span>}
                        {snapshot.selection.vision === value && (
                          <span className={model.supports_vision || model.input_modes.includes("image") ? "active" : "invalid"}>
                            {model.supports_vision || model.input_modes.includes("image")
                              ? t("modelUi.visionBadge")
                              : t("modelUi.visionInvalid")}
                          </span>
                        )}
                        {(model.supports_vision || model.input_modes.includes("image")) && <span>{t("modelUi.images")}</span>}
                        {model.supports_tools && <span>{t("modelUi.tools")}</span>}
                        {(model.thinking_toggle || model.thinking_efforts.length > 0) && <span>{t("modelUi.thinkingBadge")}</span>}
                      </div>
                      <button
                        type="button"
                        className="model-library-delete"
                        aria-label={`${t("modelUi.delete")} ${model.name || model.id}`}
                        title={selected ? t("modelUi.deleteDisabled") : t("modelUi.delete")}
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
            <strong>{t("modelUi.emptyTitle")}</strong>
            <p>{t("modelUi.emptyDescription")}</p>
            <Button variant="secondary" onClick={() => fillEditor()}>{t("modelUi.add")}</Button>
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
                <h2 id="model-editor-title">{editingExistingProvider ? t("modelUi.editorEdit") : t("modelUi.editorAdd")}</h2>
                <p>{t("modelUi.editorDescription")}</p>
              </div>
              <button type="button" aria-label={t("modelUi.close")} disabled={Boolean(busy)} onClick={() => setEditorOpen(false)}>
                <Icon name="x" size={18} />
              </button>
            </header>

            <div className="model-editor-body model-provider-editor">
              {!editingExistingProvider && (
                <label>
                  {t("modelUi.provider")}
                  <SelectMenu
                    value={catalog.some((item) => item.id === providerId) ? providerId : ""}
                    options={catalog.map((provider) => ({
                      value: provider.id,
                      label: provider.id,
                    }))}
                    placeholder={t("modelUi.providerPlaceholder")}
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
                  {t("modelUi.provider")}
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
                    ? t("modelUi.apiKeyConfigured")
                    : t("modelUi.apiKeyPlaceholder")}
                />
              </label>

              <div className="model-list-heading">
                <strong>{t("modelUi.modelName")}</strong>
                <span>{t("modelUi.selectedCount", { count: models.length })}</span>
              </div>
              {availableModels.length > 0 && (
                <SelectMenu
                  value=""
                  disabled={busy === "catalog"}
                  searchable
                  placeholder={busy === "catalog" ? t("modelUi.loadingModels") : t("modelUi.modelPlaceholder")}
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
                    {(model.supports_vision || model.input_modes.includes("image")) && <small>{t("modelUi.images")}</small>}
                    {model.supports_tools && <small>{t("modelUi.tools")}</small>}
                    <button
                      type="button"
                      aria-label={t("modelUi.removeModel", { model: model.id })}
                      onClick={() => setModels((current) => current.filter((item) => item.id !== model.id))}
                    >×</button>
                  </span>
                ))}
              </div>
              <details className="model-manual-entry" open={availableModels.length === 0}>
                <summary>{availableModels.length > 0 ? t("modelUi.manualMissing") : t("modelUi.manualEntry")}</summary>
                <div className="model-add-row">
                  <input
                    value={manualModelId}
                    onChange={(event) => setManualModelId(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") addManualModel();
                    }}
                    placeholder={t("modelUi.manualIdPlaceholder")}
                  />
                  <label className="model-vision-toggle">
                    <input
                      type="checkbox"
                      checked={manualModelVision}
                      onChange={(event) => setManualModelVision(event.target.checked)}
                    />
                    {t("modelUi.supportsImages")}
                  </label>
                  <Button variant="secondary" onClick={addManualModel} disabled={!manualModelId.trim()}>
                    {t("modelUi.addManual")}
                  </Button>
                </div>
              </details>

              <details className="model-advanced-settings">
                <summary>{t("modelUi.advanced")}</summary>
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
                    {t("modelUi.apiProtocol")}
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
                    {t("modelUi.removeConfig")}
                  </Button>
                )}
              </div>
              <div>
                <Button variant="secondary" disabled={Boolean(busy)} onClick={() => setEditorOpen(false)}>
                  {t("modelUi.cancel")}
                </Button>
                <Button
                  variant="secondary"
                  disabled={!providerId || !baseUrl || !models.length || Boolean(busy)}
                  onClick={() => void testProvider()}
                >
                  {busy === "test" ? t("modelUi.testing") : t("modelUi.testConnection")}
                </Button>
                <Button
                  variant="primary"
                  disabled={!providerId || !baseUrl || !models.length || Boolean(busy)}
                  onClick={() => void saveProvider()}
                >
                  {busy === "save-provider" ? t("modelUi.saving") : t("modelUi.save")}
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
