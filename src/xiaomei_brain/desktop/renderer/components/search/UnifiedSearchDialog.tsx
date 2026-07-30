import { useEffect, useMemo, useRef, useState } from "react";
import { useCoreStore } from "../../store";
import { Icon, type IconName } from "../ui";
import { UNIFIED_SEARCH_EVENT } from "./events";

type SearchKind = "sessions" | "messages" | "artifacts" | "assignments";

interface SearchItem {
  id: string;
  session_id: string;
  title?: string;
  snippet?: string;
  role?: string;
  kind?: string;
  status?: string;
  created_at?: number;
  updated_at?: number;
  message_count?: number;
  artifact_id?: string;
  assignment_id?: string;
  message_id?: number;
}

type SearchResult = Record<SearchKind, SearchItem[]>;

const EMPTY_RESULT: SearchResult = {
  sessions: [], messages: [], artifacts: [], assignments: [],
};

const SECTION_META: Array<{
  kind: SearchKind; label: string; icon: IconName;
}> = [
  { kind: "sessions", label: "会话", icon: "folder" },
  { kind: "messages", label: "消息", icon: "search" },
  { kind: "artifacts", label: "产物", icon: "file-text" },
  { kind: "assignments", label: "委托", icon: "sparkles" },
];

export function UnifiedSearchDialog() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<SearchResult>(EMPTY_RESULT);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const requestIdRef = useRef(0);
  const activeAgentId = useCoreStore((state) => state.activeAgentId);
  const agentName = useCoreStore((state) => {
    const agentId = state.activeAgentId;
    if (!agentId) return "Agent";
    return state.connectionByAgent[agentId]?.agentName
      || state.agents.find((agent) => agent.id === agentId)?.name
      || "Agent";
  });
  const connected = useCoreStore((state) => (
    state.connectionByAgent[state.activeAgentId || ""]?.status === "connected"
  ));
  const switchSession = useCoreStore((state) => state.switchSession);
  const openSearchMessage = useCoreStore((state) => state.openSearchMessage);

  useEffect(() => {
    const show = () => {
      setOpen(true);
      window.setTimeout(() => inputRef.current?.focus(), 0);
    };
    const keyboard = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        show();
      }
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener(UNIFIED_SEARCH_EVENT, show);
    window.addEventListener("keydown", keyboard);
    return () => {
      window.removeEventListener(UNIFIED_SEARCH_EVENT, show);
      window.removeEventListener("keydown", keyboard);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    const normalized = query.trim();
    if (!normalized || !activeAgentId || !connected) {
      setResult(EMPTY_RESULT);
      setLoading(false);
      setError("");
      return;
    }
    const timer = window.setTimeout(() => {
      const requestId = ++requestIdRef.current;
      setLoading(true);
      setError("");
      void window.gateway.unifiedSearch({
        agentId: activeAgentId,
        query: normalized,
        limit: 8,
      }).then((response) => {
        if (requestId !== requestIdRef.current) return;
        if (response.error) {
          setError(response.error.message);
          setResult(EMPTY_RESULT);
          return;
        }
        const value = response.result || {};
        setResult({
          sessions: searchItems(value.sessions),
          messages: searchItems(value.messages),
          artifacts: searchItems(value.artifacts),
          assignments: searchItems(value.assignments),
        });
      }).catch((reason) => {
        if (requestId === requestIdRef.current) setError(String(reason));
      }).finally(() => {
        if (requestId === requestIdRef.current) setLoading(false);
      });
    }, 250);
    return () => window.clearTimeout(timer);
  }, [activeAgentId, connected, open, query]);

  const total = useMemo(
    () => Object.values(result).reduce((count, items) => count + items.length, 0),
    [result],
  );

  const selectItem = async (kind: SearchKind, item: SearchItem) => {
    if (kind === "messages" && item.session_id && item.message_id) {
      await openSearchMessage(item.session_id, item.message_id);
    } else if (item.session_id) {
      await switchSession(item.session_id);
    }
    if (kind === "artifacts") {
      window.dispatchEvent(new CustomEvent("xiaomei:open-search-artifact", {
        detail: { sessionId: item.session_id, artifactId: item.artifact_id || item.id },
      }));
    } else if (kind === "assignments") {
      window.dispatchEvent(new CustomEvent("xiaomei:open-search-assignment", {
        detail: { assignmentId: item.assignment_id || item.id },
      }));
    }
    setOpen(false);
  };

  if (!open) return null;
  return (
    <div className="unified-search-backdrop" onMouseDown={() => setOpen(false)}>
      <section
        className="unified-search-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="统一搜索"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="unified-search-input-row">
          <Icon name="search" size={19} />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={`搜索 ${agentName} 的会话、消息、产物和委托`}
          />
          {loading && <span className="unified-search-loading">搜索中</span>}
          {query && !loading && (
            <button type="button" onClick={() => setQuery("")} aria-label="清空搜索">
              <Icon name="x" size={15} />
            </button>
          )}
        </header>
        <div className="unified-search-results">
          {!connected ? (
            <SearchNotice text="当前 Agent 尚未连接" />
          ) : error ? (
            <SearchNotice text={error} error />
          ) : !query.trim() ? (
            <SearchNotice text="输入关键词开始搜索" hint="Ctrl K 可随时打开" />
          ) : !loading && total === 0 ? (
            <SearchNotice text="没有找到相关内容" />
          ) : (
            SECTION_META.map((section) => {
              const items = result[section.kind];
              if (items.length === 0) return null;
              return (
                <div className="unified-search-section" key={section.kind}>
                  <div className="unified-search-section-title">
                    <span>{section.label}</span><small>{items.length}</small>
                  </div>
                  {items.map((item) => (
                    <button
                      type="button"
                      className="unified-search-result"
                      key={`${section.kind}-${item.id}-${item.session_id}`}
                      onClick={() => { void selectItem(section.kind, item); }}
                    >
                      <span className="unified-search-result-icon">
                        <Icon name={section.icon} size={16} />
                      </span>
                      <span className="unified-search-result-content">
                        <strong>{resultTitle(section.kind, item)}</strong>
                        {item.snippet && <span>{item.snippet}</span>}
                      </span>
                      <span className="unified-search-result-meta">
                        {resultMeta(section.kind, item)}
                      </span>
                    </button>
                  ))}
                </div>
              );
            })
          )}
        </div>
        <footer className="unified-search-footer">
          <span>Enter 打开</span><span>Esc 关闭</span>
        </footer>
      </section>
    </div>
  );
}

