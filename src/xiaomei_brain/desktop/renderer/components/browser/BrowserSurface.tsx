import { FormEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { DesktopBrowserState } from "../../types";

const EMPTY_STATE: DesktopBrowserState = {
  open: false,
  visible: false,
  loading: false,
  url: "",
  title: "",
  canGoBack: false,
  canGoForward: false,
};

export function BrowserSurface({
  agentId,
  requestedUrl,
  onClose,
}: {
  agentId: string;
  requestedUrl?: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const viewportRef = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<DesktopBrowserState>(EMPTY_STATE);
  const [address, setAddress] = useState(requestedUrl || "");

  useEffect(() => window.desktopBrowser.onState((next) => {
    setState(next);
    if (next.url) setAddress(next.url);
  }), []);

  useEffect(() => {
    let disposed = false;
    const element = viewportRef.current;
    if (!element) return;
    const syncBounds = () => {
      const rect = element.getBoundingClientRect();
      if (!disposed) void window.desktopBrowser.setBounds({
        x: rect.x,
        y: rect.y,
        width: rect.width,
        height: rect.height,
      });
    };
    const observer = new ResizeObserver(syncBounds);
    observer.observe(element);
    window.addEventListener("resize", syncBounds);
    syncBounds();
    void window.desktopBrowser.setVisible({ visible: true });
    void window.desktopBrowser.getState().then((next) => {
      if (!disposed) {
        setState(next);
        if (next.url) setAddress(next.url);
      }
    });
    return () => {
      disposed = true;
      observer.disconnect();
      window.removeEventListener("resize", syncBounds);
      void window.desktopBrowser.setVisible({ visible: false });
    };
  }, []);

  useEffect(() => {
    if (!requestedUrl) return;
    void window.desktopBrowser.command({ action: "open", agentId, url: requestedUrl });
  }, [agentId, requestedUrl]);

  const navigate = (event: FormEvent) => {
    event.preventDefault();
    if (!address.trim()) return;
    void window.desktopBrowser.command({ action: "navigate", agentId, url: address.trim() });
  };

  const action = (name: "back" | "forward" | "reload") => {
    void window.desktopBrowser.command({ action: name, agentId });
  };

  return (
    <section className="desktop-browser-surface">
      <header className="desktop-browser-toolbar">
        <div className="desktop-browser-nav">
          <button type="button" disabled={!state.canGoBack} onClick={() => action("back")} aria-label={t("browserUi.back")}>←</button>
          <button type="button" disabled={!state.canGoForward} onClick={() => action("forward")} aria-label={t("browserUi.forward")}>→</button>
          <button type="button" onClick={() => action("reload")} aria-label={t("browserUi.reload")}>↻</button>
        </div>
        <form className="desktop-browser-address" onSubmit={navigate}>
          <span className={`desktop-browser-status${state.loading ? " is-loading" : ""}`} aria-hidden="true" />
          <input
            value={address}
            onChange={(event) => setAddress(event.target.value)}
            placeholder={t("browserUi.addressPlaceholder")}
            aria-label={t("browserUi.address")}
            spellCheck={false}
          />
        </form>
        <button type="button" className="desktop-browser-close" onClick={onClose} aria-label={t("browserUi.close")}>×</button>
      </header>
      <div className="desktop-browser-meta">
        <span>{state.title || t("browserUi.title")}</span>
        {state.transfer && (
          <span className={`desktop-browser-transfer is-${state.transfer.status}`}>
            <span className="desktop-browser-transfer-label">
              {t(`browserUi.${state.transfer.direction}`)} · {state.transfer.name || t("browserUi.preparingTransfer")}
            </span>
            <span className="desktop-browser-transfer-track" aria-hidden="true">
              <span style={{ width: `${state.transfer.percent}%` }} />
            </span>
            <span>{state.transfer.percent}%</span>
          </span>
        )}
        {state.error && <span className="desktop-browser-error">{state.error}</span>}
      </div>
      <div ref={viewportRef} className="desktop-browser-viewport" />
    </section>
  );
}
