import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Icon } from "../ui";
import type { DesktopSettings } from "../../types";

interface SidebarFooterProps {
  userName: string;
  onSettings?: () => void;
}

export function SidebarFooter({ userName, onSettings }: SidebarFooterProps) {
  const { t } = useTranslation();
  const [appearanceOpen, setAppearanceOpen] = useState(false);
  const [theme, setTheme] = useState<DesktopSettings["theme"]>("system");
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void window.desktop.getSettings().then((settings) => setTheme(settings.theme));
    const handleSettings = (event: Event) => {
      const settings = (event as CustomEvent<DesktopSettings>).detail;
      if (settings?.theme) setTheme(settings.theme);
    };
    window.addEventListener("xiaomei:desktop-settings-changed", handleSettings);
    return () => window.removeEventListener("xiaomei:desktop-settings-changed", handleSettings);
  }, []);

  useEffect(() => {
    if (!appearanceOpen) return;
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setAppearanceOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setAppearanceOpen(false);
    };
    document.addEventListener("mousedown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [appearanceOpen]);

  async function changeTheme(nextTheme: DesktopSettings["theme"]) {
    const result = await window.desktop.updateSettings({ theme: nextTheme });
    if (!result.ok || !result.settings) return;
    const savedTheme = result.settings.theme || nextTheme;
    setTheme(savedTheme);
    const root = document.documentElement;
    if (savedTheme === "system") {
      root.removeAttribute("data-theme");
    } else {
      root.setAttribute("data-theme", savedTheme);
    }
    window.dispatchEvent(new CustomEvent("xiaomei:desktop-settings-changed", { detail: result.settings }));
  }

  const activeTheme = theme === "system"
    ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
    : theme;

  return (
    <div className="sidebar-footer">
      <div className="sidebar-identity-menu-wrap" ref={menuRef}>
        <button
          type="button"
          className={`sidebar-footer-identity ${appearanceOpen ? "is-open" : ""}`}
          title={userName}
          aria-expanded={appearanceOpen}
          onClick={() => setAppearanceOpen((open) => !open)}
        >
          <span className="sidebar-footer-avatar">{userName[0] || "?"}</span>
          <span className="sidebar-footer-name">{userName}</span>
          <Icon name="chevron-down" size={14} />
        </button>
        {appearanceOpen && (
          <div className="sidebar-identity-menu" role="dialog" aria-label={t("appearanceUi.title")}>
            <div className="sidebar-identity-menu-heading">
              <span className="sidebar-identity-menu-avatar">{userName[0] || "?"}</span>
              <strong>{userName}</strong>
              <button
                type="button"
                className="sidebar-identity-menu-close"
                aria-label={t("appearanceUi.close")}
                title={t("appearanceUi.close")}
                onClick={() => setAppearanceOpen(false)}
              >
                <Icon name="x" size={16} />
              </button>
            </div>
            <div className="sidebar-identity-menu-section">
              <div className="sidebar-identity-menu-title">{t("appearanceUi.title")}</div>
              <div className="sidebar-appearance-options">
                {(["light", "dark"] as const).map((option) => (
                  <button
                    key={option}
                    type="button"
                    className={`sidebar-appearance-option ${activeTheme === option ? "active" : ""}`}
                    onClick={() => void changeTheme(option)}
                  >
                    <span className={`sidebar-appearance-swatch ${option}`} />
                    <span>{t(`appearanceUi.${option}`)}</span>
                  </button>
                ))}
              </div>
            </div>
            <div className="sidebar-identity-menu-actions">
              {onSettings && (
                <button type="button" className="sidebar-identity-menu-account" onClick={() => { setAppearanceOpen(false); onSettings(); }}>
                  <Icon name="settings" size={16} />
                  <span>{t("appearanceUi.accountSettings")}</span>
                  <Icon name="chevron-right" size={14} />
                </button>
              )}
              <button
                type="button"
                className="sidebar-identity-menu-account"
                onClick={() => {
                  setAppearanceOpen(false);
                  window.dispatchEvent(new CustomEvent("xiaomei:desktop-lock-requested"));
                }}
              >
                <Icon name="shield" size={16} />
                <span>{t("appearanceUi.lockDesktop")}</span>
                <Icon name="chevron-right" size={14} />
              </button>
            </div>
          </div>
        )}
      </div>
      <div className="sidebar-footer-actions">
        <Button variant="ghost" size="icon-md" icon="settings" onClick={onSettings} title={t("sidebar.settings")} />
      </div>
    </div>
  );
}
