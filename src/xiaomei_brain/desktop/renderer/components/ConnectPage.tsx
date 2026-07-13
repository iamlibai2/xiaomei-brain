import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useCoreStore } from "../store";
import { Button } from "./ui";

export function ConnectPage() {
  const { t } = useTranslation();
  const connect = useCoreStore((s) => s.connect);
  const setPage = useCoreStore((s) => s.setPage);

  const [host, setHost] = useState("localhost");
  const [port, setPort] = useState("19766");
  const [token, setToken] = useState("");
  const [userId, setUserId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    window.gateway.getConfig("last_host").then((h) => {
      if (h) setHost(h);
    });
    window.gateway.getConfig("last_port").then((p) => {
      if (p) setPort(p);
    });
  }, []);

  const handleConnect = async () => {
    setLoading(true);
    setError("");
    const ok = await connect(host, parseInt(port) || 19766, token, userId);
    setLoading(false);
    if (ok) setPage("chat");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleConnect();
  };

  return (
    <div className="connect-page">
      <div className="connect-card">
        <h1>xiaomei-brain</h1>
        <p className="connect-subtitle">{t("connect.title")}</p>

        <div className="connect-field">
          <label>{t("connect.host")}</label>
          <input
            value={host}
            onChange={(e) => setHost(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="localhost"
          />
        </div>

        <div className="connect-field">
          <label>{t("connect.port")}</label>
          <input
            value={port}
            onChange={(e) => setPort(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="19766"
          />
        </div>

        <div className="connect-field">
          <label>{t("connect.token")}</label>
          <input
            value={token}
            onChange={(e) => setToken(e.target.value)}
            onKeyDown={handleKeyDown}
            type="password"
            placeholder={t("connect.tokenHint")}
          />
        </div>

        <div className="connect-field">
          <label>{t("connect.userId")}</label>
          <input
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t("connect.userIdPlaceholder")}
          />
        </div>

        {error && (
          <p className="connect-error">{error}</p>
        )}

        <Button
          variant="primary"
          size="lg"
          className="connect-btn"
          onClick={handleConnect}
          disabled={loading}
        >
          {loading ? t("connect.connecting") : t("connect.connect")}
        </Button>
      </div>
    </div>
  );
}
