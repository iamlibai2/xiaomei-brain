import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../ui";
import type { DesktopSettings } from "../../types";

interface SidebarFooterProps {
  userName: string;
  onSettings?: () => void;
  onNotifications?: () => void;
}

export function SidebarFooter({ userName, onSettings, onNotifications }: SidebarFooterProps) {
  const { t } = useTranslation();
  const [appearanceOpen, setAppearanceOpen] = useState(false);
  const [theme, setTheme] = useState<DesktopSettings["theme"]>("system");

  useEffect(() => {
    void window.desktop.getSettings().then((settings) => setTheme(settings.theme));
    const handleSettings = (event: Event) => {
      const settings = (event as CustomEvent<DesktopSettings>).detail;
      if (settings?.theme) setTheme(settings.theme);
    };
    window.addEventListener("xiaomei:desktop-settings-changed", handleSettings);
    return () => window.removeEventListener("xiaomei:desktop-settings-changed", handleSettings);
  }, []);

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

  return (
    <div className="sidebar-footer">
      <div className="sidebar-identity-menu-wrap">
        <button
          type="button"
          className={`sidebar-footer-avatar ${appearanceOpen ? "is-open" : ""}`}
          title={userName}
          aria-expanded={appearanceOpen}
          onClick={() => setAppearanceOpen((open) => !open)}
        >
          {userName[0] || "?"}
        </button>
        {appearanceOpen && (
          <div className="sidebar-identity-menu" role="dialog" aria-label={t("appearanceUi.title")}>
            <div className="sidebar-identity-menu-heading">
              <strong>{userName}</strong>
              <button type="button" className="sidebar-identity-menu-close" onClick={() => setAppearanceOpen(false)}>
                {t("appearanceUi.close")}
              </button>
            </div>
            <div className="sidebar-identity-menu-section">
              <div className="sidebar-identity-menu-title">{t("appearanceUi.title")}</div>
              <div className="sidebar-appearance-options">
                {(["light", "dark", "system"] as const).map((option) => (
                  <button
                    key={option}
                    type="button"
                    className={`sidebar-appearance-option ${theme === option ? "active" : ""}`}
                    onClick={() => void changeTheme(option)}
                  >
                    <span className={`sidebar-appearance-swatch ${option}`} />
                    <span>{t(`appearanceUi.${option}`)}</span>
                  </button>
                ))}
              </div>
              <p className="sidebar-identity-menu-description">{t("appearanceUi.description")}</p>
            </div>
            {onSettings && (
              <button type="button" className="sidebar-identity-menu-account" onClick={() => { setAppearanceOpen(false); onSettings(); }}>
                <span>{t("appearanceUi.accountSettings")}</span>
                <span aria-hidden="true">›</span>
              </button>
            )}
          </div>
        )}
      </div>
      <span className="sidebar-footer-name">{userName}</span>
      <div className="sidebar-footer-actions">
        <Button variant="ghost" size="icon-md" icon="bell" onClick={onNotifications} title={t("sidebar.notifications")} />
        <Button variant="ghost" size="icon-md" icon="settings" onClick={onSettings} title={t("sidebar.settings")} />
      </div>
    </div>
  );
}
