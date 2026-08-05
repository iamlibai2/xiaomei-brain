import type { ProjectDetailSnapshot } from "../../store";
import { Icon } from "../ui";
import { useTranslation } from "react-i18next";

const projectKey = (prefix: string, value: string) => `projectUi.${prefix}${value.replace(/(^|_)([a-z])/g, (_, __, char) => char.toUpperCase())}`;

export function ProjectPanel({
  detail,
  loading,
  error,
  onRefresh,
}: {
  detail: ProjectDetailSnapshot | null;
  loading: boolean;
  error: string;
  onRefresh: () => void;
}) {
  const { t } = useTranslation();
  if (loading && !detail) {
    return <section className="current-project-card loading">{t("projectUi.loading")}</section>;
  }
  if (error && !detail) {
    return (
      <section className="current-project-card error">
        <span>{error}</span>
        <button type="button" onClick={onRefresh}>{t("projectUi.retry")}</button>
      </section>
    );
  }
  if (!detail) {
    return (
      <section className="project-sidebar-panel empty">
        <span className="project-sidebar-empty-icon"><Icon name="folder" size={20} /></span>
        <strong>{t("projectUi.emptyTitle")}</strong>
        <p>{t("projectUi.emptyDescription")}</p>
        <button type="button" onClick={onRefresh}>{t("projectUi.refresh")}</button>
      </section>
    );
  }
  const { project, process, steps, assets, assignments, activities, latestReview } = detail;
  const currentStep = project.status === "active"
    ? steps.find((step) => step.stepId === project.currentStepId)
      || steps.find((step) => ["running", "waiting_review", "needs_revision"].includes(step.status))
    : undefined;
  const finished = steps.filter((step) => ["completed", "skipped"].includes(step.status)).length;
  const usesProcessProgress = Boolean(process && process.status !== "abandoned");
  const processStages = process?.stages.filter((stage) => stage.required) || [];
  const processFinished = processStages.filter((stage) => stage.status === "satisfied").length;
  const progressFinished = usesProcessProgress ? processFinished : finished;
  const progressTotal = usesProcessProgress ? processStages.length : steps.length;
  const percent = progressTotal > 0
    ? Math.round((progressFinished / progressTotal) * 100)
    : 0;
  const orderedSteps = steps
    .map((step, index) => ({ step, index }))
    .sort((left, right) => left.step.position - right.step.position || left.index - right.index)
    .map(({ step }) => step);
  const keyAssets = assets
    .filter((asset) => asset.status === "available" && asset.role !== "cache")
    .sort((left, right) => right.updatedAt - left.updatedAt)
    .slice(0, 8);
  const activeAssignments = assignments.filter((assignment) => ![
    "completed", "declined", "cancelled", "failed",
  ].includes(assignment.status));
  const activeActivities = activities.filter((activity) => [
    "queued", "running", "paused",
  ].includes(activity.status));

  return (
    <section className="current-project-card project-sidebar-panel">
      <header>
        <span className="current-project-icon"><Icon name="folder" size={15} /></span>
        <div>
          <small>{t("projectUi.current")}</small>
          <strong>{project.name}</strong>
        </div>
        <span className={`project-status-badge ${project.status}`}>
          {t(projectKey("status", project.status), { defaultValue: project.status })}
        </span>
        <button type="button" onClick={onRefresh} title={t("projectUi.refreshTitle")}>
          <Icon name="refresh" size={14} />
        </button>
      </header>
      {(project.progressSummary || project.summary) && (
        <p>{project.progressSummary || project.summary}</p>
      )}
      {progressTotal > 0 && (
        <div className="current-project-progress">
          <div
            className="current-project-progress-track"
            role="progressbar"
            aria-label={t("projectUi.progress")}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
          >
            <span style={{ width: `${percent}%` }} />
          </div>
          <small>
            {progressFinished}/{progressTotal} {usesProcessProgress ? t("projectUi.submitted") : t("projectUi.settled")} · {percent}%
          </small>
        </div>
      )}
      {project.waitingReason && <p className="current-project-waiting">{project.waitingReason}</p>}
      {process && (
        <section className="project-detail-section project-process-summary">
          <header>
            <strong>{t("projectUi.deliveryStandard")}</strong>
            <small className={process.status}>{t(projectKey("process", process.status), { defaultValue: process.status })}</small>
          </header>
          <div className="project-process-heading">
            <strong>{process.name}</strong>
            <small>{process.ordered ? t("projectUi.ordered") : t("projectUi.unordered")}</small>
          </div>
          <ol className="project-process-stage-list">
            {[...process.stages]
              .sort((left, right) => left.position - right.position)
              .map((stage, index) => (
                <li key={stage.id} className={stage.status}>
                  <span>{stage.status === "satisfied" ? "✓" : index + 1}</span>
                  <div>
                    <div>
                      <strong>{stage.title}</strong>
                    <small>{t(projectKey("stage", stage.status), { defaultValue: stage.status })}</small>
                    </div>
                    {stage.requirementLabels.length > 0 && (
                      <p>{t("projectUi.requirement", { value: stage.requirementLabels.join("、") })}</p>
                    )}
                    {stage.missing.length > 0 && (
                      <p className="missing">{t("projectUi.missing", { value: stage.missing.join("、") })}</p>
                    )}
                    {stage.summary && <p className="submitted">{stage.summary}</p>}
                  </div>
                </li>
              ))}
          </ol>
        </section>
      )}
      {latestReview && (
        <section className="project-detail-section project-review-summary">
          <header>
            <strong>{t("projectUi.latestReview")}</strong>
            <small>{formatTime(latestReview.createdAt)}</small>
          </header>
          <p>{latestReview.assessment}</p>
          {latestReview.deviations.length > 0 && (
            <div>
              <strong>{t("projectUi.deviations")}</strong>
              <ul>{latestReview.deviations.map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
          )}
          {latestReview.planChanges.length > 0 && (
            <div>
              <strong>{t("projectUi.planChanges")}</strong>
              <ul>{latestReview.planChanges.map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
          )}
          {latestReview.nextAction && (
            <p className="project-review-next"><strong>{t("projectUi.next")}</strong>{latestReview.nextAction}</p>
          )}
        </section>
      )}
      {orderedSteps.length > 0 && (
        <section className="project-detail-section">
          <header>
            <strong>{t("projectUi.stages")}</strong>
            <small>{finished}/{orderedSteps.length}</small>
          </header>
          <ol className="project-step-list">
            {orderedSteps.map((step, index) => {
              const isCurrent = currentStep?.stepId === step.stepId;
              return (
                <li
                  key={step.stepId}
                  className={`${step.status}${isCurrent ? " current" : ""}`}
                  aria-current={isCurrent ? "step" : undefined}
                >
                  <div className="project-step-rail">
                    <span>{["completed", "skipped"].includes(step.status) ? "✓" : index + 1}</span>
                  </div>
                  <div className="project-step-content">
                    <div>
                      <strong>{step.title}</strong>
                    <small>{t(projectKey("status", step.status), { defaultValue: step.status })}</small>
                    </div>
                    {step.summary && <p>{step.summary}</p>}
                    {step.totalUnits !== null && (
                      <em>{step.completedUnits || 0}/{step.totalUnits}</em>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        </section>
      )}
      {keyAssets.length > 0 && (
        <section className="project-detail-section">
          <header>
            <strong>{t("projectUi.assets")}</strong>
            <small>{t("projectUi.assetCount", { count: assets.length })}</small>
          </header>
          <ul className="project-asset-list">
            {keyAssets.map((asset) => (
              <li key={asset.id}>
                <span className={`project-asset-icon ${asset.role}`}>
                  <Icon name={asset.kind === "image" ? "image" : "file-text"} size={13} />
                </span>
                <div>
                  <strong title={asset.name}>{asset.name}</strong>
                  <small>{t(projectKey("role", asset.role), { defaultValue: asset.role })} · {formatBytes(asset.size)}</small>
                </div>
              </li>
            ))}
          </ul>
          {assets.length > keyAssets.length && (
            <small className="project-more-count">{t("projectUi.moreAssets", { count: assets.length - keyAssets.length })}</small>
          )}
        </section>
      )}
      {(assignments.length > 0 || activities.length > 0) && (
        <section className="project-detail-section project-work-summary">
          <header><strong>{t("projectUi.execution")}</strong></header>
          <div>
            <span>{t("projectUi.activeAssignments", { count: activeAssignments.length })}</span>
            <span>{t("projectUi.activeActivities", { count: activeActivities.length })}</span>
          </div>
        </section>
      )}
      <dl className="project-metadata">
        <dt>{t("projectUi.createdAt")}</dt><dd>{formatTime(project.createdAt)}</dd>
        <dt>{t("projectUi.updatedAt")}</dt><dd>{formatTime(project.updatedAt)}</dd>
        {project.completedAt && <><dt>{t("projectUi.completedAt")}</dt><dd>{formatTime(project.completedAt)}</dd></>}
      </dl>
      <footer>
        <span>{t("projectUi.assignments", { count: assignments.length })}</span>
        <span>{t("projectUi.activities", { count: activities.length })}</span>
        <span>{t("projectUi.assetSummary", { count: assets.length })}</span>
      </footer>
    </section>
  );
}

function formatTime(value: number): string {
  if (!value) return "—";
  return new Date(value * 1000).toLocaleString([], {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
