export type SettingsSection = "system" | "accounts" | "overview" | "models" | "channels";

export const SETTINGS_EVENT = "xiaomei:open-settings";

export function openSettingsCenter(section: SettingsSection = "overview"): void {
  window.dispatchEvent(new CustomEvent(SETTINGS_EVENT, { detail: { section } }));
}
