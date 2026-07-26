import { useTranslation } from "react-i18next";
import type { AssignmentSnapshot } from "../../store";

export function AssignmentCard({
  assignment,
  onOpen,
}: {
  assignment: AssignmentSnapshot;
  onOpen: (assignmentId: string) => void;
}) {
  const { t } = useTranslation();
  const hasSteps = assignment.totalSteps !== null && assignment.totalSteps > 0;
  const progress = hasSteps
    ? Math.min(100, Math.round(((assignment.completedSteps || 0) / assignment.totalSteps!) * 100))
    : assignment.status === "completed" ? 100 : null;
  const indeterminate = progress === null && ["queued", "in_progress"].includes(assignment.status);
  const summary = assignment.status === "waiting_person"
    ? assignment.waitingReason
    : assignment.progressSummary || assignment.objective;

  return (
    <button type="button" className="assignment-card" onClick={() => onOpen(assignment.id)}>
      <span className="assignment-card-heading">
        <span className="assignment-card-kicker">{t("assignments.label")}</span>
        <span className={`assignment-status assignment-status-${assignment.status}`}>
          {t(`assignments.status.${assignment.status}`)}
        </span>
      </span>
      <strong>{assignment.title}</strong>
      {summary && <span className="assignment-card-summary">{summary}</span>}
      {progress !== null && (
        <span className="assignment-progress" aria-label={`${progress}%`}>
          <span style={{ width: `${progress}%` }} />
        </span>
      )}
      {indeterminate && (
        <span className="assignment-progress indeterminate" aria-label={t("assignments.inProgress")}>
          <span />
        </span>
      )}
    </button>
  );
}
