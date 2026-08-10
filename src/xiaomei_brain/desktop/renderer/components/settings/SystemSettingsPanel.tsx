import { useEffect, useState, type ReactNode } from "react";
import i18n from "../../i18n";
import { useTranslation } from "react-i18next";
import { useDesktopInfo } from "../../desktop-info";
import type { DesktopSettings, DesktopUpdateState } from "../../types";
import { Button, Icon, SelectMenu } from "../ui";
import { previewMessageSound } from "../../message-sound";

export function SystemSettingsPanel() {
  const { t } = useTranslation();
  const info = useDesktopInfo();
  const [settings, setSettings] = useState<DesktopSettings | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [logContent, setLogContent] = useState<string | null>(null);
  const [updateState, setUpdateState] = useState<DesktopUpdateState | null>(null);

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

  useEffect(() => {
    let active = true;
    void window.desktopUpdate.getState().then((value) => {
      if (active) setUpdateState(value);
    });
    const unsubscribe = window.desktopUpdate.onState((value) => {
      if (active) setUpdateState(value);
    });
    return () => {
      active = false;
      unsubscribe();
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

  async function runUpdateAction(action: "check" | "download" | "install") {
    setError("");
    try {
      const next = await window.desktopUpdate[action]();
      setUpdateState(next);
    } catch (actionError) {
      setError(String(actionError));
    }
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
          <SelectMenu
            value={settings.messageSound}
            className="desktop-message-sound-select"
            placeholder={t("systemUi.messageSounds")}
            options={[
              { value: "none", label: t("systemUi.messageSoundNone") },
              { value: "soft", label: t("systemUi.messageSoundSoft") },
              { value: "crisp", label: t("systemUi.messageSoundCrisp") },
              { value: "bubble", label: t("systemUi.messageSoundBubble") },
            ]}
            onOptionHover={(value) => {
              void previewMessageSound(value as DesktopSettings["messageSound"]);
            }}
            onChange={(value) => {
              const sound = value as DesktopSettings["messageSound"];
              void update({ messageSound: sound });
            }}
          />
        </SettingRow>
        <SettingRow icon="file-text" title={t("fontUi.title")} description={t("fontUi.hint")}>
          <SelectMenu
            value={settings.messageFont}
            placeholder={t("fontUi.title")}
            options={[
              { value: "default", label: t("fontUi.default") },
              { value: "pianpian", label: t("fontUi.pianpian") },
              { value: "wanweiwei", label: t("fontUi.wanweiwei") },
              { value: "honglei", label: t("fontUi.honglei") },
              { value: "ozcaramel", label: t("fontUi.ozcaramel") },
            ]}
            onChange={(value) => void update({
              messageFont: value as DesktopSettings["messageFont"],
            })}
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
          description={updateDescription(updateState, t)}
        >
          <div className="desktop-update-controls">
            <Switch
              checked={settings.automaticUpdatesEnabled}
              onChange={(checked) => void update({ automaticUpdatesEnabled: checked })}
            />
            <UpdateAction
              state={updateState}
              onAction={(action) => void runUpdateAction(action)}
              t={t}
            />
          </div>
        </SettingRow>
        {updateState?.phase === "downloading" && updateState.progress && (
          <div className="desktop-update-progress" aria-label={t("systemUi.updateDownloading")}>
            <span style={{ width: `${updateState.progress.percent}%` }} />
          </div>
        )}
        {updateState?.releaseNotes && (
          <details className="desktop-update-notes">
            <summary>{t("systemUi.updateNotes")}</summary>
            <p>{updateState.releaseNotes}</p>
          </details>
        )}
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

function updateDescription(
  state: DesktopUpdateState | null,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  if (!state) return t("systemUi.updateLoading");
  if (state.phase === "disabled") return t("systemUi.updateDevelopment");
  if (state.phase === "checking") return t("systemUi.updateChecking");
  if (state.phase === "available") {
    return t("systemUi.updateAvailable", { version: state.availableVersion || "" });
  }
  if (state.phase === "downloading") {
    return t("systemUi.updateDownloadingPercent", {
      percent: Math.round(state.progress?.percent || 0),
    });
  }
  if (state.phase === "downloaded") {
    return t("systemUi.updateDownloaded", { version: state.availableVersion || "" });
  }
  if (state.phase === "not_available") {
    return t("systemUi.updateCurrent", { version: state.currentVersion });
  }
  if (state.phase === "error") return state.error || t("systemUi.updateError");
  return t("systemUi.updateHint", { version: state.currentVersion });
}

function UpdateAction({
  state,
  onAction,
  t,
}: {
  state: DesktopUpdateState | null;
  onAction: (action: "check" | "download" | "install") => void;
  t: (key: string) => string;
}) {
  if (!state || state.phase === "disabled") {
    return <span className="desktop-setting-status">{t("systemUi.updatePackagedOnly")}</span>;
  }
  if (state.phase === "checking" || state.phase === "downloading") {
    return <span className="desktop-setting-status">{t(`systemUi.updateState.${state.phase}`)}</span>;
  }
  if (state.phase === "available") {
    return <Button size="sm" onClick={() => onAction("download")}>{t("systemUi.updateDownload")}</Button>;
  }
  if (state.phase === "downloaded") {
    return <Button size="sm" onClick={() => onAction("install")}>{t("systemUi.updateRestart")}</Button>;
  }
  return <Button variant="secondary" size="sm" onClick={() => onAction("check")}>{t("systemUi.updateCheck")}</Button>;
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
