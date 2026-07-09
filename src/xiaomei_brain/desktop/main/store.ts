import Database from "better-sqlite3";
import path from "path";
import { app } from "electron";

interface Session {
  id: string;
  agent_name: string;
  created_at: number;
  last_active: number;
}

interface Message {
  id: number;
  session_id: string;
  role: "user" | "agent" | "tool";
  content: string;
  tool_name?: string;
  tool_status?: string;
  created_at: number;
}

export class Store {
  private db: Database.Database;

  constructor() {
    const dbPath = path.join(app.getPath("userData"), "xiaomei-brain.db");
    this.db = new Database(dbPath);
    this.init();
  }

  private init(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        agent_name TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL,
        last_active INTEGER NOT NULL
      );
      CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL DEFAULT '',
        tool_name TEXT,
        tool_status TEXT,
        created_at INTEGER NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
      );
      CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);
    `);
  }

  upsertSession(id: string, agentName: string): void {
    const now = Date.now();
    this.db
      .prepare(
        `INSERT INTO sessions (id, agent_name, created_at, last_active)
         VALUES (?, ?, ?, ?)
         ON CONFLICT(id) DO UPDATE SET last_active = ?, agent_name = ?`
      )
      .run(id, agentName, now, now, now, agentName);
  }

  getSessions(): Session[] {
    return this.db
      .prepare("SELECT * FROM sessions ORDER BY last_active DESC")
      .all() as Session[];
  }

  addMessage(
    sessionId: string,
    role: "user" | "agent" | "tool",
    content: string,
    toolName?: string,
    toolStatus?: string
  ): void {
    this.db
      .prepare(
        `INSERT INTO messages (session_id, role, content, tool_name, tool_status, created_at)
         VALUES (?, ?, ?, ?, ?, ?)`
      )
      .run(sessionId, role, content, toolName || null, toolStatus || null, Date.now());
  }

  getMessages(sessionId: string, limit: number = 200): Message[] {
    return this.db
      .prepare(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC LIMIT ?"
      )
      .all(sessionId, limit) as Message[];
  }

  getConfig(key: string): string | null {
    const row = this.db
      .prepare("SELECT value FROM config WHERE key = ?")
      .get(key) as { value: string } | undefined;
    return row?.value ?? null;
  }

  setConfig(key: string, value: string): void {
    this.db.exec(
      `CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL)`
    );
    this.db
      .prepare(
        "INSERT INTO config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?"
      )
      .run(key, value, value);
  }
}
