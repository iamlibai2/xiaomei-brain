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
  const terminalAgentId = useCoreStore((s) => s.terminalAgentId);
  const terminalAgentName = useCoreStore((s) => (
    s.agents.find((agent) => agent.localAgentId === s.terminalAgentId)?.name || s.terminalAgentId
  ));

  useEffect(() => {
    let disposed = false;
    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: 'Menlo, Consolas, "Courier New", monospace',
      theme: {
        background: "#ffffff",
        foreground: "#24292f",
        cursor: "#0969da",
        cursorAccent: "#ffffff",
        selectionBackground: "#b6d7ff",
        black: "#24292f",
        red: "#cf222e",
        green: "#116329",
        yellow: "#9a6700",
        blue: "#0969da",
        magenta: "#8250df",
        cyan: "#1b7c83",
        white: "#6e7781",
        brightBlack: "#57606a",
        brightRed: "#a40e26",
        brightGreen: "#1a7f37",
        brightYellow: "#bf8700",
        brightBlue: "#218bff",
        brightMagenta: "#a475f9",
        brightCyan: "#3192aa",
        brightWhite: "#24292f",
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
    const focusFrame = window.requestAnimationFrame(() => term.focus());

    // Spawn PTY with fitted dimensions
    void window.terminal.spawn({
      cols: term.cols,
      rows: term.rows,
      mode: terminalAgentId ? "agent-logs" : "shell",
      agentId: terminalAgentId || undefined,
    }).then((result) => {
      if (!disposed && result.error) {
        term.writeln(`\r\n\u001b[31m${result.error}\u001b[0m`);
      }
    }).catch((error) => {
      if (!disposed) {
        term.writeln(`\r\n\u001b[31m${String(error)}\u001b[0m`);
      }
    });

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
      disposed = true;
      window.cancelAnimationFrame(focusFrame);
      observer.disconnect();
      unsubData();
      unsubExit();
      term.dispose();
      window.terminal.dispose();
    };
  }, [terminalAgentId, t]);

  return (
    <div className="terminal-panel">
      <div className="terminal-panel-header">
        <span className="terminal-panel-title">
          {terminalAgentId
            ? t("terminal.agentLogTitle", { name: terminalAgentName })
            : t("terminal.title")}
        </span>
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
