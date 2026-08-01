export type SettingsSection = "system" | "accounts" | "agents" | "overview" | "capabilities" | "models" | "media" | "search" | "channels";

export const SETTINGS_EVENT = "xiaomei:open-settings";
export const CAPABILITY_STATUS_CHANGED_EVENT = "xiaomei:capability-status-changed";

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
