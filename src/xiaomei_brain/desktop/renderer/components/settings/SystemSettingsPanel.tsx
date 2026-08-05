import { useEffect, useState, type ReactNode } from "react";
import i18n from "../../i18n";
import { useTranslation } from "react-i18next";
import { useDesktopInfo } from "../../desktop-info";
import type { DesktopSettings } from "../../types";
import { Button, Icon } from "../ui";

export function SystemSettingsPanel() {
  const { t } = useTranslation();
  const info = useDesktopInfo();
  const [settings, setSettings] = useState<DesktopSettings | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [logContent, setLogContent] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void window.desktop.getSettings()
      .then((value) => {
        if (active) setSettings(value);
      })
      .catch((loadError) => {
        if (active) setError(String(loadError));
      });
    return () => {
      active = false;
    };
  }, []);

  const language = settings?.language || "zh-CN";

  async function update(
    patch: Parameters<typeof window.desktop.updateSettings>[0],
  ) {
    setError("");
    setNotice("");
    const result = await window.desktop.updateSettings(patch);
    if (!result.ok || !result.settings) {
      setError(result.error || t("systemUi.failed"));
      return;
    }
    setSettings(result.settings);
    if (patch.language) await i18n.changeLanguage(patch.language);
    window.dispatchEvent(new CustomEvent(
      "xiaomei:desktop-settings-changed",
      { detail: result.settings },
    ));
    setNotice(t("systemUi.saved"));
  }

  async function openDirectory(kind: "config" | "log") {
    const result = kind === "config"
      ? await window.desktop.openConfigDirectory()
      : await window.desktop.openLogDirectory();
    if (!result.ok) setError(result.error || t("systemUi.failed"));
  }

  async function toggleLog() {
    if (logContent !== null) {
      setLogContent(null);
      return;
    }
    const result = await window.desktop.readLog();
    setLogContent(result.content || t("systemUi.emptyLog"));
  }

  if (!settings) {
    return <div className="settings-empty">{error || t("systemUi.loading")}</div>;
  }

  return (
    <div className="desktop-settings-panel">
      <header className="desktop-settings-intro">
        <h2>{t("systemUi.title")}</h2>
        <p>{t("systemUi.subtitle")}</p>
      </header>

      <section className="settings-card">
        <div className="settings-card-heading">
          <div>
            <h3>{t("systemUi.behavior")}</h3>
          </div>
        </div>
        <SettingRow
          icon="power"
          title={t("systemUi.openAtLogin")}
          description={settings.openAtLoginAvailable ? t("systemUi.openAtLoginHint") : t("systemUi.unavailable")}
        >
          <Switch
            checked={settings.openAtLogin}
            disabled={!settings.openAtLoginAvailable}
            onChange={(checked) => void update({ openAtLogin: checked })}
          />
        </SettingRow>
        <SettingRow icon="x" title={t("systemUi.closeBehavior")} description={t("systemUi.closeHint")}>
          <select
            value={settings.closeBehavior}
            onChange={(event) => void update({
              closeBehavior: event.target.value as DesktopSettings["closeBehavior"],
            })}
          >
            <option value="exit">{t("systemUi.exit")}</option>
            <option value="minimize">{t("systemUi.minimize")}</option>
          </select>
        </SettingRow>
      </section>

      <section className="settings-card">
        <div className="settings-card-heading">
          <div><h3>{t("systemUi.experience")}</h3></div>
        </div>
        <SettingRow icon="bell" title={t("systemUi.notifications")} description={t("systemUi.notificationsHint")}>
          <Switch
            checked={settings.notificationsEnabled}
            onChange={(checked) => void update({ notificationsEnabled: checked })}
          />
        </SettingRow>
        <SettingRow icon="bell" title={t("systemUi.messageSounds")} description={t("systemUi.messageSoundsHint")}>
          <Switch
            checked={settings.messageSoundsEnabled}
            onChange={(checked) => void update({ messageSoundsEnabled: checked })}
          />
        </SettingRow>
        <SettingRow icon="info" title={t("systemUi.language")} description={t("systemUi.languageHint")}>
          <select
            value={settings.language}
            onChange={(event) => void update({
              language: event.target.value as DesktopSettings["language"],
            })}
          >
            <option value="zh-CN">{t("systemUi.chinese")}</option>
            <option value="en-US">English</option>
          </select>
        </SettingRow>
        <SettingRow
          icon="sidebar-panel-right"
          title={t("systemUi.rightSidebar")}
          description={t("systemUi.rightSidebarHint")}
        >
          <Switch
            checked={settings.openRightSidebarByDefault}
            onChange={(checked) => void update({ openRightSidebarByDefault: checked })}
          />
        </SettingRow>
      </section>

      <section className="settings-card">
        <SettingRow
          icon="refresh"
          title={t("systemUi.update")}
          description={t("systemUi.updateHint")}
        >
          <span className="desktop-setting-status">{t("systemUi.updateDisabled")}</span>
        </SettingRow>
      </section>

      <section className="settings-card">
        <div className="settings-card-heading">
          <div><h3>{t("systemUi.directories")}</h3></div>
        </div>
        <DirectoryRow
          label={t("systemUi.configDirectory")}
          path={info?.configDirectory || "—"}
          action={t("systemUi.open")}
          onOpen={() => void openDirectory("config")}
        />
        <DirectoryRow
          label={t("systemUi.logDirectory")}
          path={info?.logDirectory || "—"}
          action={t("systemUi.open")}
          onOpen={() => void openDirectory("log")}
        />
        <div className="desktop-log-action">
          <Button variant="secondary" size="sm" onClick={() => void toggleLog()}>
            {logContent === null ? t("systemUi.viewLog") : t("systemUi.hideLog")}
          </Button>
        </div>
        {logContent !== null && <pre className="desktop-settings-log">{logContent}</pre>}
      </section>

      {notice && <p className="settings-notice">{notice}</p>}
      {error && <p className="settings-error">{error}</p>}
    </div>
  );
}

function SettingRow({
  icon,
  title,
  description,
  children,
}: {
  icon: Parameters<typeof Icon>[0]["name"];
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <div className="desktop-setting-row">
      <span className="desktop-setting-icon"><Icon name={icon} size={17} /></span>
      <div className="desktop-setting-copy">
        <strong>{title}</strong>
        <p>{description}</p>
      </div>
      <div className="desktop-setting-control">{children}</div>
    </div>
  );
}

function Switch({
  checked,
  disabled = false,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <button
      type="button"
      className={`desktop-switch ${checked ? "is-on" : ""}`}
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
    >
      <span />
    </button>
  );
}

function DirectoryRow({
  label,
  path,
  action,
  onOpen,
}: {
  label: string;
  path: string;
  action: string;
  onOpen: () => void;
}) {
  return (
    <div className="desktop-directory-row">
      <div>
        <strong>{label}</strong>
        <code title={path}>{path}</code>
      </div>
      <Button variant="secondary" size="sm" onClick={onOpen}>
        {action}
      </Button>
    </div>
  );
}
