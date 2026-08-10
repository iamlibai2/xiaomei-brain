import { useState, useRef, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useCoreStore } from "../store";
import { openSettingsCenter } from "./settings/events";
import { TokenUsageDialog } from "./TokenUsageDialog";
import { AboutDialog } from "./AboutDialog";
import { ShortcutDialog } from "./ShortcutDialog";
import { ModelContextDialog } from "./ModelContextDialog";

interface MenuItem {
  label: string;
  action?: () => void;
  separator?: boolean;
  disabled?: boolean;
  children?: MenuItem[];
}

export function MenuBar() {
  const { t } = useTranslation();
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [maximized, setMaximized] = useState(false);
  const [usageOpen, setUsageOpen] = useState(false);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [modelContextOpen, setModelContextOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const activeAgent = useCoreStore((state) => (
    state.agents.find((agent) => agent.id === state.activeAgentId)
  ));
  const openAgentLogs = useCoreStore((state) => state.openAgentLogs);
  const terminalOpen = useCoreStore((state) => state.terminalOpen);
  const setTerminalOpen = useCoreStore((state) => state.setTerminalOpen);

  const menus: Record<string, MenuItem[]> = useMemo(() => ({
    [t("menu.edit")]: [
      { label: t("menu.undo"), action: () => document.execCommand("undo") },
      { label: t("menu.redo"), action: () => document.execCommand("redo") },
      { separator: true, label: "" },
      { label: t("menu.cut"), action: () => document.execCommand("cut") },
      { label: t("menu.copy"), action: () => document.execCommand("copy") },
      { label: t("menu.paste"), action: () => document.execCommand("paste") },
      { label: t("menu.selectAll"), action: () => document.execCommand("selectAll") },
    ],
    [t("menu.window")]: [
      {
        label: t("sidebar.settings"),
        action: () => openSettingsCenter("agents"),
      },
      { separator: true, label: "" },
      {
        label: t("sidebar.terminal"),
        action: () => setTerminalOpen(!terminalOpen),
      },
      {
        label: t("menu.viewAgentLogs"),
        action: activeAgent?.localAgentId
          ? () => openAgentLogs(activeAgent.localAgentId!)
          : undefined,
        disabled: !activeAgent || activeAgent.source !== "local" || !activeAgent.localAgentId,
      },
      {
        label: t("menu.analysis"),
        children: [
          {
            label: t("menu.tokenUsage"),
            action: () => setUsageOpen(true),
            disabled: !activeAgent,
          },
          {
            label: t("menu.modelContext"),
            action: () => setModelContextOpen(true),
            disabled: !activeAgent,
          },
        ],
      },
      { separator: true, label: "" },
      { label: t("menu.reload"), action: () => location.reload() },
      { label: t("menu.close"), action: () => window.win.close() },
      { label: t("menu.quit"), action: () => window.win.quit() },
    ],
    [t("menu.help")]: [
      {
        label: t("shortcutUi.title"),
        action: () => setShortcutsOpen(true),
      },
      {
        label: t("systemUi.updateCheck"),
        action: () => { void window.desktopUpdate.check(); },
      },
      { separator: true, label: "" },
      {
        label: t("menu.about"),
        action: () => setAboutOpen(true),
      },
    ],
  }), [activeAgent, openAgentLogs, setTerminalOpen, t, terminalOpen]);

  useEffect(() => {
    if (!window.win) return;
    window.win.isMaximized().then(setMaximized);
    window.win.onMaximizeChange(setMaximized);
  }, []);

  useEffect(() => {
    const handleWindowShortcut = (event: KeyboardEvent) => {
      if (
        event.repeat
        || event.isComposing
        || event.altKey
        || !(event.ctrlKey || event.metaKey)
        || !event.shiftKey
        || event.key.toLowerCase() !== "f"
      ) return;
      event.preventDefault();
      window.win.maximize();
    };
    window.addEventListener("keydown", handleWindowShortcut);
    return () => window.removeEventListener("keydown", handleWindowShortcut);
  }, []);

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpenMenu(null);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  return (
    <>
      <div className="menubar" ref={menuRef}>
        <div className="menubar-logo">
          <div className="menubar-logo-icon">{t("menu.logo")}</div>
        </div>

        <div className="menubar-items">
          {Object.keys(menus).map((key) => (
            <div className="menubar-item" key={key}>
              <button
                className={`menubar-item-button ${openMenu === key ? "open" : ""}`}
                onClick={() => setOpenMenu(openMenu === key ? null : key)}
              >
                {key}
              </button>
              {openMenu === key && (
                <div className="menubar-dropdown">
                  {menus[key].map((item, i) =>
                    item.separator ? (
                      <div className="menubar-dropdown-separator" key={i} />
                    ) : item.children ? (
                      <div className="menubar-dropdown-submenu" key={i}>
                        <button type="button" className="menubar-dropdown-item menubar-dropdown-submenu-trigger">
                          <span>{item.label}</span>
                          <span aria-hidden="true">›</span>
                        </button>
                        <div className="menubar-dropdown menubar-dropdown-nested">
                          {item.children.map((child, childIndex) => (
                            <button
                              type="button"
                              key={childIndex}
                              className="menubar-dropdown-item"
                              disabled={child.disabled}
                              onClick={() => {
                                child.action?.();
                                setOpenMenu(null);
                              }}
                            >
                              {child.label}
                            </button>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <button
                        key={i}
                        className="menubar-dropdown-item"
                        disabled={item.disabled}
                        onClick={() => {
                          item.action?.();
                          setOpenMenu(null);
                        }}
                      >
                        {item.label}
                      </button>
                    )
                  )}
                </div>
              )}
            </div>
          ))}
        </div>

        <div className="menubar-spacer" />

        {window.win && (
          <div className="menubar-window-controls">
            <button
              className="menubar-window-btn"
              onClick={() => window.win.minimize()}
              title={t("menu.minimize")}
              aria-label={t("menu.minimize")}
            >
              <svg className="menubar-window-icon" viewBox="0 0 12 12" aria-hidden="true">
                <path d="M2 6.5h8" />
              </svg>
            </button>
            <button
              className="menubar-window-btn"
              onClick={() => window.win.maximize()}
              title={`${maximized ? t("menu.restore") : t("menu.maximize")} (Ctrl+Shift+F)`}
              aria-label={maximized ? t("menu.restore") : t("menu.maximize")}
            >
              {maximized ? (
                <svg className="menubar-window-icon" viewBox="0 0 12 12" aria-hidden="true">
                  <path d="M4.5 3.5v-1h5v5h-1" />
                  <rect x="2.5" y="4.5" width="5" height="5" />
                </svg>
              ) : (
                <svg className="menubar-window-icon" viewBox="0 0 12 12" aria-hidden="true">
                  <rect x="2.5" y="2.5" width="7" height="7" />
                </svg>
              )}
            </button>
            <button
              className="menubar-window-btn menubar-window-btn-close"
              onClick={() => window.win.close()}
              title={t("menu.close")}
              aria-label={t("menu.close")}
            >
              <svg className="menubar-window-icon" viewBox="0 0 12 12" aria-hidden="true">
                <path d="m2.5 2.5 7 7m0-7-7 7" />
              </svg>
            </button>
          </div>
        )}
      </div>
      {usageOpen && <TokenUsageDialog onClose={() => setUsageOpen(false)} />}
      {aboutOpen && <AboutDialog onClose={() => setAboutOpen(false)} />}
      {shortcutsOpen && <ShortcutDialog onClose={() => setShortcutsOpen(false)} />}
      {modelContextOpen && <ModelContextDialog onClose={() => setModelContextOpen(false)} />}
    </>
  );
}
