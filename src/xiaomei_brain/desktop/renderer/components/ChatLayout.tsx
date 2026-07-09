import React, { useState, useEffect } from "react";
import { useGateway } from "../hooks/useGateway";
import { Session } from "../types";
import { SessionList } from "./SessionList";
import { ChatView } from "./ChatView";
import { ToolPanel } from "./ToolPanel";
import { InputBar } from "./InputBar";

interface Props {
  gateway: ReturnType<typeof useGateway>;
}

export function ChatLayout({ gateway }: Props) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSessionId, setActiveSessionId] = useState(gateway.conn.sessionId);
  const [showToolPanel, setShowToolPanel] = useState(false);
  const [toolData, setToolData] = useState<{
    name: string;
    status: string;
    params?: unknown;
    result?: unknown;
  } | null>(null);

  useEffect(() => {
    window.gateway.getSessions().then(setSessions);
  }, [gateway.conn.sessionId]);

  useEffect(() => {
    if (gateway.conn.sessionId) {
      setActiveSessionId(gateway.conn.sessionId);
    }
  }, [gateway.conn.sessionId]);

  useEffect(() => {
    const handler = (event: string, data: unknown) => {
      if (event === "tool.start") {
        const d = data as Record<string, unknown>;
        setToolData({
          name: (d["name"] || d["text"]) as string,
          status: "running",
          params: d["params"],
        });
        setShowToolPanel(true);
      } else if (event === "tool.complete") {
        const d = data as Record<string, unknown>;
        setToolData((prev) =>
          prev
            ? { ...prev, status: "completed", result: d["text"] || d["result"] }
            : null
        );
      }
    };
    window.gateway.onEvent(handler);
    return () => {};
  }, []);

  return (
    <div className="chat-layout">
      <SessionList
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelect={(id) => setActiveSessionId(id)}
      />
      <div className="chat-center">
        <ChatView gateway={gateway} sessionId={activeSessionId} />
        <InputBar gateway={gateway} />
      </div>
      {showToolPanel && toolData && (
        <ToolPanel
          toolName={toolData.name}
          status={toolData.status}
          params={toolData.params}
          result={toolData.result}
          onClose={() => setShowToolPanel(false)}
        />
      )}
    </div>
  );
}
