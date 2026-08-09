import { useCallback, useEffect, useRef, useState } from "react";
import type { TokenUsageSummary, TokenUsageTotals } from "./types";

export function formatTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 1 : 2)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(value >= 100_000 ? 0 : 1)}K`;
  return String(Math.max(0, Math.round(value || 0)));
}

export function formatTurnUsage(value: TokenUsageTotals): string {
  const estimate = value.estimated_calls > 0 ? "≈" : "";
  return `${estimate}${formatTokens(value.total_tokens)} tokens · ${value.calls}`;
}

export function useTokenUsage(
  agentId: string,
  sessionId = "",
  enabled = true,
) {
  const [summary, setSummary] = useState<TokenUsageSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const refreshTimer = useRef<number>();

  const refresh = useCallback(async () => {
    if (!enabled || !agentId) return;
    setLoading(true);
    const response = await window.gateway.getUsageSummary({
      agentId,
      sessionId,
      turnLimit: 120,
    });
    if (response.error) {
      setError(response.error.message || "Unable to load token usage");
    } else {
      setSummary((response.result?.usage || null) as TokenUsageSummary | null);
      setError("");
    }
    setLoading(false);
  }, [agentId, enabled, sessionId]);

  useEffect(() => {
    setSummary(null);
    if (enabled) void refresh();
  }, [enabled, refresh]);

  useEffect(() => {
    if (!enabled || !agentId) return undefined;
    return window.gateway.onEvent((event: { event?: string; agentId?: string }) => {
      if (event.event !== "usage.updated" || event.agentId !== agentId) return;
      window.clearTimeout(refreshTimer.current);
      refreshTimer.current = window.setTimeout(() => void refresh(), 220);
    });
  }, [agentId, enabled, refresh]);

  useEffect(() => () => window.clearTimeout(refreshTimer.current), []);
  return { summary, loading, error, refresh };
}
