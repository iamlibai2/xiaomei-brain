import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import { useCoreStore, DisplayMessage, HomeMode } from "../../store";
import { Button, Icon } from "../ui";
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
  const sending = useCoreStore((s) => s.sendingByAgent[s.activeAgentId || ""] || false);
  const mode = useCoreStore((s) => s.mode);
  const agentName = useCoreStore((s) => {
    const agentId = s.activeAgentId;
    if (!agentId) return t("home.defaultAgentName");
    return s.connectionByAgent[agentId]?.agentName
      || s.agents.find((agent) => agent.id === agentId)?.name
      || t("home.defaultAgentName");
  });
  const activeAgent = useCoreStore((s) => s.agents.find((agent) => agent.id === s.activeAgentId));
  const activeAgentOnline = useCoreStore((s) => s.localAvailabilityByAgent[s.activeAgentId || ""]);
  const activeAgentInfo = useCoreStore((s) => s.localInfoByAgent[s.activeAgentId || ""]);
  const activeAgentLifecycle = useCoreStore((s) => s.lifecycleByAgent[s.activeAgentId || ""]);
  const controlLocalAgent = useCoreStore((s) => s.controlLocalAgent);
  const sendMessage = useCoreStore((s) => s.sendMessage);
  const abortMessage = useCoreStore((s) => s.abortMessage);
  const setMode = useCoreStore((s) => s.setMode);
  const activeSessionId = useCoreStore((s) => s.activeSessionByAgent[s.activeAgentId || ""] || null);
  const sessionsByAgent = useCoreStore((s) => s.sessionsByAgent);
  const historyPage = useCoreStore((s) => {
    const agentId = s.activeAgentId;
    const sessionId = agentId ? s.activeSessionByAgent[agentId] : null;
    return agentId && sessionId ? s.historyPaginationByAgent[agentId]?.[sessionId] : undefined;
  });
  const loadOlderMessages = useCoreStore((s) => s.loadOlderMessages);

  const [rightPanelOpen, setRightPanelOpen] = useState(false);

  const bottomRef = useRef<HTMLDivElement>(null);
  const topRef = useRef<HTMLDivElement>(null);
  const messageListRef = useRef<HTMLDivElement>(null);
  const previousFirstMessageId = useRef<string | null>(null);

  useEffect(() => {
    const firstMessageId = messages[0]?.id || null;
    const previousFirst = previousFirstMessageId.current;
    const historyWasPrepended = Boolean(
      previousFirst
      && firstMessageId !== previousFirst
      && messages.some((message) => message.id === previousFirst),
    );
    if (!historyWasPrepended) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    previousFirstMessageId.current = firstMessageId;
  }, [messages]);

  const loadOlderPreservingPosition = useCallback(async () => {
    const list = messageListRef.current;
    const previousHeight = list?.scrollHeight || 0;
    await loadOlderMessages();
    requestAnimationFrame(() => {
      if (list) list.scrollTop += list.scrollHeight - previousHeight;
    });
  }, [loadOlderMessages]);

  useEffect(() => {
    const sentinel = topRef.current;
    const list = messageListRef.current;
    if (!sentinel || !list || !historyPage?.hasMore || historyPage.loading || historyPage.error) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) void loadOlderPreservingPosition();
    }, { root: list, threshold: 0.1 });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [activeAgentId, activeSessionId, historyPage?.hasMore, historyPage?.loading, historyPage?.error, loadOlderPreservingPosition]);

  const hasMessages = messages.length > 0;
  const showAgentStart = !hasMessages && activeAgent?.source === "local" && activeAgentOnline === false;
  const agentStarting = activeAgentLifecycle?.status === "starting" || activeAgentLifecycle?.status === "restarting";
  const agentNeedsRestart = Boolean(activeAgentInfo?.pid);

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
      {!hasMessages && !showAgentStart && (
        <div className="activity-banner">
          <button className="activity-banner-button">
            {t("home.earnPoints")}
          </button>
        </div>
      )}
      <div className="wb-home-page">
        {showAgentStart && activeAgent && activeAgentId && (
          <div className="agent-start-state">
            <div className="agent-start-avatar">{activeAgent.name.charAt(0)}</div>
            <h1>
              {agentNeedsRestart
                ? t("home.agentDisconnectedTitle", { name: activeAgent.name })
                : t("home.agentCreatedTitle", { name: activeAgent.name })}
            </h1>
            <p className="agent-start-role">
              <span>{t("home.agentResponsibility")}</span>
              {activeAgent.description || t("home.agentResponsibilityFallback")}
            </p>
            {agentNeedsRestart && (
              <p className="agent-start-status-hint">{t("home.agentDisconnectedHint")}</p>
            )}
            <Button
              variant="primary"
              size="lg"
              icon={agentStarting ? "refresh" : "play"}
              disabled={agentStarting}
              onClick={() => { void controlLocalAgent(activeAgentId, agentNeedsRestart ? "restart" : "start"); }}
            >
              {agentStarting
                ? t("home.agentStarting")
                : agentNeedsRestart
                  ? t("home.restartAgent", { name: activeAgent.name })
                  : t("home.startAgent", { name: activeAgent.name })}
            </Button>
            {activeAgentLifecycle?.status === "error" && (
              <div className="agent-start-error">{activeAgentLifecycle.error}</div>
            )}
          </div>
        )}
        {!hasMessages && !showAgentStart && (
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
            <div className="message-list" ref={messageListRef}>
              <div ref={topRef} className="history-page-status">
                {historyPage?.loading && t("home.loadingOlder")}
                {historyPage?.error && (
                  <button type="button" onClick={() => { void loadOlderPreservingPosition(); }}>
                    {t("home.retryOlder")}
                  </button>
                )}
                {historyPage && !historyPage.hasMore && !historyPage.loading && !historyPage.error
                  ? t("home.oldestReached")
                  : null}
              </div>
              {messages.map((m) => (
                <MessageRow key={m.id} message={m} agentName={agentName || t("home.defaultAgentName")} />
              ))}
              <div ref={bottomRef} />
            </div>
          </>
        )}
        {!showAgentStart && (
          <div className="wb-home-composer">
            {!hasMessages && <QuickActions onAction={() => {}} />}
            <ChatInput onSend={sendMessage} sending={sending} onAbort={abortMessage} />
            {!hasMessages && <ContextBar />}
          </div>
        )}
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

  if (message.interaction) {
    return <InteractionCard message={message} agentName={agentName} />;
  }

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