function searchItems(value: unknown): SearchItem[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((entry): SearchItem[] => {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) return [];
    const item = entry as Record<string, unknown>;
    if (typeof item.id !== "string") return [];
    return [{
      id: item.id,
      session_id: typeof item.session_id === "string" ? item.session_id : "",
      title: typeof item.title === "string" ? item.title : undefined,
      snippet: typeof item.snippet === "string" ? item.snippet : undefined,
      role: typeof item.role === "string" ? item.role : undefined,
      kind: typeof item.kind === "string" ? item.kind : undefined,
      status: typeof item.status === "string" ? item.status : undefined,
      created_at: typeof item.created_at === "number" ? item.created_at : undefined,
      updated_at: typeof item.updated_at === "number" ? item.updated_at : undefined,
      message_count: typeof item.message_count === "number" ? item.message_count : undefined,
      artifact_id: typeof item.artifact_id === "string" ? item.artifact_id : undefined,
      assignment_id: typeof item.assignment_id === "string" ? item.assignment_id : undefined,
      message_id: typeof item.message_id === "number" ? item.message_id : undefined,
    }];
  });
}

function resultTitle(kind: SearchKind, item: SearchItem): string {
  if (item.title) return item.title;
  if (kind === "messages") return item.role === "user" ? "你的消息" : "Agent 回复";
  return "搜索结果";
}

function resultMeta(kind: SearchKind, item: SearchItem): string {
  if (kind === "sessions" && item.message_count !== undefined) return `${item.message_count} 条`;
  if (kind === "assignments" && item.status) return assignmentStatus(item.status);
  const timestamp = item.updated_at || item.created_at;
  return timestamp ? new Date(timestamp * 1000).toLocaleDateString([], { month: "2-digit", day: "2-digit" }) : "";
}

function assignmentStatus(status: string): string {
  return ({
    offered: "待确认", clarifying: "待澄清", accepted: "已接受", queued: "排队中",
    in_progress: "进行中", waiting_person: "等待回复", paused: "已暂停",
    completed: "已完成", declined: "已拒绝", cancelled: "已取消", failed: "失败",
  } as Record<string, string>)[status] || status;
}

function SearchNotice({ text, hint, error = false }: { text: string; hint?: string; error?: boolean }) {
  return (
    <div className={`unified-search-notice ${error ? "error" : ""}`}>
      <span>{text}</span>{hint && <small>{hint}</small>}
    </div>
  );
}
