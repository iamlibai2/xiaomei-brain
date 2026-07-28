import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { AssignmentSnapshot } from "../../store";
import { useCoreStore } from "../../store";

interface PendingInteraction {
  kind: "interaction";
  question: string;
  choices: string[];
}

interface PendingAction {
  kind: "action";
  tool_name: string;
  arguments: Record<string, unknown>;
  summary: string;
  reason: string;
  risk_level: string;
}

type Pending = PendingInteraction | PendingAction | null;

interface AssignmentExecutionStep {
  title: string;
  status: "pending" | "completed";
  summary: string;
}

interface AssignmentExecutionPlan {
  steps: AssignmentExecutionStep[];
  completed_steps: number;
  total_steps: number;
}

interface AssignmentAcceptanceCheck {
  criterion_index: number;
  criterion: string;
  satisfied: boolean;
  evidence: string;
}

interface AssignmentAcceptanceVerification {
  criteria: AssignmentAcceptanceCheck[];
  checked_at?: number;
}

const EMPTY_ASSIGNMENTS: AssignmentSnapshot[] = [];

export function AssignmentPanel({
  selectedId,
  onSelect,
  onClose,
}: {
  selectedId: string | null;
  onSelect: (assignmentId: string) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const agentId = useCoreStore((state) => state.activeAgentId || "");
  const assignments = useCoreStore((state) => state.assignmentsByAgent[state.activeAgentId || ""] || EMPTY_ASSIGNMENTS);
  const loading = useCoreStore((state) => state.assignmentLoadingByAgent[state.activeAgentId || ""] || false);
  const listError = useCoreStore((state) => state.assignmentErrorByAgent[state.activeAgentId || ""] || "");
  const refreshAssignments = useCoreStore((state) => state.refreshAssignments);
  const requestCancel = useCoreStore((state) => state.requestAssignmentCancel);
  const requestResume = useCoreStore((state) => state.requestAssignmentResume);
  const selected = assignments.find((item) => item.id === selectedId) || assignments[0];
  const [pending, setPending] = useState<Pending>(null);
  const [events, setEvents] = useState<Record<string, unknown>[]>([]);
  const [resources, setResources] = useState<Record<string, unknown>[]>([]);
  const [executionPlan, setExecutionPlan] = useState<AssignmentExecutionPlan | null>(null);
  const [acceptanceVerification, setAcceptanceVerification] = useState<AssignmentAcceptanceVerification | null>(null);
  const [answer, setAnswer] = useState("");
  const [actionError, setActionError] = useState("");
  const [acting, setActing] = useState(false);
  const [openingArtifactId, setOpeningArtifactId] = useState("");

  useEffect(() => {
    if (!agentId) return;
    void refreshAssignments(agentId);
  }, [agentId, refreshAssignments]);

  useEffect(() => {
    if (!agentId || !selected?.id) {
      setPending(null);
      setEvents([]);
      setResources([]);
      setExecutionPlan(null);
      setAcceptanceVerification(null);
      return;
    }
    let cancelled = false;
    setActionError("");
    void window.gateway.getAssignment({ agentId, assignmentId: selected.id, eventLimit: 100 })
      .then((response) => {
        if (cancelled) return;
        if (response.error) {
          setActionError(response.error.message);
          return;
        }
        const rawPending = response.result?.pending;
        setPending(rawPending && typeof rawPending === "object" && !Array.isArray(rawPending)
          ? rawPending as unknown as Pending
          : null);
        setEvents(Array.isArray(response.result?.events)
          ? response.result!.events as Record<string, unknown>[]
          : []);
        setResources(Array.isArray(response.result?.resources)
          ? response.result!.resources as Record<string, unknown>[]
          : []);
        const rawPlan = response.result?.execution_plan;
        setExecutionPlan(rawPlan && typeof rawPlan === "object" && !Array.isArray(rawPlan)
          ? rawPlan as unknown as AssignmentExecutionPlan
          : null);
        const rawVerification = response.result?.acceptance_verification;
        setAcceptanceVerification(rawVerification && typeof rawVerification === "object" && !Array.isArray(rawVerification)
          ? rawVerification as unknown as AssignmentAcceptanceVerification
          : null);
      })
      .catch((error) => { if (!cancelled) setActionError(String(error)); });
    return () => { cancelled = true; };
  }, [agentId, selected?.id, selected?.revision]);

  const act = async (operation: () => Promise<string>) => {
    if (acting) return;
    setActing(true);
    setActionError("");
    try {
      const error = await operation();
      setActionError(error);
      if (!error) {
        setAnswer("");
        await refreshAssignments(agentId);
      }
    } finally {
      setActing(false);
    }
  };

  const terminal = selected && ["completed", "declined", "cancelled", "failed"].includes(selected.status);
  const artifactResources = resources.filter((resource) => resource.type === "artifact");
  const explicitDeliverables = artifactResources.filter((resource) => resource.relation === "deliverable");
  const deliverables = explicitDeliverables.length > 0
    ? explicitDeliverables
    : artifactResources.filter((resource) => {
        const metadata = resource.metadata as Record<string, unknown> | undefined;
        const name = String(metadata?.name || "");
        const kind = String(metadata?.kind || "");
        return ["document", "image", "audio", "video"].includes(kind)
          || Boolean(name && selected?.progressSummary.includes(name));
      });
  const supportingResources = resources.filter((resource) => resource.type !== "artifact");
  const progressPercent = executionPlan?.total_steps
    ? Math.round((executionPlan.completed_steps / executionPlan.total_steps) * 100)
    : 0;

  const openArtifact = async (resource: Record<string, unknown>) => {
    if (!selected || openingArtifactId) return;
    const artifactId = String(resource.key || "");
    if (!artifactId) return;
    setOpeningArtifactId(artifactId);
    setActionError("");
    try {
      const result = await window.gateway.openAssignmentArtifact({
        agentId,
        assignmentId: selected.id,
        artifactId,
      });
      if (!result.ok) setActionError(result.error || t("assignments.openFailed"));
    } finally {
      setOpeningArtifactId("");
    }
  };

  return (
      <aside className="assignment-drawer embedded" aria-label={t("assignments.workspace")}>
        <header>
          <div>
            <span>{t("assignments.workspace")}</span>
            <strong>{assignments.length}</strong>
          </div>
          <button type="button" onClick={onClose} aria-label={t("assignments.close")}>×</button>
        </header>
        <div className="assignment-drawer-body">
          <nav className="assignment-drawer-list">
            {loading && assignments.length === 0 && <p>{t("assignments.loading")}</p>}
            {listError && <p className="assignment-error">{listError}</p>}
            {assignments.map((assignment) => (
              <button
                type="button"
                className={assignment.id === selected?.id ? "selected" : ""}
                key={assignment.id}
                onClick={() => onSelect(assignment.id)}
              >
                <span>{assignment.title}</span>
                <small>{t(`assignments.status.${assignment.status}`)}</small>
              </button>
            ))}
          </nav>
          <section className="assignment-detail">
            {!selected && <p className="assignment-empty">{t("assignments.empty")}</p>}
            {selected && (
              <>
                <div className="assignment-detail-title">
                  <span className={`assignment-status assignment-status-${selected.status}`}>
                    {t(`assignments.status.${selected.status}`)}
                  </span>
                  <h2>{selected.title}</h2>
                  <p>{selected.objective}</p>
                </div>
                {selected.progressSummary && (
                  <div className="assignment-detail-block">
                    <h3>
                      {t("assignments.progress")}
                      {executionPlan && (
                        <span className="assignment-plan-percent">{progressPercent}%</span>
                      )}
                    </h3>
                    <p>{selected.progressSummary}</p>
                  </div>
                )}
                {executionPlan && executionPlan.steps.length > 0 && (
                  <div className="assignment-detail-block">
                    <h3>{t("assignments.executionPlan")}</h3>
                    <ol className="assignment-plan">
                      {executionPlan.steps.map((step, index) => {
                        const current = step.status === "pending"
                          && index === executionPlan.completed_steps;
                        return (
                          <li
                            className={`${step.status}${current ? " current" : ""}`}
                            key={`${index}-${step.title}`}
                          >
                            <span className="assignment-plan-marker">
                              {step.status === "completed" ? "✓" : index + 1}
                            </span>
                            <div>
                              <strong>{step.title}</strong>
                              {step.summary && <p>{step.summary}</p>}
                            </div>
                          </li>
                        );
                      })}
                    </ol>
                  </div>
                )}
                {selected.acceptanceCriteria.length > 0 && (
                  <div className="assignment-detail-block">
                    <h3>{t("assignments.acceptance")}</h3>
                    <ul className="assignment-acceptance-list">
                      {selected.acceptanceCriteria.map((criterion, index) => {
                        const check = acceptanceVerification?.criteria.find(
                          (item) => item.criterion_index === index + 1 && item.criterion === criterion,
                        );
                        return (
                          <li className={check ? (check.satisfied ? "satisfied" : "unmet") : "pending"} key={criterion}>
                            <span className="assignment-acceptance-marker">
                              {check ? (check.satisfied ? "✓" : "!") : index + 1}
                            </span>
                            <div>
                              <strong>{criterion}</strong>
                              {check?.evidence && <p>{check.evidence}</p>}
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                )}
                {selected.status === "waiting_person" && (
                  <div className="assignment-response-block">
                    <h3>{pending?.kind === "action" ? pending.summary : pending?.question || selected.waitingReason}</h3>
                    {pending?.kind === "action" ? (
                      <>
                        {pending.reason && <p>{pending.reason}</p>}
                        <pre>{pending.tool_name} {JSON.stringify(pending.arguments, null, 2)}</pre>
                        <div className="assignment-actions">
                          <button disabled={acting} onClick={() => void act(() => requestResume(selected.id, "", "deny"))}>
                            {t("assignments.deny")}
                          </button>
                          <button className="primary" disabled={acting} onClick={() => void act(() => requestResume(selected.id, "", "approve"))}>
                            {t("assignments.approve")}
                          </button>
                        </div>
                      </>
                    ) : (
                      <>
                        {pending?.kind === "interaction" && pending.choices.length > 0 && (
                          <div className="assignment-choice-list">
                            {pending.choices.map((choice) => (
                              <button key={choice} onClick={() => setAnswer(choice)}>{choice}</button>
                            ))}
                          </div>
                        )}
                        <textarea value={answer} onChange={(event) => setAnswer(event.target.value)} placeholder={t("assignments.answerPlaceholder")} />
                        <button className="primary" disabled={acting || !answer.trim()} onClick={() => void act(() => requestResume(selected.id, answer))}>
                          {t("assignments.resume")}
                        </button>
                      </>
                    )}
                  </div>
                )}
                {selected.status === "paused" && (
                  <button className="assignment-primary-action" disabled={acting} onClick={() => void act(() => requestResume(selected.id))}>
                    {t("assignments.resume")}
                  </button>
                )}
                {!terminal && (
                  <button className="assignment-cancel-action" disabled={acting} onClick={() => void act(() => requestCancel(selected.id))}>
                    {t("assignments.cancel")}
                  </button>
                )}
                {actionError && <p className="assignment-error">{actionError}</p>}
                {deliverables.length > 0 && (
                  <div className="assignment-detail-block">
                    <h3>{t("assignments.deliverables")}</h3>
                    <div className="assignment-deliverables">
                      {deliverables.map((resource) => {
                        const metadata = resource.metadata as Record<string, unknown> | undefined;
                        const artifactId = String(resource.key || "");
                        const size = typeof metadata?.size === "number"
                          ? metadata.size < 1024 * 1024
                            ? `${(metadata.size / 1024).toFixed(1)} KB`
                            : `${(metadata.size / 1024 / 1024).toFixed(1)} MB`
                          : "";
                        return (
                          <button
                            type="button"
                            className="assignment-deliverable"
                            key={artifactId}
                            disabled={Boolean(openingArtifactId)}
                            onClick={() => void openArtifact(resource)}
                          >
                            <span>{String(metadata?.name || artifactId)}</span>
                            <small>{openingArtifactId === artifactId ? t("assignments.opening") : size}</small>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}
                {supportingResources.length > 0 && (
                  <div className="assignment-detail-block">
                    <h3>{t("assignments.resources")}</h3>
                    {supportingResources.map((resource, index) => (
                      <div className="assignment-resource" key={`${String(resource.type)}-${String(resource.key)}-${index}`}>
                        {String((resource.metadata as Record<string, unknown> | undefined)?.name || resource.key || resource.type)}
                      </div>
                    ))}
                  </div>
                )}
                {events.length > 0 && (
                  <details className="assignment-events">
                    <summary>{t("assignments.history", { count: events.length })}</summary>
                    {events.slice().reverse().map((event, index) => (
                      <div key={`${String(event.id)}-${index}`}>
                        <span>{String(event.type || "")}</span>
                        <time>{typeof event.created_at === "number" ? new Date(event.created_at * 1000).toLocaleString() : ""}</time>
                      </div>
                    ))}
                  </details>
                )}
              </>
            )}
          </section>
        </div>
      </aside>
  );
}
