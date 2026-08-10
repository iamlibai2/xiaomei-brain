import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Icon } from "./ui";

const SHORTCUTS = [
  { keys: ["Ctrl", "N"], label: "sidebar.newSession" },
  { keys: ["Ctrl", "K"], label: "shortcutUi.search" },
  { keys: ["Ctrl", "B"], label: "shortcutUi.leftSidebar" },
  { keys: ["Ctrl", "Shift", "B"], label: "shortcutUi.rightSidebar" },
  { keys: ["Ctrl", "M"], label: "shortcutUi.voice" },
  { keys: ["Ctrl", "Shift", "F"], label: "shortcutUi.maximize" },
] as const;

export function ShortcutDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div className="about-overlay" role="presentation" onMouseDown={onClose}>
      <section
        className="about-dialog shortcut-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcut-dialog-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="about-header">
          <div>
            <h2 id="shortcut-dialog-title">{t("shortcutUi.title")}</h2>
            <p>{t("shortcutUi.description")}</p>
          </div>
          <button className="about-close" onClick={onClose} aria-label={t("about.close")}>
            <Icon name="x" size={18} />
          </button>
        </header>
        <div className="shortcut-list">
          {SHORTCUTS.map((shortcut) => (
            <div className="shortcut-row" key={shortcut.label}>
              <span>{t(shortcut.label)}</span>
              <div className="shortcut-keys">
                {shortcut.keys.map((key) => <kbd key={key}>{key}</kbd>)}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
