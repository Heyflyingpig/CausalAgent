// 文件总览：候选题审核流程的类型、计数和状态转换辅助函数。
// 页面组件只负责展示和提交，审核业务规则集中在本文件，便于前后端契约测试复用。

export type ReviewDecision = "approved" | "rejected" | "needs_revision";

export interface ReviewCounts {
  approved: number;
  rejected: number;
  needsRevision: number;
  pending: number;
  reviewed: number;
  total: number;
}

export interface ReviewSample {
  sample_id: string;
}

export function getReviewCounts(
  samples: ReviewSample[],
  decisions: Record<string, ReviewDecision | undefined>,
  reviewedIds: Set<string> | Record<string, boolean>,
): ReviewCounts {
  const isReviewed = (sampleId: string) => reviewedIds instanceof Set
    ? reviewedIds.has(sampleId)
    : reviewedIds[sampleId] === true;
  const counts: ReviewCounts = {
    approved: 0,
    rejected: 0,
    needsRevision: 0,
    pending: 0,
    reviewed: 0,
    total: samples.length,
  };

  samples.forEach((sample) => {
    if (!isReviewed(sample.sample_id)) {
      counts.pending += 1;
      return;
    }
    counts.reviewed += 1;
    const decision = decisions[sample.sample_id];
    if (decision === "approved") counts.approved += 1;
    else if (decision === "rejected") counts.rejected += 1;
    else counts.needsRevision += 1;
  });
  return counts;
}

export function nextReviewState(
  currentIndex: number,
  total: number,
  reviewedCount: number,
): { phase: "review" | "complete"; index: number } {
  if (total > 0 && reviewedCount >= total) return { phase: "complete", index: currentIndex };
  return {
    phase: "review",
    index: Math.min(Math.max(currentIndex + 1, 0), Math.max(total - 1, 0)),
  };
}

export type EvaluationProgressStatus = "pending" | "running" | "done" | "error";

export interface EvaluationProgressEvent {
  type: string;
  message?: string;
  data?: Record<string, unknown>;
}

export interface EvaluationSubstepProgress {
  phase: string;
  current?: number;
  total?: number;
}

export interface EvaluationProgressRow {
  step: string;
  status: EvaluationProgressStatus;
  current?: number;
  total?: number;
  phase?: string;
  substeps?: EvaluationSubstepProgress[];
}

const DEFAULT_STAGES = ["validate_datasets", "retrieval_eval", "ragas_eval", "trace_export", "summary"];

function finiteNumber(value: unknown): number | undefined {
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) ? number : undefined;
}

function eventStep(event: EvaluationProgressEvent, knownSteps: Set<string>): string | undefined {
  const explicit = String(event.data?.step || "").trim();
  if (explicit) return explicit;
  const message = String(event.message || "");
  return Array.from(knownSteps).find((step) => message.includes(step));
}

function eventProgress(event: EvaluationProgressEvent): { current?: number; total?: number } {
  const current = finiteNumber(event.data?.current);
  const total = finiteNumber(event.data?.total);
  if (current !== undefined || total !== undefined) return { current, total };
  const match = String(event.message || "").match(/(\d+)\s*\/\s*(\d+)/);
  return match ? { current: Number(match[1]), total: Number(match[2]) } : {};
}

export function summarizeEvaluationProgress(
  events: EvaluationProgressEvent[],
  stageNames: string[] = DEFAULT_STAGES,
): EvaluationProgressRow[] {
  const rows = new Map<string, EvaluationProgressRow>(
    stageNames.map((step) => [step, { step, status: "pending" }]),
  );
  const knownSteps = new Set(stageNames);

  events.forEach((event) => {
    const step = eventStep(event, knownSteps);
    if (!step) return;
    if (!rows.has(step)) rows.set(step, { step, status: "pending" });
    const row = rows.get(step)!;
    if (event.type === "step_start") row.status = "running";
    if (event.type === "step_done") row.status = "done";
    if (event.type === "step_error") row.status = "error";
    if (event.type === "step_progress") {
      row.status = "running";
      const progress = eventProgress(event);
      row.current = progress.current;
      row.total = progress.total;
      row.phase = String(event.data?.phase || "").trim() || undefined;
      if (row.phase) {
        const substeps = row.substeps || [];
        const previous = substeps.find((substep) => substep.phase === row.phase);
        if (previous) Object.assign(previous, progress);
        else substeps.push({ phase: row.phase, ...progress });
        row.substeps = substeps;
      }
    }
  });
  return Array.from(rows.values());
}
