import { useEffect, useState, type ReactNode } from "react";
import i18n from "../../i18n";
import { useDesktopInfo } from "../../desktop-info";
import type { DesktopSettings } from "../../types";
import { Button, Icon } from "../ui";

const COPY = {
  "zh-CN": {
    title: "系统设置",
    subtitle: "这些设置只影响当前 Desktop，不会修改任何 Agent。",
    behavior: "启动与窗口",
    openAtLogin: "开机启动",
    openAtLoginHint: "登录 Windows 后自动启动 xiaomei-brain Desktop。",
    unavailable: "当前系统不可用",
    closeBehavior: "关闭窗口时",
    closeHint: "选择点击关闭按钮后退出 Desktop，或仅最小化窗口。",
    exit: "退出 Desktop",
    minimize: "最小化窗口",
    experience: "界面与通知",
    notifications: "Windows 通知",
    notificationsHint: "Desktop 最小化或失焦时，显示 Agent 的新消息通知。",
    language: "语言",
    languageHint: "切换 Desktop 界面语言。",
    rightSidebar: "默认打开右侧栏",
    rightSidebarHint: "进入会话时默认展示 Agent 的动态和状态。",
    update: "自动更新",
    updateDisabled: "暂未启用",
    updateHint: "正式更新服务尚未启用，Desktop 不会自动检查更新。",
    directories: "目录与诊断",
    configDirectory: "Desktop 配置目录",
    logDirectory: "Desktop 日志目录",
    open: "打开目录",
    viewLog: "查看日志",
    hideLog: "收起日志",
    emptyLog: "日志文件目前为空。",
    saved: "设置已保存",
    failed: "保存设置失败",
  },
  "en-US": {
    title: "System settings",
    subtitle: "These preferences affect only this Desktop, not any Agent.",
    behavior: "Startup and window",
    openAtLogin: "Open at login",
    openAtLoginHint: "Start xiaomei-brain Desktop after signing in.",
    unavailable: "Unavailable on this system",
    closeBehavior: "When closing the window",
    closeHint: "Exit Desktop or keep it running in a minimized window.",
    exit: "Exit Desktop",
    minimize: "Minimize window",
    experience: "Interface and notifications",
    notifications: "Windows notifications",
    notificationsHint: "Show Agent message notifications when Desktop is minimized or unfocused.",
    language: "Language",
    languageHint: "Change the Desktop interface language.",
    rightSidebar: "Open right sidebar by default",
    rightSidebarHint: "Show Agent activity and status when entering a conversation.",
    update: "Automatic updates",
    updateDisabled: "Not enabled",
    updateHint: "The release service is not enabled, so Desktop does not check for updates.",
    directories: "Directories and diagnostics",
    configDirectory: "Desktop configuration",
    logDirectory: "Desktop logs",
    open: "Open directory",
    viewLog: "View log",
    hideLog: "Hide log",
    emptyLog: "The log is currently empty.",
    saved: "Settings saved",
    failed: "Failed to save settings",
  },
} as const;

export function SystemSettingsPanel() {
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
  const copy = COPY[language];

  async function update(
    patch: Parameters<typeof window.desktop.updateSettings>[0],
  ) {
    setError("");
    setNotice("");
    const result = await window.desktop.updateSettings(patch);
    if (!result.ok || !result.settings) {
      setError(result.error || copy.failed);
      return;
    }
    setSettings(result.settings);
    if (patch.language) await i18n.changeLanguage(patch.language);
    window.dispatchEvent(new CustomEvent(
      "xiaomei:desktop-settings-changed",
      { detail: result.settings },
    ));
    setNotice(COPY[result.settings.language].saved);
  }

  async function openDirectory(kind: "config" | "log") {
    const result = kind === "config"
      ? await window.desktop.openConfigDirectory()
      : await window.desktop.openLogDirectory();
    if (!result.ok) setError(result.error || copy.failed);
  }

  async function toggleLog() {
    if (logContent !== null) {
      setLogContent(null);
      return;
    }
    const result = await window.desktop.readLog();
    setLogContent(result.content || copy.emptyLog);
  }

  if (!settings) {
    return <div className="settings-empty">{error || "正在读取 Desktop 设置…"}</div>;
  }

  return (
    <div className="desktop-settings-panel">
      <header className="desktop-settings-intro">
        <h2>{copy.title}</h2>
        <p>{copy.subtitle}</p>
      </header>

      <section className="settings-card">
        <div className="settings-card-heading">
          <div>
            <h3>{copy.behavior}</h3>
          </div>
        </div>
        <SettingRow
          icon="power"
          title={copy.openAtLogin}
          description={settings.openAtLoginAvailable ? copy.openAtLoginHint : copy.unavailable}
        >
          <Switch
            checked={settings.openAtLogin}
            disabled={!settings.openAtLoginAvailable}
            onChange={(checked) => void update({ openAtLogin: checked })}
          />
        </SettingRow>
        <SettingRow icon="x" title={copy.closeBehavior} description={copy.closeHint}>
          <select
            value={settings.closeBehavior}
            onChange={(event) => void update({
              closeBehavior: event.target.value as DesktopSettings["closeBehavior"],
            })}
          >
            <option value="exit">{copy.exit}</option>
            <option value="minimize">{copy.minimize}</option>
          </select>
        </SettingRow>
      </section>

      <section className="settings-card">
        <div className="settings-card-heading">
          <div><h3>{copy.experience}</h3></div>
        </div>
        <SettingRow icon="bell" title={copy.notifications} description={copy.notificationsHint}>
          <Switch
            checked={settings.notificationsEnabled}
            onChange={(checked) => void update({ notificationsEnabled: checked })}
          />
        </SettingRow>
        <SettingRow icon="info" title={copy.language} description={copy.languageHint}>
          <select
            value={settings.language}
            onChange={(event) => void update({
              language: event.target.value as DesktopSettings["language"],
            })}
          >
            <option value="zh-CN">简体中文</option>
            <option value="en-US">English</option>
          </select>
        </SettingRow>
        <SettingRow
          icon="sidebar-panel-right"
          title={copy.rightSidebar}
          description={copy.rightSidebarHint}
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
          title={copy.update}
          description={copy.updateHint}
        >
          <span className="desktop-setting-status">{copy.updateDisabled}</span>
        </SettingRow>
      </section>

      <section className="settings-card">
        <div className="settings-card-heading">
          <div><h3>{copy.directories}</h3></div>
        </div>
        <DirectoryRow
          label={copy.configDirectory}
          path={info?.configDirectory || "—"}
          action={copy.open}
          onOpen={() => void openDirectory("config")}
        />
        <DirectoryRow
          label={copy.logDirectory}
          path={info?.logDirectory || "—"}
          action={copy.open}
          onOpen={() => void openDirectory("log")}
        />
        <div className="desktop-log-action">
          <Button variant="secondary" size="sm" onClick={() => void toggleLog()}>
            {logContent === null ? copy.viewLog : copy.hideLog}
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
