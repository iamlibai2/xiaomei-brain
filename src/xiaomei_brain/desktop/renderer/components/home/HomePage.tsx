import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import { useCoreStore, DisplayMessage, HomeMode } from "../../store";
import { Icon } from "../ui";
import { HomeHeader } from "./HomeHeader";
import { SceneTabs } from "./SceneTabs";
import { GrowthBuddy } from "./GrowthBuddy";
import { QuickActions } from "./QuickActions";
import { ChatInput } from "./ChatInput";
import { ContextBar } from "./ContextBar";
import { ChatTopbar } from "./ChatTopbar";

const EMPTY_MSGS: DisplayMessage[] = [];

export function HomePage() {
  const { t } = useTranslation();
  const activeAgentId = useCoreStore((s) => s.activeAgentId);
  const messages = useCoreStore((s) => s.messagesByAgent[s.activeAgentId || ""] || EMPTY_MSGS);
  const sending = useCoreStore((s) => s.sending);
  const mode = useCoreStore((s) => s.mode);
  const agentName = useCoreStore((s) => {
    const agentId = s.activeAgentId;
    if (!agentId) return t("home.defaultAgentName");
    return s.connectionByAgent[agentId]?.agentName || t("home.defaultAgentName");
  });
  const sendMessage = useCoreStore((s) => s.sendMessage);
  const abortMessage = useCoreStore((s) => s.abortMessage);
  const setMode = useCoreStore((s) => s.setMode);
  const activeSessionId = useCoreStore((s) => s.activeSessionId);
  const sessionsByAgent = useCoreStore((s) => s.sessionsByAgent);

  const [rightPanelOpen, setRightPanelOpen] = useState(false);

  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const hasMessages = messages.length > 0;

  const taskName = (() => {
    if (activeSessionId && activeAgentId) {
      const sessions = sessionsByAgent[activeAgentId] || [];
      const s = sessions.find((x) => x.id === activeSessionId);
      if (s) return s.name;
    }
    return agentName || t("home.defaultAgentName");
  })();

  return (
    <div className="main-content">
      {!hasMessages && (
        <div className="activity-banner">
          <button className="activity-banner-button">
            {t("home.earnPoints")}
          </button>
        </div>
      )}
      <div className="wb-home-page">
        {!hasMessages && (
          <>
            <HomeHeader mode={mode} />
            <SceneTabs selected={mode} onSelect={(m) => setMode(m as HomeMode)} />
            <GrowthBuddy />
          </>
        )}
        {hasMessages && (
          <>
            <ChatTopbar
              taskName={taskName}
              onSearch={() => {}}
              onToggleRightPanel={() => setRightPanelOpen(!rightPanelOpen)}
              rightPanelOpen={rightPanelOpen}
            />
            <div className="message-list">
              {messages.map((m) => (
                <MessageRow key={m.id} message={m} agentName={agentName || t("home.defaultAgentName")} />
              ))}
              <div ref={bottomRef} />
            </div>
          </>
        )}
        <div className="wb-home-composer">
          {!hasMessages && <QuickActions onAction={() => {}} />}
          <ChatInput onSend={sendMessage} sending={sending} onAbort={abortMessage} />
          {!hasMessages && <ContextBar />}
        </div>
      </div>
    </div>
  );
}

// ── 解析 ANSI 转义码，分离思考内容和正文 ──

function parseThinkingContent(raw: string, streaming: boolean): { thinking: string; content: string } {
  const ansiDim = /\x1b\[2m([\s\S]*?)\x1b\[0m/g;
  const thinkingParts: string[] = [];
  let content = raw.replace(ansiDim, (_, t) => {
    thinkingParts.push(t.trim());
    return "";
  });
  const bareDim = /\[2m([\s\S]*?)\[0m/g;
  content = content.replace(bareDim, (_, t) => {
    thinkingParts.push(t.trim());
    return "";
  });

  if (streaming) {
    const openTag = /\x1b\[2m([\s\S]*?)$/;
    const m = content.match(openTag);
    if (m) {
      thinkingParts.push(m[1].trim());
      content = content.replace(openTag, "");
    }
    const bareOpen = /\[2m([\s\S]*?)$/;
    const bm = content.match(bareOpen);
    if (bm) {
      thinkingParts.push(bm[1].trim());
      content = content.replace(bareOpen, "");
    }
  }

  return {
    thinking: thinkingParts.join("\n\n").trim(),
    content: content.trim(),
  };
}

function MessageRow({ message, agentName }: { message: DisplayMessage; agentName: string }) {
  const { t } = useTranslation();
  const isUser = message.role === "user";
  const [thinkingExpanded, setThinkingExpanded] = useState(false);

  if (isUser) {
    return (
      <div className="user-message-row">
        <div className="user-message-bubble">
          {message.content}
        </div>
      </div>
    );
  }

  const { thinking, content } = parseThinkingContent(message.content, message.streaming);
  const hasThinking = thinking.length > 0;
  const thinkingComplete = !message.streaming || /\x1b\[0m/.test(message.content) || /\[0m/.test(message.content);

  return (
    <div className="assistant-message-row">
      <div className="assistant-avatar">
        <div className="assistant-avatar-face">
          {agentName.charAt(0)}
        </div>
        <span className="assistant-avatar-name">{agentName}</span>
      </div>
      {hasThinking && (
        <div className={`thinking-block ${!thinkingExpanded ? "thinking-collapsed" : ""} ${thinkingComplete ? "thinking-complete" : ""}`}>
          <div
            className={`thinking-header ${!thinkingComplete ? "thinking-loading" : ""}`}
            onClick={() => setThinkingExpanded(!thinkingExpanded)}
          >
            <span className="thinking-title">{t("home.deepThink")}</span>
            {thinkingComplete && (
              <span className={`thinking-chevron ${thinkingExpanded ? "expanded" : ""}`}>▼</span>
            )}
          </div>
          {thinkingExpanded && (
            <div className="thinking-content">
              {thinking}
            </div>
          )}
        </div>
      )}
      <div className="assistant-text-content">
        <ReactMarkdown
          className="message-md"
          components={{
            pre({ children }) {
              return <div className="md-pre-wrapper"><div className="md-pre-container">{children}</div></div>;
            },
            code({ className, children, ...props }) {
              const match = /language-(\w+)/.exec(className || "");
              const codeStr = String(children).replace(/\n$/, "");
              const isInline = !match && !String(children).includes("\n");
              if (isInline) {
                return <code className={className} {...props}>{children}</code>;
              }
              return (
                <>
                  <div className="md-pre-header">
                    <span className="md-pre-lang">{match ? match[1] : "code"}</span>
                    <button
                      className="md-pre-copy"
                      onClick={() => navigator.clipboard.writeText(codeStr)}
                    >
                      <Icon name="copy" size={14} />
                      {t("home.copy")}
                    </button>
                  </div>
                  <pre><code className={className} {...props}>{children}</code></pre>
                </>
              );
            },
          }}
        >
          {hasThinking ? content : message.content}
        </ReactMarkdown>
      </div>
    </div>
  );
}
