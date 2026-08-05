import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type {
  ModelConfigSnapshot,
  ModelDefinition,
  ModelThinkingSelection,
  ThinkingEffort,
} from "../../types";
import { Icon } from "../ui";

interface ModelOption {
  value: string;
  label: string;
  provider: string;
  model: ModelDefinition;
}

export function ModelQuickMenu({
  snapshot,
  busy,
  disabled,
  onApply,
}: {
  snapshot: ModelConfigSnapshot | null;
  busy: boolean;
  disabled: boolean;
  onApply: (
    primary: string,
    thinking?: ModelThinkingSelection,
  ) => Promise<void>;
}) {
  const { t } = useTranslation();
  const effortLabels: Record<ThinkingEffort, string> = {
    default: t("modelQuick.default"),
    low: t("modelQuick.low"),
    medium: t("modelQuick.medium"),
    high: t("modelQuick.high"),
    max: t("modelQuick.max"),
  };
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const options = useMemo<ModelOption[]>(() => (
    snapshot?.providers.flatMap((provider) => provider.models.map((model) => ({
      value: `${provider.id}/${model.id}`,
      label: model.name || model.id,
      provider: provider.id,
      model,
    }))) || []
  ), [snapshot]);
  const primary = snapshot?.selection.primary || "";
  const selected = options.find((option) => option.value === primary);

  useEffect(() => {
    const handleOutside = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, []);

  async function selectModel(option: ModelOption) {
    const hasThinking = Boolean(
      option.model.thinking_toggle || option.model.thinking_efforts.length,
    );
    const nextThinking = hasThinking ? {
      enabled: option.model.thinking_default_enabled,
      effort: normalizeEffort(
        option.model.thinking_default_effort,
        option.model.thinking_efforts,
      ),
    } : undefined;
    setOpen(false);
    await onApply(option.value, nextThinking);
  }

  async function toggleThinking(option: ModelOption, enabled: boolean) {
    if (busy) return;
    const optionThinking = resolveOptionThinking(snapshot, option, primary);
    await onApply(option.value, {
      enabled,
      effort: optionThinking.effort,
    });
  }

  async function selectEffort(option: ModelOption, effort: ThinkingEffort) {
    if (busy) return;
    const optionThinking = resolveOptionThinking(snapshot, option, primary);
    if (option.value === primary && effort === optionThinking.effort) return;
    await onApply(option.value, {
      enabled: true,
      effort,
    });
  }

  return (
    <div
      className={`chat-model-menu ${open ? "is-open" : ""}`}
      ref={rootRef}
    >
      <button
        type="button"
        className="chat-model-menu-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled || options.length === 0}
        title={t("modelQuick.title")}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="chat-model-menu-trigger-copy">
          <strong>{busy ? t("modelQuick.switching") : selected?.label || t("modelQuick.select")}</strong>
        </span>
        <Icon name="chevron-down" size={14} />
      </button>

      {open && (
        <div className="chat-model-menu-popover" role="menu">
          <div className="chat-model-menu-options">
            {options.map((option) => {
              const optionSupportsThinking = Boolean(
                option.model.thinking_toggle
                || option.model.thinking_efforts.length,
              );
              const optionThinking = resolveOptionThinking(snapshot, option, primary);
              const optionEfforts = option.model.thinking_efforts;
              const optionThinkingSummary = optionThinking.enabled
                ? optionEfforts.length
                  ? effortLabels[optionThinking.effort]
                  : t("modelQuick.enabled")
                : t("modelQuick.disabled");
              return (
                <div
                  key={option.value}
                  className={`chat-model-option-shell ${optionSupportsThinking ? "has-details" : ""}`}
                >
                  <button
                    type="button"
                    className={option.value === primary ? "selected" : ""}
                    disabled={busy}
                    onClick={() => void selectModel(option)}
                  >
                    <span className="chat-model-option-name">{option.label}</span>
                    <span className="chat-model-option-end">
                      {option.value === primary && (
                        <span className="chat-model-current-mark" aria-label={t("modelQuick.current")}>✓</span>
                      )}
                      {optionSupportsThinking && <Icon name="chevron-left" size={14} />}
                    </span>
                  </button>

                  {optionSupportsThinking && (
                    <div className="chat-model-detail-panel">
                      <div className="chat-model-detail-header">
                        <strong>{option.label}</strong>
                        <small>{option.provider}</small>
                      </div>
                      <div className="chat-model-detail-divider" />
                      <div className="chat-model-thinking-shell">
                        <button type="button" className="chat-model-detail-action">
                          <span>{t("modelQuick.effort")}</span>
                          <span>
                            {optionThinkingSummary}
                            <Icon name="chevron-left" size={14} />
                          </span>
                        </button>

                        <div className="chat-model-effort-panel">
                          {option.model.thinking_toggle && (
                            <>
                              <div className="chat-model-thinking-toggle">
                                <span>{t("modelQuick.mode")}</span>
                                <button
                                  type="button"
                                  role="switch"
                                  aria-checked={optionThinking.enabled}
                                  className={`desktop-switch ${optionThinking.enabled ? "is-on" : ""}`}
                                  disabled={busy}
                                  onClick={() => void toggleThinking(option, !optionThinking.enabled)}
                                >
                                  <span />
                                </button>
                              </div>
                              {optionEfforts.length > 0 && <div className="chat-model-detail-divider" />}
                            </>
                          )}
                          {optionEfforts.length > 0 && (
                            <div className="chat-model-effort-list">
                              <small>{t("modelQuick.effort")}</small>
                              {optionEfforts.map((effort) => (
                                <button
                                  type="button"
                                  key={effort}
                                  disabled={busy}
                                  className={optionThinking.enabled && optionThinking.effort === effort
                                    ? "selected"
                                    : ""}
                                  onClick={() => void selectEffort(option, effort)}
                                >
                                  <span>{effortLabels[effort]}</span>
                                  {optionThinking.enabled && optionThinking.effort === effort && (
                                    <span aria-hidden="true">✓</span>
                                  )}
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function resolveOptionThinking(
  snapshot: ModelConfigSnapshot | null,
  option: ModelOption,
  primary: string,
): ModelThinkingSelection {
  if (option.value === primary) return resolveThinking(snapshot, option.model);
  return {
    enabled: option.model.thinking_default_enabled,
    effort: normalizeEffort(
      option.model.thinking_default_effort,
      option.model.thinking_efforts,
    ),
  };
}

function resolveThinking(
  snapshot: ModelConfigSnapshot | null,
  model?: ModelDefinition,
): ModelThinkingSelection {
  const efforts = model?.thinking_efforts || [];
  const configured = snapshot?.selection.thinking;
  return {
    enabled: typeof configured?.enabled === "boolean"
      ? configured.enabled
      : model?.thinking_default_enabled ?? true,
    effort: normalizeEffort(
      configured?.effort || model?.thinking_default_effort || "default",
      efforts,
    ),
  };
}

function normalizeEffort(
  effort: ThinkingEffort,
  efforts: ThinkingEffort[],
): ThinkingEffort {
  if (!efforts.length) return "default";
  return efforts.includes(effort) ? effort : efforts[0];
}
