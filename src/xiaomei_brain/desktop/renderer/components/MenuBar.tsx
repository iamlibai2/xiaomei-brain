import { useState, useRef, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";

interface MenuItem {
  label: string;
  action?: () => void;
  separator?: boolean;
}

export function MenuBar() {
  const { t } = useTranslation();
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [maximized, setMaximized] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

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
      { label: t("menu.reload"), action: () => location.reload() },
      { label: t("menu.devtools"), action: () => {} },
      { separator: true, label: "" },
      { label: t("menu.close"), action: () => window.win.close() },
    ],
    [t("menu.help")]: [
      {
        label: t("menu.about"),
        action: () => alert(t("menu.aboutDetail")),
      },
    ],
  }), [t]);

  useEffect(() => {
    if (!window.win) return;
    window.win.isMaximized().then(setMaximized);
    window.win.onMaximizeChange(setMaximized);
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
                  ) : (
                    <button
                      key={i}
                      className="menubar-dropdown-item"
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
          >
            &#x2212;
          </button>
          <button
            className="menubar-window-btn"
            onClick={() => window.win.maximize()}
            title={maximized ? t("menu.restore") : t("menu.maximize")}
          >
            {maximized ? "\u29C9" : "\u25A1"}
          </button>
          <button
            className="menubar-window-btn menubar-window-btn-close"
            onClick={() => window.win.close()}
            title={t("menu.close")}
          >
            &#x2715;
          </button>
        </div>
      )}
    </div>
  );
}
