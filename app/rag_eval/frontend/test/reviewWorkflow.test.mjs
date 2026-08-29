import assert from "node:assert/strict";
import test from "node:test";
import {
  getReviewCounts,
  nextReviewState,
  summarizeEvaluationProgress,
} from "../src/reviewWorkflow.ts";

test("final reviewed decision enters the completion state without resetting the index", () => {
  assert.deepEqual(nextReviewState(2, 3, 3), { phase: "complete", index: 2 });
});

test("needs_revision is a reviewed decision and does not remain pending", () => {
  const counts = getReviewCounts(
    [{ sample_id: "q1" }, { sample_id: "q2" }],
    { q1: "needs_revision", q2: "approved" },
    new Set(["q1", "q2"]),
  );

  assert.deepEqual(counts, {
    approved: 1,
    rejected: 0,
    needsRevision: 1,
    pending: 0,
    reviewed: 2,
    total: 2,
  });
});

test("Ragas progress keeps preparation samples and judge repeats as separate rows", () => {
  const rows = summarizeEvaluationProgress([
    { type: "step_start", data: { step: "ragas_eval" } },
    { type: "step_progress", message: "ragas_eval prepare: 48/48", data: { step: "ragas_eval", phase: "prepare", current: 48, total: 48 } },
    { type: "step_progress", message: "ragas_eval judge: 1/1", data: { step: "ragas_eval", phase: "judge", current: 1, total: 1 } },
  ]);

  assert.deepEqual(rows.find((row) => row.step === "ragas_eval"), {
    step: "ragas_eval",
    status: "running",
    current: 1,
    total: 1,
    phase: "judge",
    substeps: [
      { phase: "prepare", current: 48, total: 48 },
      { phase: "judge", current: 1, total: 1 },
    ],
  });
});
