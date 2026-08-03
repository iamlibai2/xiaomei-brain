import type { ProjectDetailSnapshot } from "../../store";
import { Icon } from "../ui";

const stepStatus: Record<string, string> = {
  pending: "待开始",
  running: "进行中",
  waiting_review: "待审阅",
  completed: "已完成",
  needs_revision: "需修改",
  skipped: "已跳过",
};

const projectStatus: Record<string, string> = {
  active: "进行中",
  completed: "已完成",
  discontinued: "已终止",
};

const assetRole: Record<string, string> = {
  source: "素材",
  working: "工作文件",
  cache: "缓存",
  review: "审阅件",
  deliverable: "交付物",
};

const processStatus: Record<string, string> = {
  active: "待满足",
  satisfied: "已满足",
  abandoned: "已取消",
};

const processStageStatus: Record<string, string> = {
  pending: "待提交",
  incomplete: "材料不完整",
  satisfied: "已满足",
};

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
  if (loading && !detail) {
    return <section className="current-project-card loading">正在读取当前项目…</section>;
  }
  if (error && !detail) {
    return (
      <section className="current-project-card error">
        <span>{error}</span>
        <button type="button" onClick={onRefresh}>重试</button>
      </section>
    );
  }
  if (!detail) {
    return (
      <section className="project-sidebar-panel empty">
        <span className="project-sidebar-empty-icon"><Icon name="folder" size={20} /></span>
        <strong>当前会话还没有项目</strong>
        <p>直接在对话中告诉 Agent 要开展的长期工作，Agent 会创建项目并持续记录阶段、委托和资产。</p>
        <button type="button" onClick={onRefresh}>刷新</button>
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
          <small>当前项目</small>
          <strong>{project.name}</strong>
        </div>
        <span className={`project-status-badge ${project.status}`}>
          {projectStatus[project.status] || project.status}
        </span>
        <button type="button" onClick={onRefresh} title="刷新项目">
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
            aria-label="项目进度"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
          >
            <span style={{ width: `${percent}%` }} />
          </div>
          <small>
            {progressFinished}/{progressTotal} {usesProcessProgress ? "正式提交" : "已收束"} · {percent}%
          </small>
        </div>
      )}
      {project.waitingReason && <p className="current-project-waiting">{project.waitingReason}</p>}
      {process && (
        <section className="project-detail-section project-process-summary">
          <header>
            <strong>交付标准</strong>
            <small className={process.status}>{processStatus[process.status] || process.status}</small>
          </header>
          <div className="project-process-heading">
            <strong>{process.name}</strong>
            <small>{process.ordered ? "按顺序提交" : "提交顺序自由"}</small>
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
                      <small>{processStageStatus[stage.status] || stage.status}</small>
                    </div>
                    {stage.requirementLabels.length > 0 && (
                      <p>要求：{stage.requirementLabels.join("、")}</p>
                    )}
                    {stage.missing.length > 0 && (
                      <p className="missing">缺少：{stage.missing.join("、")}</p>
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
            <strong>最近复盘</strong>
            <small>{formatTime(latestReview.createdAt)}</small>
          </header>
          <p>{latestReview.assessment}</p>
          {latestReview.deviations.length > 0 && (
            <div>
              <strong>与原计划的差异</strong>
              <ul>{latestReview.deviations.map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
          )}
          {latestReview.planChanges.length > 0 && (
            <div>
              <strong>计划调整</strong>
              <ul>{latestReview.planChanges.map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
          )}
          {latestReview.nextAction && (
            <p className="project-review-next"><strong>下一步</strong>{latestReview.nextAction}</p>
          )}
        </section>
      )}
      {orderedSteps.length > 0 && (
        <section className="project-detail-section">
          <header>
            <strong>项目阶段</strong>
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
                      <small>{stepStatus[step.status] || step.status}</small>
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
            <strong>项目资产</strong>
            <small>{assets.length} 份</small>
          </header>
          <ul className="project-asset-list">
            {keyAssets.map((asset) => (
              <li key={asset.id}>
                <span className={`project-asset-icon ${asset.role}`}>
                  <Icon name={asset.kind === "image" ? "image" : "file-text"} size={13} />
                </span>
                <div>
                  <strong title={asset.name}>{asset.name}</strong>
                  <small>{assetRole[asset.role] || asset.role} · {formatBytes(asset.size)}</small>
                </div>
              </li>
            ))}
          </ul>
          {assets.length > keyAssets.length && (
            <small className="project-more-count">另有 {assets.length - keyAssets.length} 份项目资产</small>
          )}
        </section>
      )}
      {(assignments.length > 0 || activities.length > 0) && (
        <section className="project-detail-section project-work-summary">
          <header><strong>执行现场</strong></header>
          <div>
            <span><b>{activeAssignments.length}</b> 项进行中的委托</span>
            <span><b>{activeActivities.length}</b> 条正在运行的活动</span>
          </div>
        </section>
      )}
      <dl className="project-metadata">
        <dt>创建时间</dt><dd>{formatTime(project.createdAt)}</dd>
        <dt>最近更新</dt><dd>{formatTime(project.updatedAt)}</dd>
        {project.completedAt && <><dt>完成时间</dt><dd>{formatTime(project.completedAt)}</dd></>}
      </dl>
      <footer>
        <span>{assignments.length} 项委托</span>
        <span>{activities.length} 条活动</span>
        <span>{assets.length} 份资产</span>
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
