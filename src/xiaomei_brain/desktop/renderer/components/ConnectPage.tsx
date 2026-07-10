import { useState, useEffect } from "react";
import { useGateway } from "../hooks/useGateway";

interface Props {
  gateway: ReturnType<typeof useGateway>;
  onConnected: () => void;
}

export function ConnectPage({ gateway, onConnected }: Props) {
  const [host, setHost] = useState("localhost");
  const [port, setPort] = useState("19766");
  const [token, setToken] = useState("");
  const [userId, setUserId] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    window.gateway.getConfig("last_host").then((h) => {
      if (h) setHost(h as string);
    });
    window.gateway.getConfig("last_port").then((p) => {
      if (p) setPort(p as string);
    });
  }, []);

  const handleConnect = async () => {
    setLoading(true);
    const ok = await gateway.connect(host, parseInt(port) || 19766, token, userId);
    setLoading(false);
    if (ok) onConnected();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleConnect();
  };

  return (
    <div className="connect-page">
      <div className="connect-card">
        <h1>xiaomei-brain</h1>
        <p className="connect-subtitle">连接到 Gateway</p>

        <div className="connect-field">
          <label>地址</label>
          <input
            value={host}
            onChange={(e) => setHost(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="localhost"
          />
        </div>

        <div className="connect-field">
          <label>端口</label>
          <input
            value={port}
            onChange={(e) => setPort(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="19766"
          />
        </div>

        <div className="connect-field">
          <label>Token (可选)</label>
          <input
            value={token}
            onChange={(e) => setToken(e.target.value)}
            onKeyDown={handleKeyDown}
            type="password"
            placeholder="留空则跳过认证"
          />
        </div>

        <div className="connect-field">
          <label>用户身份 (可选)</label>
          <input
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入 user_id"
          />
        </div>

        {gateway.conn.error && (
          <p className="connect-error">{gateway.conn.error}</p>
        )}

        <button
          className="connect-btn"
          onClick={handleConnect}
          disabled={loading}
        >
          {loading ? "连接中..." : "连接"}
        </button>
      </div>
    </div>
  );
}
