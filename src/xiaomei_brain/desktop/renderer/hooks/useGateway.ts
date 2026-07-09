import { useState, useCallback, useRef } from "react";

export interface ConnectionState {
  status: "disconnected" | "connecting" | "connected" | "error";
  sessionId: string;
  agentName: string;
  error: string;
}

export function useGateway() {
  const [conn, setConn] = useState<ConnectionState>({
    status: "disconnected",
    sessionId: "",
    agentName: "",
    error: "",
  });

  const connect = useCallback(
    async (host: string, port: number, token: string, userId: string) => {
      setConn((c) => ({ ...c, status: "connecting", error: "" }));
      const res = await window.gateway.connect({ host, port, token, userId });
      if (res.error) {
        const errMsg = res.error.message;
        setConn((c) => ({
          ...c,
          status: "error",
          error: errMsg,
        }));
        return false;
      }
      const result = res.result || {};
      setConn({
        status: "connected",
        sessionId: (result.session_id as string) || "",
        agentName: (result.agent_name as string) || "",
        error: "",
      });
      return true;
    },
    []
  );

  const disconnect = useCallback(async () => {
    await window.gateway.disconnect();
    setConn({ status: "disconnected", sessionId: "", agentName: "", error: "" });
  }, []);

  const sendMessage = useCallback(async (content: string) => {
    const res = await window.gateway.sendMessage({ content });
    return res;
  }, []);

  const abortMessage = useCallback(async () => {
    await window.gateway.abortMessage();
  }, []);

  const getHistory = useCallback(
    async (sessionId?: string, limit?: number) => {
      const res = await window.gateway.getHistory({ sessionId, limit });
      if (res.error) return [];
      return (res.result?.messages as unknown[]) || [];
    },
    []
  );

  const listIdentities = useCallback(async () => {
    const res = await window.gateway.listIdentities();
    if (res.error) return [];
    return (res.result?.identities as unknown[]) || [];
  }, []);

  return {
    conn,
    connect,
    disconnect,
    sendMessage,
    abortMessage,
    getHistory,
    listIdentities,
  };
}
