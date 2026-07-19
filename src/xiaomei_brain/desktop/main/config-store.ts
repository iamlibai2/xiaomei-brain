import fs from "node:fs";
import path from "node:path";
import { app } from "electron";

/**
 * Thin JSON-file config for Electron-local settings.
 * Only stores what the desktop needs before the Python backend is available
 * (last connection host/port and an optional development runtime override).
 * Everything else lives in the Python backend.
 */
export class ConfigStore {
  private filePath: string;

  constructor() {
    this.filePath = path.join(app.getPath("userData"), "desktop-config.json");
  }

  private read(): Record<string, string> {
    try {
      const raw = fs.readFileSync(this.filePath, "utf-8").replace(/^\uFEFF/, "");
      return JSON.parse(raw);
    } catch {
      return {};
    }
  }

  private write(data: Record<string, string>): void {
    const dir = path.dirname(this.filePath);
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(this.filePath, JSON.stringify(data, null, 2), "utf-8");
  }

  get(key: string): string | null {
    return this.read()[key] ?? null;
  }

  set(key: string, value: string): void {
    const data = this.read();
    data[key] = value;
    this.write(data);
  }
}
