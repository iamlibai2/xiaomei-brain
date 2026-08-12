import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type {
  BootstrapStatus,
  ModelConfigSnapshot,
  ModelDefinition,
} from "../../types";
import { Button, SelectMenu } from "../ui";
import { BootstrapWizard } from "./BootstrapWizard";

interface CatalogProvider {
  id: string;
  base_url: string;
  api_mode: string;
  models?: ModelDefinition[];
}

export function BootstrapModelSetup({
  mode,
  agentId,
  initialAgentId,
  connected,
  connectionError,
  preview,
  onRetryConnection,
  onComplete,
}: {
  mode: "quick" | "custom" | "";
  agentId: string;
  initialAgentId: string;
  connected: boolean;
  connectionError: string;
  preview: boolean;
  onRetryConnection: () => void;
  onComplete: (status: BootstrapStatus) => void;
}) {
  const { t } = useTranslation();
  const [snapshot, setSnapshot] = useState<ModelConfigSnapshot | null>(null);
  const [catalog, setCatalog] = useState<CatalogProvider[]>([]);
  const [adding, setAdding] = useState(false);
  const [primary, setPrimary] = useState("");
  const [providerId, setProviderId] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiMode, setApiMode] = useState("openai-completions");
  const [apiKey, setApiKey] = useState("");
  const [availableModels, setAvailableModels] = useState<ModelDefinition[]>([]);
  const [modelId, setModelId] = useState("");
  const [manualModelId, setManualModelId] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [readyToFinish, setReadyToFinish] = useState(false);

  const configuredModels = useMemo(() => (
    snapshot?.providers
      .filter((provider) => provider.secret_configured)
      .flatMap((provider) => provider.models.map((model) => ({
      value: `${provider.id}/${model.id}`,
      label: model.name || model.id,
      description: provider.id,
      model,
    }))) || []
  ), [snapshot]);

  const load = useCallback(async () => {
    if (!agentId || !connected || preview) return;
    setLoading(true);
    setError("");
    try {
      const [configResponse, catalogResponse] = await Promise.all([
        window.gateway.getModelConfig({ agentId }),
        window.gateway.getModelCatalog({ agentId }),
      ]);
      if (configResponse.error) throw new Error(configResponse.error.message);
      if (catalogResponse.error) throw new Error(catalogResponse.error.message);
      const next = configResponse.result as unknown as ModelConfigSnapshot;
      const providers = Array.isArray(catalogResponse.result?.providers)
        ? catalogResponse.result.providers as unknown as CatalogProvider[]
        : [];
      setSnapshot(next);
      setCatalog(providers);
      const readyProviders = next.providers.filter((provider) => provider.secret_configured && provider.models.length > 0);
      const primaryProviderId = String(next.selection.primary || "").split("/", 1)[0];
      const primaryReady = readyProviders.some((provider) => provider.id === primaryProviderId);
      const fallbackProvider = readyProviders[0];
      const fallbackSelection = fallbackProvider?.models[0]
        ? `${fallbackProvider.id}/${fallbackProvider.models[0].id}`
        : "";
      setPrimary(primaryReady ? next.selection.primary || "" : fallbackSelection);
      setAdding(readyProviders.length === 0);
      if (!primaryReady && readyProviders.length === 0) {
        const configured = next.providers[0];
        const candidate = configured || providers[0];
        if (candidate) {
          const detailResponse = await window.gateway.getModelCatalog({ agentId, providerId: candidate.id });
          if (detailResponse.error) throw new Error(detailResponse.error.message);
          const detail = detailResponse.result?.provider as unknown as CatalogProvider;
          const models = detail.models || configured?.models || [];
          setProviderId(candidate.id);
          setBaseUrl(configured?.base_url || detail.base_url || candidate.base_url || "");
          setApiMode(configured?.api_mode || detail.api_mode || candidate.api_mode || "openai-completions");
          setAvailableModels(models);
          const selected = String(next.selection.primary || "").startsWith(`${candidate.id}/`)
            ? String(next.selection.primary).slice(candidate.id.length + 1)
            : configured?.models[0]?.id || models[0]?.id || "";
          setModelId(selected);
        }
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }, [agentId, connected, preview]);

  useEffect(() => { void load(); }, [load]);

  async function chooseProvider(id: string) {
    setProviderId(id);
    setModelId("");
    setManualModelId("");
    setAvailableModels([]);
    setError("");
    if (!id) return;
    setLoading(true);
    try {
      const response = await window.gateway.getModelCatalog({ agentId, providerId: id });
      if (response.error) throw new Error(response.error.message);
      const provider = response.result?.provider as unknown as CatalogProvider;
      setBaseUrl(provider.base_url || "");
      setApiMode(provider.api_mode || "openai-completions");
      setAvailableModels(provider.models || []);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }

  async function finish() {
    setBusy(true);
    setError("");
    try {
      if (preview) {
        setReadyToFinish(true);
        return;
      }

      let selection = primary;
      let selectedModel = configuredModels.find((item) => item.value === selection)?.model;
      if (adding) {
        const selectedId = modelId || manualModelId.trim();
        const existingProvider = snapshot?.providers.find((provider) => provider.id === providerId);
        if (!providerId || !baseUrl || !selectedId || (!existingProvider?.secret_configured && !apiKey.trim())) {
          throw new Error(t("bootstrap.modelSetup.incomplete"));
        }
        selectedModel = availableModels.find((model) => model.id === selectedId) || {
          id: selectedId,
          name: selectedId,
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

        const tested = await window.gateway.testModelProvider({
          agentId,
          providerId,
          baseUrl,
          apiKey,
          apiMode,
          modelId: selectedId,
        });
        if (tested.error) throw new Error(tested.error.message);

        const models = existingProvider?.models.some((model) => model.id === selectedId)
          ? existingProvider.models
          : [...(existingProvider?.models || []), selectedModel];
        const configured = await window.gateway.configureModelProvider({
          agentId,
          providerId,
          baseUrl,
          apiKey,
          apiMode,
          models,
          baseHash: snapshot?.hashes.global,
        });
        if (configured.error) throw new Error(configured.error.message);
        selection = `${providerId}/${selectedId}`;
      }

      if (!selection || !selectedModel) throw new Error(t("bootstrap.modelSetup.selectModel"));
      const selected = await window.gateway.setModelSelection({
        agentId,
        primary: selection,
        vision: selectedModel.supports_vision || selectedModel.input_modes.includes("image") ? selection : "",
        thinking: selectedModel.thinking_toggle || selectedModel.thinking_efforts.length > 0 ? {
          enabled: selectedModel.thinking_default_enabled,
          effort: selectedModel.thinking_default_effort,
        } : undefined,
        baseHash: snapshot?.hashes.agent,
      });
      if (selected.error) throw new Error(selected.error.message);

      setReadyToFinish(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function completeSetup() {
    setBusy(true);
    setError("");
    try {
      const completed = await window.bootstrap.complete({ initialAgentId: preview ? "xiaomei" : initialAgentId });
      if (!completed.ok || !completed.status) throw new Error(completed.error || t("bootstrap.operationFailed"));
      onComplete(completed.status);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  const selectedId = modelId || manualModelId.trim();
  const configuredProvider = snapshot?.providers.find((provider) => provider.id === providerId);
  const apiKeyRequired = adding && !configuredProvider?.secret_configured;
  const canFinish = preview || (!adding
    ? Boolean(primary)
    : Boolean(providerId && baseUrl && selectedId && (!apiKeyRequired || apiKey.trim())));
  if (readyToFinish) {
    return (
      <BootstrapWizard
        mode={mode}
        current="complete"
        preview={preview}
        title={t("bootstrap.completeTitle")}
        description={t("bootstrap.completeDescription")}
        actions={(
          <Button variant="primary" size="lg" className="bootstrap-primary-action" disabled={busy} onClick={() => void completeSetup()}>
            {busy ? t("bootstrap.finishing") : t("bootstrap.startConversation")}
          </Button>
        )}
      >
        <div className="bootstrap-finish-summary">
          <span aria-hidden="true">✓</span>
          <p>{t("bootstrap.completeHint")}</p>
        </div>
        {error && <div className="setup-error"><span>{error}</span></div>}
      </BootstrapWizard>
    );
  }

  const action = connectionError ? (
    <Button variant="primary" size="lg" className="bootstrap-primary-action" onClick={onRetryConnection}>
      {t("common.retry")}
    </Button>
  ) : connected ? (
    <Button variant="primary" size="lg" className="bootstrap-primary-action" disabled={busy || loading || !canFinish} onClick={() => void finish()}>
      {busy ? t("bootstrap.modelSetup.verifying") : t("bootstrap.next")}
    </Button>
  ) : undefined;

  const modelContent = connectionError ? (
    <div className="bootstrap-error bootstrap-model-error">
      <strong>{t("bootstrap.agentStartFailed")}</strong>
      <p>{connectionError}</p>
      <Button variant="text" size="sm" onClick={() => void window.desktop.openLogDirectory()}>{t("bootstrap.openLogs")}</Button>
    </div>
  ) : !connected ? (
    <div className="bootstrap-inline-loading">
      <span className="bootstrap-spinner" aria-hidden="true" />
      <p>{t("bootstrap.connectingAgent")}</p>
    </div>
  ) : preview ? (
    <div className="bootstrap-model-form">
      <label><span>{t("modelUi.provider")}</span><input value={t("bootstrap.previewProvider")} readOnly /></label>
      <label><span>{t("modelUi.modelName")}</span><input value={t("bootstrap.previewModel")} readOnly /></label>
    </div>
  ) : loading && !snapshot ? (
    <div className="bootstrap-inline-loading">
      <span className="bootstrap-spinner" aria-hidden="true" />
      <p>{t("modelUi.loading")}</p>
    </div>
  ) : (
    <div className="bootstrap-model-form">
      {!adding ? (
        <>
          <label>
            <span>{t("modelUi.primary")}</span>
            <SelectMenu
              value={primary}
              options={configuredModels.map((item) => ({ value: item.value, label: item.label, description: item.description }))}
              placeholder={t("modelUi.primaryPlaceholder")}
              onChange={setPrimary}
            />
          </label>
          <button type="button" className="bootstrap-text-action" onClick={() => {
            setAdding(true);
            setError("");
          }}>{t("bootstrap.modelSetup.addAnother")}</button>
        </>
      ) : (
        <>
          <label>
            <span>{t("modelUi.provider")}</span>
            <SelectMenu
              value={providerId}
              options={catalog.map((provider) => ({ value: provider.id, label: provider.id }))}
              placeholder={t("modelUi.providerPlaceholder")}
              onChange={(value) => void chooseProvider(value)}
            />
          </label>
          <label>
            <span>API Key</span>
            <input
              type="password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder={configuredProvider?.secret_configured
                ? configuredProvider.secret_hint || t("modelUi.apiKeyConfigured")
                : t("modelUi.apiKeyPlaceholder")}
              autoComplete="off"
            />
          </label>
          <label>
            <span>{t("modelUi.modelName")}</span>
            {availableModels.length > 0 ? (
              <SelectMenu
                value={modelId}
                options={availableModels.map((model) => ({ value: model.id, label: model.name || model.id, description: model.name !== model.id ? model.id : "" }))}
                placeholder={t("modelUi.modelPlaceholder")}
                searchable={availableModels.length > 8}
                onChange={(value) => {
                  setModelId(value);
                  setManualModelId("");
                }}
              />
            ) : (
              <input
                value={manualModelId}
                onChange={(event) => setManualModelId(event.target.value)}
                placeholder={loading ? t("modelUi.loadingModels") : t("modelUi.manualIdPlaceholder")}
                disabled={loading || !providerId}
              />
            )}
          </label>
          {configuredModels.length > 0 && (
            <button type="button" className="bootstrap-text-action" onClick={() => {
              setAdding(false);
              setError("");
            }}>{t("bootstrap.modelSetup.useExisting")}</button>
          )}
        </>
      )}
      {error && <div className="setup-error"><span>{error}</span></div>}
    </div>
  );

  return (
    <BootstrapWizard
      mode={mode}
      current="model"
      preview={preview}
      title={t("bootstrap.modelTitle")}
      description={t("bootstrap.modelSetup.description")}
      actions={action}
    >
      {modelContent}
    </BootstrapWizard>
  );
}