function InteractionCard({ message, agentName }: { message: DisplayMessage; agentName: string }) {
  const { t } = useTranslation();
  const interaction = message.interaction!;
  const respondToInteraction = useCoreStore((s) => s.respondToInteraction);
  const [answer, setAnswer] = useState("");
  const canRespond = interaction.status === "pending" || interaction.status === "error";
  const waiting = interaction.status === "responding";

  const submit = (response: string) => {
    if (!canRespond || !response.trim()) return;
    void respondToInteraction(interaction.id, response.trim());
  };

  return (
    <div className="assistant-message-row interaction-message-row">
      <div className="assistant-avatar">
        <div className="assistant-avatar-face">{agentName.charAt(0)}</div>
        <span className="assistant-avatar-name">{agentName}</span>
      </div>
      <div className={`interaction-card interaction-${interaction.status}`}>
        <div className="interaction-card-label">{t("home.interactionLabel")}</div>
        <div className="interaction-card-question">{interaction.question}</div>
        {canRespond && interaction.choices.length > 0 && (
          <div className="interaction-card-choices">
            {interaction.choices.map((choice) => (
              <button type="button" key={choice} onClick={() => submit(choice)}>
                {choice}
              </button>
            ))}
          </div>
        )}
        {canRespond && interaction.choices.length === 0 && (
          <form
            className="interaction-card-answer"
            onSubmit={(event) => {
              event.preventDefault();
              submit(answer);
            }}
          >
            <input
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
              placeholder={t("home.interactionAnswerPlaceholder")}
              autoFocus
            />
            <button type="submit" disabled={!answer.trim()}>{t("home.interactionSubmit")}</button>
          </form>
        )}
        {waiting && <div className="interaction-card-status">{t("home.interactionSending")}</div>}
        {interaction.status === "answered" && (
          <div className="interaction-card-status interaction-card-result">
            {t("home.interactionAnswered", { answer: interaction.response })}
          </div>
        )}
        {interaction.status === "expired" && (
          <div className="interaction-card-status">{t("home.interactionExpired")}</div>
        )}
        {interaction.status === "cancelled" && (
          <div className="interaction-card-status">{t("home.interactionCancelled")}</div>
        )}
        {interaction.status === "error" && interaction.error && (
          <div className="interaction-card-error">{interaction.error}</div>
        )}
      </div>
    </div>
  );
}
