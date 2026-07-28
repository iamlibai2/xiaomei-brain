import { IPty } from "node-pty";

export interface TerminalLaunch {
  command: string;
  args: string[];
  cwd?: string;
  env?: NodeJS.ProcessEnv;
}

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

function powershellArgument(value: string): string {
  return `'${value.replace(/'/g, "''")}'`;
}

function wrapWindowsLaunch(
  shell: { command: string; args: string[] },
  launch: TerminalLaunch,
): { command: string; args: string[] } {
  const executable = powershellArgument(launch.command);
  const commandArgs = launch.args.map(powershellArgument).join(" ");
  const commandLine = `& ${executable}${commandArgs ? ` ${commandArgs}` : ""}`;
  const shellName = shell.command.toLowerCase();
  if (shellName.includes("powershell") || shellName.includes("pwsh")) {
    return {
      command: shell.command,
      args: [...shell.args, "-NoExit", "-Command", commandLine],
    };
  }

  // PowerShell is present on supported Windows versions, but keep a cmd
  // fallback for stripped-down environments.
  const cmdLine = [launch.command, ...launch.args]
    .map((value) => `"${value.replace(/"/g, '""')}"`)
    .join(" ");
  return { command: shell.command, args: ["/D", "/K", cmdLine] };
}

// ── TerminalManager ──

export class TerminalManager {
  pty: IPty | null = null;
  id: string | null = null;

  spawn(
    cols: number,
    rows: number,
    onData: (data: string) => void,
    onExit: (code: number) => void,
    launch?: TerminalLaunch,
  ): { id: string; shell: string; cwd: string } {
    this.kill();

    const shell = resolveShell();
    const wrapped = launch && process.platform === "win32"
      ? wrapWindowsLaunch(shell, launch)
      : null;
    const command = wrapped?.command || launch?.command || shell.command;
    const args = wrapped?.args || launch?.args || shell.args;
    const cwd = launch?.cwd || process.env.HOME || process.env.USERPROFILE || "/";

    const nodePty = require("node-pty");
    const p = nodePty.spawn(command, args, {
      name: "xterm-256color",
      cols,
      rows,
      cwd,
      env: {
        ...process.env,
        ...launch?.env,
        TERM: "xterm-256color",
        COLORTERM: "truecolor",
        TERM_PROGRAM: "xiaomei-brain",
      },
    }) as IPty;

    this.id = `term-${Date.now()}`;
    this.pty = p;
    p.onData(onData);
    p.onExit(({ exitCode }: { exitCode: number }) => {
      if (this.pty === p) {
        this.pty = null;
        this.id = null;
      }
      onExit(exitCode);
    });

    return { id: this.id, shell: command, cwd };
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
