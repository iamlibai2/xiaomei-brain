import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { Button } from "../ui";
import { useCoreStore } from "../../store";
import "@xterm/xterm/css/xterm.css";

export function TerminalPanel() {
  const { t } = useTranslation();
  const hostRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const setTerminalOpen = useCoreStore((s) => s.setTerminalOpen);

  useEffect(() => {
    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: 'Menlo, Consolas, "Courier New", monospace',
      theme: {
        background: "#1e1e1e",
        foreground: "#d4d4d4",
        cursor: "#d4d4d4",
      },
      allowTransparency: false,
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);

    if (hostRef.current) {
      term.open(hostRef.current);
      fitAddon.fit();
    }

    termRef.current = term;

    // Spawn PTY with fitted dimensions
    window.terminal.spawn({ cols: term.cols, rows: term.rows });

    // Resize handler
    const observer = new ResizeObserver(() => {
      fitAddon.fit();
      window.terminal.resize({ cols: term.cols, rows: term.rows });
    });
    if (hostRef.current) {
      observer.observe(hostRef.current);
    }

    // User input → PTY
    term.onData((data) => {
      window.terminal.write(data);
    });

    // PTY output → terminal display
    const unsubData = window.terminal.onData((data: string) => {
      term.write(data);
    });

    const unsubExit = window.terminal.onExit((code: number) => {
      term.writeln(`\r\n\u001b[33m[${t("terminal.exitMessage", { code })}]\u001b[0m`);
    });

    return () => {
      observer.disconnect();
      unsubData();
      unsubExit();
      term.dispose();
      window.terminal.dispose();
    };
  }, []);

  return (
    <div className="terminal-panel">
      <div className="terminal-panel-header">
        <span className="terminal-panel-title">{t("terminal.title")}</span>
        <div className="terminal-panel-actions">
          <Button
            variant="ghost"
            size="icon-sm"
            icon="x"
            onClick={() => setTerminalOpen(false)}
            title={t("terminal.close")}
          />
        </div>
      </div>
      <div ref={hostRef} className="terminal-container" />
    </div>
  );
}
