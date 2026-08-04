import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useState,
} from "react";
import type {
  ChatInvocationSelection,
  ComposerInvocationCatalog,
  ComposerInvocationOption,
  InvocationProcessOption,
} from "../../types";

export interface SlashInvocationMenuHandle {
  handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>): boolean;
}

interface SlashInvocationMenuProps {
  agentId: string;
  query: string;
  onSelect: (selection: ChatInvocationSelection) => void;
  onClose: () => void;
}

type MenuEntry = ComposerInvocationOption & { section: string };

const EMPTY_CATALOG: ComposerInvocationCatalog = {
  capabilities: [],
  skills: [],
  execution_modes: [],
};

function normalized(value: string): string {
  return value.trim().toLocaleLowerCase();
}

function matches(option: ComposerInvocationOption, query: string): boolean {
  const needle = normalized(query);
  if (!needle) return true;
  return [option.name, option.id, option.description, ...(option.tags || [])]
    .some((value) => normalized(value).includes(needle));
}

export const SlashInvocationMenu = forwardRef<
  SlashInvocationMenuHandle,
  SlashInvocationMenuProps
>(function SlashInvocationMenu({ agentId, query, onSelect, onClose }, ref) {
  const [catalog, setCatalog] = useState(EMPTY_CATALOG);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [pendingCapability, setPendingCapability] = useState<ComposerInvocationOption | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    setPendingCapability(null);
    void window.gateway.getInteractionCatalog({ agentId }).then((response) => {
      if (!active) return;
      if (response.error) throw new Error(response.error.message);
      const result = (response.result || {}) as unknown as ComposerInvocationCatalog;
      setCatalog({
        capabilities: Array.isArray(result.capabilities) ? result.capabilities : [],
        skills: Array.isArray(result.skills) ? result.skills : [],
        execution_modes: Array.isArray(result.execution_modes) ? result.execution_modes : [],
      });
    }).catch((reason) => {
      if (active) setError(reason instanceof Error ? reason.message : String(reason));
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [agentId]);

  const entries = useMemo<MenuEntry[]>(() => {
    if (pendingCapability) return [];
    return [
      ...catalog.capabilities.filter((item) => matches(item, query)).map((item) => ({
        ...item, section: "能力",
      })),
      ...catalog.skills.filter((item) => matches(item, query)).map((item) => ({
        ...item, section: "工作方法",
      })),
      ...catalog.execution_modes.filter((item) => matches(item, query)).map((item) => ({
        ...item, section: "执行方式",
      })),
    ].slice(0, 24);
  }, [catalog, pendingCapability, query]);

  const processes = pendingCapability?.processes || [];
  const selectableCount = pendingCapability ? processes.length + 1 : entries.length;

  useEffect(() => {
    setActiveIndex(0);
  }, [query, pendingCapability]);

  const selectEntry = (entry: ComposerInvocationOption) => {
    if (entry.kind === "capability" && (entry.processes?.length || 0) > 0) {
      setPendingCapability(entry);
      return;
    }
    onSelect({ kind: entry.kind, id: entry.id, name: entry.name });
  };

  const selectProcess = (process?: InvocationProcessOption) => {
    if (!pendingCapability) return;
    onSelect({
      kind: "capability",
      id: pendingCapability.id,
      name: pendingCapability.name,
      processTemplateId: process?.id,
      processName: process?.name,
    });
  };

  useImperativeHandle(ref, () => ({
    handleKeyDown(event) {
      if (event.key === "Escape") {
        if (pendingCapability) setPendingCapability(null);
        else onClose();
        event.preventDefault();
        return true;
      }
      if (!selectableCount) return false;
      if (event.key === "ArrowDown") {
        setActiveIndex((value) => (value + 1) % selectableCount);
        event.preventDefault();
        return true;
      }
      if (event.key === "ArrowUp") {
        setActiveIndex((value) => (value - 1 + selectableCount) % selectableCount);
        event.preventDefault();
        return true;
      }
      if (event.key === "Enter" && !event.shiftKey) {
        if (pendingCapability) {
          selectProcess(activeIndex === 0 ? undefined : processes[activeIndex - 1]);
        } else if (entries[activeIndex]) {
          selectEntry(entries[activeIndex]);
        }
        event.preventDefault();
        return true;
      }
      return false;
    },
  }), [activeIndex, entries, onClose, pendingCapability, processes, selectableCount]);

  if (loading) {
    return <div className="slash-invocation-menu is-message">正在读取小美的能力…</div>;
  }
  if (error) {
    return <div className="slash-invocation-menu is-message">暂时无法读取工作方式</div>;
  }

  if (pendingCapability) {
    return (
      <div className="slash-invocation-menu" role="listbox" aria-label="选择交付标准">
        <div className="slash-invocation-heading">
          <button type="button" onClick={() => setPendingCapability(null)} aria-label="返回">←</button>
          <div>
            <strong>{pendingCapability.name}</strong>
            <span>选择交付标准（可选）</span>
          </div>
        </div>
        <button
          type="button"
          className={`slash-invocation-item ${activeIndex === 0 ? "is-active" : ""}`}
          onMouseEnter={() => setActiveIndex(0)}
          onClick={() => selectProcess()}
        >
          <span className="slash-invocation-item-main"><strong>由小美判断</strong><small>根据任务需求决定是否使用交付标准</small></span>
        </button>
        {processes.map((process, index) => (
          <button
            type="button"
            key={process.id}
            className={`slash-invocation-item ${activeIndex === index + 1 ? "is-active" : ""}`}
            onMouseEnter={() => setActiveIndex(index + 1)}
            onClick={() => selectProcess(process)}
          >
            <span className="slash-invocation-item-main">
              <strong>{process.name}</strong>
              <small>{process.description}</small>
            </span>
            <span className="slash-invocation-count">{process.stage_count} 阶段</span>
          </button>
        ))}
      </div>
    );
  }

  if (!entries.length) {
    return <div className="slash-invocation-menu is-message">没有匹配的能力或工作方法</div>;
  }

  let previousSection = "";
  return (
    <div className="slash-invocation-menu" role="listbox" aria-label="选择能力或工作方法">
      {entries.map((entry, index) => {
        const heading = entry.section !== previousSection;
        previousSection = entry.section;
        return (
          <div key={`${entry.kind}:${entry.id}`}>
            {heading && <div className="slash-invocation-section">{entry.section}</div>}
            <button
              type="button"
              className={`slash-invocation-item ${activeIndex === index ? "is-active" : ""}`}
              onMouseEnter={() => setActiveIndex(index)}
              onClick={() => selectEntry(entry)}
            >
              <span className={`slash-invocation-kind is-${entry.kind}`}>
                {entry.kind === "capability" ? "能" : entry.kind === "skill" ? "法" : "行"}
              </span>
              <span className="slash-invocation-item-main">
                <strong>{entry.name}</strong>
                <small>{entry.description}</small>
              </span>
              {(entry.processes?.length || 0) > 0 && <span className="slash-invocation-chevron">›</span>}
            </button>
          </div>
        );
      })}
    </div>
  );
});

