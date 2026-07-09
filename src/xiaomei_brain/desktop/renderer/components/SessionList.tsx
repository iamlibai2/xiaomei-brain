import React, { useState } from "react";
import { Session } from "../types";

interface Props {
  sessions: Session[];
  activeSessionId: string;
  onSelect: (sessionId: string) => void;
}

export function SessionList({ sessions, activeSessionId, onSelect }: Props) {
  const [search, setSearch] = useState("");

  const filtered = sessions.filter((s) =>
    s.id.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="session-list">
      <div className="session-search">
        <input
          placeholder="搜索会话..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <div className="session-items">
        {filtered.length === 0 && (
          <p className="session-empty">
            {search ? "无匹配结果" : "暂无会话"}
          </p>
        )}
        {filtered.map((s) => (
          <div
            key={s.id}
            className={`session-item ${s.id === activeSessionId ? "active" : ""}`}
            onClick={() => onSelect(s.id)}
          >
            <span className="session-name">
              {s.agent_name || s.id.slice(0, 8)}
            </span>
            <span className="session-time">
              {new Date(s.last_active).toLocaleDateString("zh-CN")}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
