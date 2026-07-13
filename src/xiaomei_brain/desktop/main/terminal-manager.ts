import { IPty } from "node-pty";

let pty: IPty | null = null;

// ── Shell resolution ──

function resolveShell(): { command: string; args: string[] } {
  if (process.platform === "win32") {
    // Try pwsh > powershell > cmd
    for (const cmd of ["pwsh.exe", "pwsh", "powershell.exe"]) {
      try {
        const { execSync } = require("child_process");
        execSync(`where ${cmd}`, { stdio: "ignore" });
        return { command: cmd, args: ["-NoLogo"] };
      } catch {}
    }
    return { command: process.env.COMSPEC || "cmd.exe", args: [] };
  }

  const shell = process.env.SHELL || "/bin/zsh";
  return { command: shell, args: ["-il"] };
}

// ── TerminalManager ──

export class TerminalManager {
  pty: IPty | null = null;
  id: string | null = null;

  spawn(
    cols: number,
    rows: number,
    onData: (data: string) => void,
    onExit: (code: number) => void
  ): { id: string; shell: string; cwd: string } {
    this.kill();

    const shell = resolveShell();
    const cwd = process.env.HOME || process.env.USERPROFILE || "/";

    const nodePty = require("node-pty");
    const p = nodePty.spawn(shell.command, shell.args, {
      name: "xterm-256color",
      cols,
      rows,
      cwd,
      env: {
        ...process.env,
        TERM: "xterm-256color",
        COLORTERM: "truecolor",
        TERM_PROGRAM: "xiaomei-brain",
      },
    }) as IPty;

    this.id = `term-${Date.now()}`;
    this.pty = p;
    p.onData(onData);
    p.onExit(({ exitCode }: { exitCode: number }) => onExit(exitCode));

    return { id: this.id, shell: shell.command, cwd };
  }

  write(data: string): void {
    this.pty?.write(data);
  }

  resize(cols: number, rows: number): void {
    this.pty?.resize(cols, rows);
  }

  kill(): void {
    if (this.pty) {
      try { this.pty.kill(); } catch {}
      this.pty = null;
      this.id = null;
    }
  }
}
