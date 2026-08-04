export type SettingsSection = "system" | "local-ai" | "accounts" | "agents" | "overview" | "capabilities" | "models" | "media" | "search" | "channels";

export const SETTINGS_EVENT = "xiaomei:open-settings";
export const CAPABILITY_STATUS_CHANGED_EVENT = "xiaomei:capability-status-changed";
export const LOCAL_AI_STATUS_CHANGED_EVENT = "xiaomei:local-ai-status-changed";

export function openSettingsCenter(
  section: SettingsSection = "agents",
  agentId?: string,
  target?: string,
): void {
  window.dispatchEvent(new CustomEvent(SETTINGS_EVENT, {
    detail: { section, agentId, target },
  }));
}

export function notifyCapabilityStatusChanged(
  agentId: string,
  capabilityId = "",
): void {
  window.dispatchEvent(new CustomEvent(CAPABILITY_STATUS_CHANGED_EVENT, {
    detail: { agentId, capabilityId },
  }));
}

export function notifyLocalAIStatusChanged(services: import("../../types").LocalAIServiceStatus[]): void {
  window.dispatchEvent(new CustomEvent(LOCAL_AI_STATUS_CHANGED_EVENT, {
    detail: { services },
  }));
}
