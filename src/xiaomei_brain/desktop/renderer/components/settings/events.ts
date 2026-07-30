export type SettingsSection = "system" | "accounts" | "agents" | "overview" | "models" | "media" | "search" | "channels";

export const SETTINGS_EVENT = "xiaomei:open-settings";

export function openSettingsCenter(
  section: SettingsSection = "agents",
  agentId?: string,
): void {
  window.dispatchEvent(new CustomEvent(SETTINGS_EVENT, { detail: { section, agentId } }));
}
