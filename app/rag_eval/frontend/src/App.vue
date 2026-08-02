<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  BarChart3,
  Check,
  ChevronDown,
  CircleDot,
  Database,
  FileChartColumn,
  FileText,
  Gauge,
  GitCompare,
  LayoutDashboard,
  LoaderCircle,
  Minus,
  PanelLeftClose,
  PanelLeftOpen,
  Play,
  RefreshCw,
  SlidersHorizontal,
  Trash2,
  TrendingUp,
  Upload,
} from "lucide-vue-next";

type RunStatus = "created" | "queued" | "running" | "cancelling" | "staged" | "succeeded" | "cancelled" | "failed";
type NavId = "workspace" | "evaluation" | "reports";
type EvaluationSection = "config" | "events" | "comparison";
type ComparisonMode = "time_trend" | "run_diff" | "strategy_diff";
type ReportTab = "pipeline" | "retrieval" | "ragas";

interface SourceEntry {
  source_id: string;
  name: string;
  size_bytes: number;
  content_sha256: string;
  source_kind?: "frozen" | "uploaded";
  page_count?: number | null;
}

interface PageRangeDraft { start: string; end: string; }

interface RunEvent {
  type: string;
  message?: string;
  timestamp?: string;
  data?: Record<string, unknown>;
}

interface RunState {
  run_id: string;
  kind: string;
  status: RunStatus;
  source_ids?: string[];
  source_names?: string[];
  max_pages?: number | null;
  page_ranges?: Array<{ source_id: string; start_page: number; end_page: number }>;
  current_stage?: string;
  index_version?: string;
  manifest_sha256?: string;
  unit_count?: number;
  vector_count?: number;
  question_count?: number;
  ingestion_run_id?: string;
  error?: string;
  result_available?: boolean;
  events?: RunEvent[];
}

interface IngestionHistory {
  items: RunState[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

interface EvaluationResult {
  summary: {
    status: string;
    status_reason?: string;
    key_metrics: Record<string, number | string | null>;
    steps: Array<{ name?: string; step?: string; status: string; error?: string; message?: string }>;
  };
  artifacts?: Record<string, string>;
}

interface EvaluationHistoryItem {
  run_id: string;
  status: string;
  status_reason?: string;
  created_at?: string;
  started_at?: string;
  finished_at?: string;
  stale?: boolean;
  ingestion_run_id?: string;
  index_version?: string;
  source_ids?: string[];
  source_names?: string[];
  source_label?: string;
  question_count?: number;
  dataset_identity?: Record<string, unknown>;
  config_identity?: string;
  strategy?: Record<string, unknown>;
  key_metrics: Record<string, number | string | null>;
}

interface EvaluationDiff {
  available: boolean;
  base: EvaluationHistoryItem;
  candidate: EvaluationHistoryItem;
  metric_deltas: Array<{ metric: string; base: number | string | null; candidate: number | string | null; delta: number | null }>;
  config_deltas: Array<{ field: string; base: unknown; candidate: unknown }>;
  sample_deltas: Array<{ sample_id: string; question: string; classification: string; metrics: Array<{ metric: string; base: number | string | null; candidate: number | string | null; delta: number | null }>; base_bad_case: boolean; candidate_bad_case: boolean }>;
  summary: Record<string, number>;
}

interface ParameterMeta {
  label: string;
  meaning: string;
  allowed?: [number, number];
  recommended?: [number, number];
  integer?: boolean;
  allow_null?: boolean;
}

interface RagEvalConfig {
  active_retrieval_profile: string;
  retrieval_profiles: Record<string, Record<string, unknown>>;
  retrieval_current: Record<string, unknown>;
  retrieval_profile_limits: Record<string, number | null>;
  retrieval_eval: Record<string, unknown>;
  ragas: {
    active_profile: string;
    available_profiles: string[];
    profiles: Record<string, Record<string, unknown>>;
    selected_metrics: string[];
    [key: string]: unknown;
  };
  parameter_meta: Record<string, ParameterMeta>;
}

interface StrategyProfile {
  profile_id: string;
  name: string;
  kind: "builtin" | "custom";
  editable: boolean;
  retrieval_profile: string;
  ragas_profile: string;
  retrieval: Record<string, unknown>;
  ragas: Record<string, unknown>;
  version?: number;
}

interface StrategyProfileCatalog {
  default_profile_id: string;
  published_profile_id: string;
  profiles: StrategyProfile[];
}

interface ProductionConfig {
  exists: boolean;
  retrieval_config?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  path?: string;
}

const sources = ref<SourceEntry[]>([]);
const selectedSourceIds = ref<string[]>([]);
const ingestion = ref<RunState | null>(null);
const evaluationRun = ref<RunState | null>(null);
const evaluationResult = ref<EvaluationResult | null>(null);
const events = ref<RunEvent[]>([]);
const datasetText = ref("");
const pageLimit = ref<"4" | "12" | "all" | "custom">("4");
const pageRanges = ref<Record<string, PageRangeDraft>>({});
const activeNav = ref<NavId>("workspace");
const evaluationSection = ref<EvaluationSection>("config");
const comparisonMode = ref<ComparisonMode>("time_trend");
const reportTab = ref<ReportTab>("pipeline");
const historyRange = ref("30d");
const historySource = ref("");
const comparisonGranularity = ref("day");
const diffBaseRunId = ref("");
const diffCandidateRunId = ref("");
const diffResult = ref<EvaluationDiff | null>(null);
const sampleFilter = ref("all");
const sampleSort = ref("default");
const historyRuns = ref<EvaluationHistoryItem[]>([]);
const historyLoading = ref(false);
const diffLoading = ref(false);
const comparisonError = ref("");
const reportRunId = ref("");
const reportMarkdown = ref("");
const reportLoading = ref(false);
const reportError = ref("");
const reportNotice = ref("");
const reportDeleteLoading = ref(false);
const configData = ref<RagEvalConfig | null>(null);
const strategyProfiles = ref<StrategyProfile[]>([]);
const strategyProfileId = ref("active_current");
const publishedProfileId = ref("active_current");
const profileNameDraft = ref("");
const strategyProfileStorageKey = "rag_eval_strategy_profile_id";
const productionConfig = ref<ProductionConfig | null>(null);
const retrievalProfile = ref("active_current");
const ragasProfile = ref("generic_pipeline");
const retrievalDraft = ref<Record<string, unknown>>({});
const ragasDraft = ref<Record<string, unknown>>({});
const executeRagas = ref(true);
const configLoading = ref(false);
const configSaving = ref(false);
const configMessage = ref("");
const configError = ref("");
const sidebarCollapsed = ref(false);
const sourceLoading = ref(false);
const uploadInput = ref<HTMLInputElement | null>(null);
const uploadLoading = ref(false);
const sourceDeleteLoading = ref<string | null>(null);
const ingestionLoading = ref(false);
const evaluationLoading = ref(false);
const catalogError = ref("");
const sourceNotice = ref("");
const actionError = ref("");
const evaluationToast = ref("");
const evaluationAwaitingCompletion = ref<string | null>(null);
let eventSource: EventSource | null = null;
let pollTimer: number | null = null;
let evaluationToastTimer: number | null = null;

const retrievalFieldKeys = [
  "dense_fetch_k", "dense_mmr_k", "sparse_fetch_k", "final_top_k",
  "dense_score_threshold", "final_rerank_threshold", "mmr_lambda",
];
const ragasFieldKeys = [
  "limit", "max_contexts", "max_context_chars", "max_response_chars",
  "ragas_timeout", "ragas_max_workers", "ragas_max_retries", "ragas_max_wait",
  "repeat_count", "low_score_threshold", "retrieval_recall_low_threshold", "retrieval_mrr_low_threshold",
];
const evaluationRagasKeys = [
  "limit", "selected_metrics", "include_reference_metrics", "max_contexts", "max_context_chars",
  "max_response_chars", "ragas_timeout", "ragas_max_workers", "ragas_max_retries", "ragas_max_wait",
  "answer_relevancy_strictness", "judge_profile", "repeat_count", "low_score_threshold",
  "retrieval_recall_low_threshold", "retrieval_mrr_low_threshold",
];
const metricOptions = ["faithfulness", "answer_relevancy", "context_utilization", "context_recall"];
const terminalStatuses: RunStatus[] = ["staged", "succeeded", "cancelled", "failed"];
const supportedUploadExtensions = [
  ".pdf", ".txt", ".md", ".markdown", ".csv", ".xlsx",
  ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff",
];
const supportedUploadLabel = supportedUploadExtensions.join(", ");
const selectedSources = computed(() => sources.value.filter((item) => selectedSourceIds.value.includes(item.source_id)));
const ingestionReady = computed(() => ingestion.value?.status === "staged" && Boolean(ingestion.value.index_version));
const busy = computed(() => uploadLoading.value || sourceDeleteLoading.value !== null || ingestionLoading.value || evaluationLoading.value);
const evaluationMetrics = computed(() => Object.entries(evaluationResult.value?.summary.key_metrics || {}));
const displayEvents = computed(() => {
  const visible: RunEvent[] = [];
  const progressIndexes = new Map<string, number>();
  events.value.forEach((event) => {
    const progressMatch = event.type === "step_progress"
      ? String(event.message || "").match(/^(.+?):\s*\d+\/\d+/)
      : null;
    const progressKey = progressMatch?.[1]?.trim();
    if (progressKey) {
      const previousIndex = progressIndexes.get(progressKey);
      if (previousIndex !== undefined) {
        visible[previousIndex] = event;
        return;
      }
      progressIndexes.set(progressKey, visible.length);
    }
    visible.push(event);
  });
  return visible;
});
const evaluationActive = computed(() => Boolean(evaluationRun.value && ["created", "queued", "running", "cancelling"].includes(evaluationRun.value.status)));
const ragasInProgress = computed(() => evaluationActive.value && (
  String(evaluationRun.value?.current_stage || "").toLowerCase().includes("ragas")
  || events.value.some((event) => /ragas/i.test(String(event.message || "")))
));
const evaluationWaitingMessage = computed(() => ragasInProgress.value
  ? "当前正在调用 Ragas judge 大模型，请耐心等待；样本越多，评测耗时越长。"
  : "当前流程包含回答生成或模型评审，请耐心等待；页面会持续更新执行进度。"
);
const historyMetricKeys = computed(() => Array.from(new Set(historyRuns.value.flatMap((run) => Object.keys(run.key_metrics || {})))).slice(0, 6));
const sourceFilterOptions = computed(() => Array.from(new Set(historyRuns.value.flatMap((run) => run.source_names || []))).sort());
const selectedReportRun = computed(() => historyRuns.value.find((run) => run.run_id === reportRunId.value) || null);
const reportDeleteCanProceed = computed(() => {
  const run = selectedReportRun.value;
  if (!run) return false;
  return !["created", "queued", "running", "cancelling"].includes(run.status) || run.stale === true;
});
const currentReportRunLabel = computed(() => selectedReportRun.value ? historyLabel(selectedReportRun.value) : reportRunId.value || "未选择评测运行");
const trendRows = computed(() => {
  const completed = historyRuns.value.filter((run) => run.status === "pass" || run.status === "succeeded");
  if (comparisonGranularity.value === "run") return completed.map((run) => ({
    label: formatBeijingDateTime(run.finished_at || run.created_at) || run.run_id,
    count: 1,
    metrics: run.key_metrics,
  }));
  const groups = new Map<string, EvaluationHistoryItem[]>();
  completed.forEach((run) => {
    const day = formatBeijingDate(run.finished_at || run.created_at) || "unknown";
    groups.set(day, [...(groups.get(day) || []), run]);
  });
  return Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b)).map(([label, runs]) => {
    const metrics: Record<string, number | null> = {};
    historyMetricKeys.value.forEach((key) => {
      const values = runs.map((run) => run.key_metrics?.[key]).filter((value): value is number => typeof value === "number" && Number.isFinite(value));
      metrics[key] = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
    });
    return { label, count: runs.length, metrics };
  });
});
const customPageTotal = computed(() => selectedSources.value.reduce((total, source) => {
  const range = pageRanges.value[source.source_id];
  const start = Number(range?.start);
  const end = Number(range?.end);
  return total + (Number.isInteger(start) && Number.isInteger(end) && end >= start ? end - start + 1 : 0);
}, 0));

function formatBytes(value = 0): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function parseTimestamp(value?: string): Date | null {
  if (!value) return null;
  const hasTimezone = value.endsWith("Z") || value.length > 10 && /[+-][0-9]{2}:?[0-9]{2}$/.test(value);
  const timestamp = new Date(hasTimezone ? value : value + "Z");
  return Number.isNaN(timestamp.getTime()) ? null : timestamp;
}

function formatBeijingParts(value?: string): Record<string, string> | null {
  const timestamp = parseTimestamp(value);
  if (!timestamp) return null;
  return Object.fromEntries(new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  }).formatToParts(timestamp).map(({ type, value: part }) => [type, part]));
}

function formatBeijingTime(value?: string): string {
  const parts = formatBeijingParts(value);
  return parts ? `${parts.hour}:${parts.minute}:${parts.second}` : "--:--:--";
}

function formatBeijingDate(value?: string): string {
  const parts = formatBeijingParts(value);
  return parts ? `${parts.year}-${parts.month}-${parts.day}` : "";
}

function formatBeijingDateTime(value?: string): string {
  const date = formatBeijingDate(value);
  return date ? `${date} ${formatBeijingTime(value)}` : "";
}

function statusLabel(status?: string): string {
  return ({ created: "已创建", queued: "排队中", running: "运行中", cancelling: "取消中", staged: "已就绪", succeeded: "已完成", cancelled: "已取消", failed: "失败", pass: "通过", needs_review: "待复核" } as Record<string, string>)[status || ""] || "未开始";
}

function statusTone(status?: string): string {
  if (status === "failed" || status === "fail") return "danger";
  if (status === "staged" || status === "succeeded" || status === "pass") return "success";
  if (status === "cancelled") return "muted";
  return "active";
}

async function api<T>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(url, { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.success === false) throw new Error(payload.error || `请求失败 (${response.status})`);
  return payload.data as T;
}

function openUploadDialog() { uploadInput.value?.click(); }

async function uploadSource(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  actionError.value = "";
  sourceNotice.value = "";
  const extension = file.name.toLowerCase().slice(file.name.lastIndexOf("."));
  if (!supportedUploadExtensions.includes(extension)) {
    actionError.value = `不支持该文件格式，可上传：${supportedUploadLabel}`;
    return;
  }
  uploadLoading.value = true;
  try {
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch("/api/rag_eval/isolated/sources", { method: "POST", body: formData });
    const payload = await response.json().catch(() => ({})) as { success?: boolean; error?: string; data?: { source?: SourceEntry } };
    if (!response.ok || payload.success === false) throw new Error(payload.error || `上传失败 (${response.status})`);
    await loadCatalog();
    sourceNotice.value = `已登记 ${payload.data?.source?.name || file.name}，请选择来源后启动摄取`;
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : "知识源上传失败";
  } finally { uploadLoading.value = false; }
}

async function deleteSource(source: SourceEntry) {
  if (source.source_kind !== "uploaded") return;
  if (!window.confirm(`确认删除“${source.name}”？这只会删除上传文件，不会删除已生成的 staged index 或评测报告。`)) return;
  actionError.value = "";
  sourceNotice.value = "";
  sourceDeleteLoading.value = source.source_id;
  try {
    await api(`/api/rag_eval/isolated/sources/${encodeURIComponent(source.source_id)}`, { method: "DELETE" });
    selectedSourceIds.value = selectedSourceIds.value.filter((value) => value !== source.source_id);
    const nextRanges = { ...pageRanges.value };
    delete nextRanges[source.source_id];
    pageRanges.value = nextRanges;
    await loadCatalog();
    sourceNotice.value = `已删除 ${source.name}`;
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : "知识源删除失败";
  } finally { sourceDeleteLoading.value = null; }
}

async function loadCatalog() {
  sourceLoading.value = true;
  catalogError.value = "";
  try {
    const data = await api<{ sources: SourceEntry[] }>("/api/rag_eval/isolated/source-catalog");
    sources.value = data.sources;
    const nextRanges = { ...pageRanges.value };
    data.sources.forEach((source) => { nextRanges[source.source_id] ||= { start: "1", end: String(Math.min(source.page_count || 12, 12)) }; });
    pageRanges.value = nextRanges;
    const availableIds = new Set(data.sources.map((item) => item.source_id));
    selectedSourceIds.value = selectedSourceIds.value.filter((value) => availableIds.has(value));
    if (!selectedSourceIds.value.length) selectedSourceIds.value = data.sources.map((item) => item.source_id);
  } catch (error) {
    catalogError.value = error instanceof Error ? error.message : "来源目录加载失败";
  } finally { sourceLoading.value = false; }
}

function appendEvent(event: RunEvent) {
  if (event.type === "heartbeat" || event.type === "connected") return;
  events.value = [...events.value, event].slice(-100);
}

function notifyEvaluationFinished(state: RunState) {
  if (!evaluationAwaitingCompletion.value || evaluationAwaitingCompletion.value !== state.run_id) return;
  if (!(["succeeded", "failed", "cancelled"] as RunStatus[]).includes(state.status)) return;
  evaluationAwaitingCompletion.value = null;
  evaluationToast.value = state.status === "succeeded"
    ? "Ragas 评测已完成，可以查看本次报告。"
    : state.status === "cancelled"
      ? "评测已取消。"
      : "评测失败，请查看流程事件和后台日志。";
  if (evaluationToastTimer !== null) window.clearTimeout(evaluationToastTimer);
  evaluationToastTimer = window.setTimeout(() => {
    evaluationToast.value = "";
    evaluationToastTimer = null;
  }, 7000);
}

function dismissEvaluationToast() {
  evaluationToast.value = "";
  if (evaluationToastTimer !== null) window.clearTimeout(evaluationToastTimer);
  evaluationToastTimer = null;
}

function stopWatching() {
  eventSource?.close();
  eventSource = null;
  if (pollTimer !== null) window.clearInterval(pollTimer);
  pollTimer = null;
}

type RunKind = "ingestion" | "evaluation";

async function refreshRun(kind: RunKind, runId: string) {
  const url = kind === "ingestion"
    ? `/api/rag_eval/isolated/ingestion-runs/${encodeURIComponent(runId)}`
    : `/api/rag_eval/isolated/evaluation-runs/${encodeURIComponent(runId)}`;
  const state = await api<RunState>(url);
  if (kind === "ingestion") ingestion.value = state;
  else evaluationRun.value = state;
  if (kind === "evaluation") notifyEvaluationFinished(state);
  if (terminalStatuses.includes(state.status)) {
    if (kind === "ingestion") ingestionLoading.value = false;
    else evaluationLoading.value = false;
    if (kind === "evaluation" && state.status === "succeeded" && state.result_available) await loadEvaluationResult(runId);
    stopWatching();
  }
  return state;
}

async function loadEvaluationResult(runId: string) {
  try {
    evaluationResult.value = await api<EvaluationResult>(`/api/rag_eval/isolated/evaluation-runs/${encodeURIComponent(runId)}/result`);
    await loadEvaluationHistory();
  } catch (error) { actionError.value = error instanceof Error ? error.message : "评测结果加载失败"; }
}

function watchRun(kind: RunKind, runId: string) {
  stopWatching();
  const stream = kind === "ingestion"
    ? `/api/rag_eval/isolated/ingestion-runs/${encodeURIComponent(runId)}/stream`
    : `/api/rag_eval/isolated/evaluation-runs/${encodeURIComponent(runId)}/stream`;
  eventSource = new EventSource(stream);
  eventSource.onmessage = async (message) => {
    const event = JSON.parse(message.data) as RunEvent;
    appendEvent(event);
    if (["run_done", "run_error", "run_cancelled"].includes(event.type)) await refreshRun(kind, runId);
  };
  eventSource.onerror = async () => {
    eventSource?.close(); eventSource = null;
    try {
      await refreshRun(kind, runId);
      const current = kind === "ingestion" ? ingestion.value : evaluationRun.value;
      if (current && !terminalStatuses.includes(current.status)) pollTimer = window.setInterval(() => refreshRun(kind, runId).catch(() => undefined), 5000);
    } catch (error) { actionError.value = error instanceof Error ? error.message : "运行状态读取失败"; }
  };
}

async function startIngestion() {
  actionError.value = "";
  if (!selectedSourceIds.value.length) { actionError.value = "请选择至少一个知识源"; return; }
  ingestionLoading.value = true;
  events.value = [];
  try {
    let customRanges: Array<{ source_id: string; start_page: number; end_page: number }> | null = null;
    if (pageLimit.value === "custom") {
      customRanges = selectedSources.value.map((source) => {
        const draft = pageRanges.value[source.source_id];
        const start = Number(draft?.start); const end = Number(draft?.end);
        if (!Number.isInteger(start) || !Number.isInteger(end) || start < 1 || end < start) throw new Error(`请填写 ${source.name} 的有效页码范围`);
        return { source_id: source.source_id, start_page: start, end_page: end };
      });
    }
    const state = await api<RunState>("/api/rag_eval/isolated/ingestion-runs", {
      method: "POST",
      body: JSON.stringify({ source_ids: selectedSourceIds.value, max_pages: pageLimit.value === "4" || pageLimit.value === "12" ? Number(pageLimit.value) : null, page_ranges: customRanges }),
    });
    ingestion.value = state;
    localStorage.setItem("ingestion_run_id", state.run_id);
    watchRun("ingestion", state.run_id);
  } catch (error) {
    ingestionLoading.value = false;
    actionError.value = error instanceof Error ? error.message : "摄取任务启动失败";
  }
}

async function cancelIngestion() {
  if (!ingestion.value) return;
  try { ingestion.value = await api<RunState>(`/api/rag_eval/isolated/ingestion-runs/${encodeURIComponent(ingestion.value.run_id)}/cancel`, { method: "POST", body: "{}" }); }
  catch (error) { actionError.value = error instanceof Error ? error.message : "取消失败"; }
}

function comparisonSince(): string | undefined {
  if (historyRange.value === "all") return undefined;
  const days = historyRange.value === "90d" ? 90 : historyRange.value === "30d" ? 30 : 7;
  return new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
}

async function loadEvaluationHistory() {
  historyLoading.value = true;
  comparisonError.value = "";
  try {
    const query: Record<string, string> = { page: "1", page_size: "100" };
    const since = comparisonSince();
    if (since) query.since = since;
    if (historySource.value) query.source_name = historySource.value;
    const params = new URLSearchParams(query);
    const data = await api<{ items: EvaluationHistoryItem[] }>(`/api/rag_eval/isolated/evaluation-history?${params.toString()}`);
    historyRuns.value = data.items || [];
    const ids = historyRuns.value.map((run) => run.run_id);
    if (!ids.includes(reportRunId.value)) reportRunId.value = evaluationRun.value?.run_id && ids.includes(evaluationRun.value.run_id) ? evaluationRun.value.run_id : ids[0] || "";
    if (!ids.includes(diffCandidateRunId.value)) diffCandidateRunId.value = ids[0] || "";
    if (!ids.includes(diffBaseRunId.value) || diffBaseRunId.value === diffCandidateRunId.value) diffBaseRunId.value = ids.find((id) => id !== diffCandidateRunId.value) || "";
    if (activeNav.value === "reports" && reportRunId.value) await loadReportArtifact();
    if (!reportRunId.value) reportMarkdown.value = "";
  } catch (error) {
    comparisonError.value = error instanceof Error ? error.message : "评测历史加载失败";
  } finally { historyLoading.value = false; }
}

async function loadEvaluationDiff() {
  if (!diffBaseRunId.value || !diffCandidateRunId.value || diffBaseRunId.value === diffCandidateRunId.value) { diffResult.value = null; return; }
  diffLoading.value = true;
  comparisonError.value = "";
  try {
    const params = new URLSearchParams({ base_run_id: diffBaseRunId.value, candidate_run_id: diffCandidateRunId.value });
    diffResult.value = await api<EvaluationDiff>(`/api/rag_eval/isolated/evaluation-diff?${params.toString()}`);
  } catch (error) {
    diffResult.value = null;
    comparisonError.value = error instanceof Error ? error.message : "评测 diff 加载失败";
  } finally { diffLoading.value = false; }
}

async function refreshComparison() { await loadEvaluationHistory(); if (comparisonMode.value !== "time_trend") await loadEvaluationDiff(); }

function reportArtifactPath(): string {
  return reportTab.value === "pipeline" ? "summary.md" : reportTab.value === "retrieval" ? "reports/rag_eval_report.md" : "reports/ragas_eval_report.md";
}

async function loadReportArtifact() {
  if (!reportRunId.value) { reportMarkdown.value = ""; return; }
  reportLoading.value = true;
  reportError.value = "";
  const url = `/api/rag_eval/isolated/evaluation-runs/${encodeURIComponent(reportRunId.value)}/artifacts/${reportArtifactPath().split("/").map(encodeURIComponent).join("/")}`;
  try {
    const response = await fetch(url);
    const text = await response.text();
    if (!response.ok) {
      let message = text;
      try { message = JSON.parse(text).error || message; } catch { /* response may be plain text */ }
      throw new Error(message || `报告读取失败 (${response.status})`);
    }
    reportMarkdown.value = text;
  } catch (error) {
    reportMarkdown.value = "";
    reportError.value = error instanceof Error ? error.message : "报告读取失败";
  } finally { reportLoading.value = false; }
}

async function deleteReport() {
  const runId = reportRunId.value;
  const run = selectedReportRun.value;
  if (!runId || !run) return;
  const warning = run.stale
    ? "该任务长时间没有新的执行事件，将强制移除其运行目录。"
    : "删除后历史记录、报告和对比数据都不可见。";
  if (!reportDeleteCanProceed.value || !window.confirm(`确定删除这次评测报告吗？\n\n${historyLabel(run)}\n\n${warning}`)) return;
  reportDeleteLoading.value = true;
  reportError.value = "";
  reportNotice.value = "";
  try {
    await api(`/api/rag_eval/isolated/evaluation-runs/${encodeURIComponent(runId)}`, {
      method: "DELETE",
      body: JSON.stringify({ force: run.stale === true }),
    });
    if (evaluationRun.value?.run_id === runId) {
      stopWatching();
      evaluationRun.value = null;
      evaluationResult.value = null;
      evaluationAwaitingCompletion.value = null;
      localStorage.removeItem("evaluation_run_id");
    }
    reportRunId.value = "";
    reportMarkdown.value = "";
    diffResult.value = null;
    diffBaseRunId.value = "";
    diffCandidateRunId.value = "";
    await loadEvaluationHistory();
    reportNotice.value = "报告已删除，历史记录和对比数据已同步移除。";
  } catch (error) {
    reportError.value = error instanceof Error ? error.message : "报告删除失败";
  } finally { reportDeleteLoading.value = false; }
}

function openReport(runId: string, tab: ReportTab = "pipeline") {
  activeNav.value = "reports";
  reportRunId.value = runId;
  reportTab.value = tab;
  void loadEvaluationHistory().then(() => loadReportArtifact());
}

function selectReportTab(tab: ReportTab) { reportTab.value = tab; void loadReportArtifact(); }

function escapeHtml(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

function renderInlineMarkdown(value: string): string {
  let rendered = escapeHtml(value);
  rendered = rendered.replace(/`([^`]+)`/g, "<code>$1</code>");
  rendered = rendered.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  rendered = rendered.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  rendered = rendered.replace(/__([^_]+)__/g, "<strong>$1</strong>");
  rendered = rendered.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  return rendered;
}

function splitMarkdownTableRow(line: string): string[] { return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim()); }

function renderMarkdown(markdown: string): string {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const html: string[] = [];
  let paragraph: string[] = [];
  let listType = "";
  let inCode = false;
  let codeLines: string[] = [];
  const flushParagraph = () => { if (paragraph.length) { html.push(`<p>${renderInlineMarkdown(paragraph.join(" "))}</p>`); paragraph = []; } };
  const closeList = () => { if (listType) { html.push(`</${listType}>`); listType = ""; } };
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (line.trim().startsWith("```")) {
      flushParagraph(); closeList();
      if (inCode) { html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`); codeLines = []; }
      inCode = !inCode; continue;
    }
    if (inCode) { codeLines.push(line); continue; }
    if (/^\|.*\|$/.test(line) && /^\|?\s*:?-{3,}/.test(lines[index + 1] || "")) {
      flushParagraph(); closeList();
      const headers = splitMarkdownTableRow(line); index += 2;
      const rows: string[][] = [];
      while (index < lines.length && /^\|.*\|$/.test(lines[index])) { rows.push(splitMarkdownTableRow(lines[index])); index += 1; }
      index -= 1;
      html.push(`<table><thead><tr>${headers.map((cell) => `<th>${renderInlineMarkdown(cell)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${headers.map((_, i) => `<td>${renderInlineMarkdown(row[i] || "")}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
      continue;
    }
    const heading = /^(#{1,4})\s+(.+)$/.exec(line);
    if (heading) { flushParagraph(); closeList(); html.push(`<h${heading[1].length}>${renderInlineMarkdown(heading[2])}</h${heading[1].length}>`); continue; }
    if (/^\s*([-*_])\s*\1\s*\1/.test(line)) { flushParagraph(); closeList(); html.push("<hr>"); continue; }
    const bullet = /^\s*[-*+]\s+(.+)$/.exec(line);
    const ordered = /^\s*\d+[.)]\s+(.+)$/.exec(line);
    if (bullet || ordered) {
      flushParagraph(); const nextList = bullet ? "ul" : "ol";
      if (listType !== nextList) { closeList(); html.push(`<${nextList}>`); listType = nextList; }
      html.push(`<li>${renderInlineMarkdown((bullet || ordered)![1])}</li>`); continue;
    }
    if (/^>\s?/.test(line)) { flushParagraph(); closeList(); html.push(`<blockquote>${renderInlineMarkdown(line.replace(/^>\s?/, ""))}</blockquote>`); continue; }
    if (!line.trim()) { flushParagraph(); closeList(); continue; }
    paragraph.push(line.trim());
  }
  if (inCode) html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
  flushParagraph(); closeList();
  return html.join("");
}

function runProfileName(run: EvaluationHistoryItem): string {
  return String(run.strategy?.profile_name || run.strategy?.profile_id || "未记录 profile");
}
function runDatasetSubtitle(run: EvaluationHistoryItem): string {
  return `${String(run.dataset_identity?.dataset_id || "dataset")} · ${formatBeijingDateTime(run.created_at) || run.run_id}`;
}
function historyLabel(run: EvaluationHistoryItem): string { return `${runProfileName(run)} · ${runDatasetSubtitle(run)}`; }
function formatMetric(value: unknown): string { return typeof value === "number" ? value.toFixed(4) : value === null || value === undefined || value === "" ? "未评分" : String(value); }
function formatConfigValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "未设置";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
function configFieldLabel(field: string): string {
  const labels: Record<string, string> = {
    strategy_profile: "策略配置",
    retrieval: "检索",
    ragas: "Ragas",
    profile: "配置档案",
    overrides: "覆盖参数",
    selected_metrics: "评测指标",
    judge_profile: "评审档案",
    steps: "执行步骤",
  };
  return field.split(".").map((part) => labels[part] || part.replaceAll("_", " ")).join(" / ");
}
function metricLabel(value: string): string { return ({ retrieval_recall_at_k: "检索 Recall@K", retrieval_mrr: "检索 MRR", retrieval_hit_rate: "检索命中率", ragas_faithfulness: "Ragas 忠实性", ragas_answer_relevancy: "回答相关性", ragas_context_utilization: "上下文利用率", ragas_context_recall: "上下文召回率", faithfulness: "忠实度", answer_relevancy: "回答相关性", context_utilization: "上下文利用率", context_recall: "上下文召回率", recall: "检索召回率", reciprocal_rank: "检索 MRR" } as Record<string, string>)[value] || value.replaceAll("_", " "); }
function metricDeltaTone(delta: number | null): string { return delta === null ? "unscored" : delta > 0 ? "positive" : delta < 0 ? "negative" : "flat"; }
function metricDeltaLabel(delta: number | null): string { return delta === null ? "无可比数据" : delta > 0 ? "候选升高" : delta < 0 ? "候选降低" : "保持不变"; }
function sampleClassificationLabel(value: string): string { return ({ improved: "整体改善", regressed: "整体退化", mixed: "指标分歧", unchanged: "基本持平", unscored: "未评分" } as Record<string, string>)[value] || value; }
function sampleClassificationTone(value: string): string { return ({ improved: "positive", regressed: "negative", mixed: "mixed", unchanged: "flat", unscored: "unscored" } as Record<string, string>)[value] || "unscored"; }
function sampleMetric(sample: EvaluationDiff["sample_deltas"][number], metric: string) { return sample.metrics.find((item) => item.metric === metric); }

const sampleMetricOrder = ["answer_relevancy", "context_recall", "context_utilization", "faithfulness", "recall", "reciprocal_rank"];
const sampleMetricKeys = computed(() => {
  const present = new Set((diffResult.value?.sample_deltas || []).flatMap((sample) => sample.metrics.filter((metric) => typeof metric.base === "number" || typeof metric.candidate === "number").map((metric) => metric.metric)));
  return [...sampleMetricOrder.filter((metric) => present.has(metric)), ...Array.from(present).filter((metric) => !sampleMetricOrder.includes(metric)).sort()];
});
const visibleSampleDeltas = computed(() => {
  const rows = (diffResult.value?.sample_deltas || []).filter((sample) => sampleFilter.value === "all" || sample.classification === sampleFilter.value);
  const sorted = [...rows];
  if (sampleSort.value === "classification") {
    const order: Record<string, number> = { regressed: 0, mixed: 1, unchanged: 2, improved: 3, unscored: 4 };
    sorted.sort((left, right) => (order[left.classification] ?? 9) - (order[right.classification] ?? 9) || left.sample_id.localeCompare(right.sample_id));
  } else if (sampleSort.value === "largest_drop") {
    const worstDelta = (sample: EvaluationDiff["sample_deltas"][number]) => Math.min(...sample.metrics.map((metric) => metric.delta ?? 0));
    sorted.sort((left, right) => worstDelta(left) - worstDelta(right) || left.sample_id.localeCompare(right.sample_id));
  }
  return sorted;
});
function toggleSource(sourceId: string) { selectedSourceIds.value = selectedSourceIds.value.includes(sourceId) ? selectedSourceIds.value.filter((value) => value !== sourceId) : [...selectedSourceIds.value, sourceId]; }

function selectNav(nav: NavId) {
  activeNav.value = nav;
  if (nav === "evaluation") { evaluationSection.value = "config"; void loadConfig(); }
  if (nav === "reports") { void loadEvaluationHistory(); }
}

function selectEvaluationSection(section: EvaluationSection) {
  activeNav.value = "evaluation";
  evaluationSection.value = section;
  if (section === "config") void loadConfig();
  if (section === "comparison") void refreshComparison();
}

function toggleSidebar() { sidebarCollapsed.value = !sidebarCollapsed.value; localStorage.setItem("sidebar_collapsed", String(sidebarCollapsed.value)); }

function configMeta(key: string): ParameterMeta { return configData.value?.parameter_meta?.[key] || { label: key, meaning: "" }; }
function formatRange(range?: [number, number]): string { return range ? `[${range[0]}, ${range[1]}]` : "未定义"; }
function configTooltip(key: string): string { const meta = configMeta(key); return `${meta.meaning} 建议范围：${formatRange(meta.recommended)}；硬限制：${formatRange(meta.allowed)}`; }
function draftDisplay(draft: Record<string, unknown>, key: string): string { const value = draft[key]; return value === null || value === undefined ? "" : String(value); }
function updateDraft(draft: Record<string, unknown>, key: string, event: Event) {
  const raw = (event.target as HTMLInputElement).value;
  if (raw === "") { draft[key] = null; return; }
  draft[key] = configMeta(key).integer ? Number.parseInt(raw, 10) : Number(raw);
}
function selectedMetrics(): string[] { return Array.isArray(ragasDraft.value.selected_metrics) ? ragasDraft.value.selected_metrics as string[] : []; }
function isMetricSelected(metric: string): boolean { return selectedMetrics().includes(metric); }
function toggleMetric(metric: string) { const values = selectedMetrics(); ragasDraft.value.selected_metrics = values.includes(metric) ? values.filter((value) => value !== metric) : [...values, metric]; }

function evaluationRagasOptions(): Record<string, unknown> {
  return Object.fromEntries(
    evaluationRagasKeys
      .filter((key) => key in ragasDraft.value)
      .map((key) => [key, ragasDraft.value[key]]),
  );
}

function selectedStrategyProfile(): StrategyProfile | null {
  return strategyProfiles.value.find((profile) => profile.profile_id === strategyProfileId.value) || null;
}

function applyStrategyProfile(profileId = strategyProfileId.value) {
  const profile = strategyProfiles.value.find((item) => item.profile_id === profileId);
  if (!profile) return;
  strategyProfileId.value = profile.profile_id;
  localStorage.setItem(strategyProfileStorageKey, profile.profile_id);
  profileNameDraft.value = profile.name;
  retrievalProfile.value = profile.retrieval_profile;
  ragasProfile.value = profile.ragas_profile;
  retrievalDraft.value = { ...profile.retrieval };
  ragasDraft.value = { ...profile.ragas };
}

async function loadStrategyProfileCatalog() {
  const catalog = await api<StrategyProfileCatalog>("/api/rag_eval/profiles");
  strategyProfiles.value = catalog.profiles || [];
  publishedProfileId.value = catalog.published_profile_id || "active_current";
  const storedProfileId = localStorage.getItem(strategyProfileStorageKey);
  const storedProfile = strategyProfiles.value.find((profile) => profile.profile_id === storedProfileId);
  const currentProfile = strategyProfiles.value.find((profile) => profile.profile_id === strategyProfileId.value);
  const preferredProfileId = storedProfile?.profile_id
    || currentProfile?.profile_id
    || catalog.default_profile_id
    || "active_current";
  if (storedProfileId && !storedProfile) localStorage.removeItem(strategyProfileStorageKey);
  applyStrategyProfile(preferredProfileId);
}

async function loadProductionConfig() {
  try { productionConfig.value = await api<ProductionConfig>("/api/rag_eval/production-config"); }
  catch (error) { configError.value = error instanceof Error ? error.message : "正式配置加载失败"; }
}

async function loadConfig() {
  configLoading.value = true;
  configError.value = "";
  try {
    const data = await api<RagEvalConfig>("/api/rag_eval/config");
    configData.value = data;
    await loadStrategyProfileCatalog();
    await loadProductionConfig();
  } catch (error) { configError.value = error instanceof Error ? error.message : "评测配置加载失败"; }
  finally { configLoading.value = false; }
}


async function saveConfig() {
  configSaving.value = true; configMessage.value = ""; configError.value = "";
  try {
    const profile = selectedStrategyProfile();
    if (!profile) throw new Error("当前策略 profile 不存在，请重新加载");
    if (!profile.editable) throw new Error("内置 profile 只读，请使用“另存为”创建自定义 profile");
    await api<StrategyProfile>("/api/rag_eval/profiles/" + encodeURIComponent(profile.profile_id), {
      method: "PUT",
      body: JSON.stringify({
        name: profileNameDraft.value,
        retrieval_profile: retrievalProfile.value,
        ragas_profile: ragasProfile.value,
        retrieval: { ...retrievalDraft.value },
        ragas: { ...evaluationRagasOptions() },
      }),
    });
    await loadStrategyProfileCatalog();
    applyStrategyProfile(profile.profile_id);
    configMessage.value = "自定义 profile 已保存";
  } catch (error) { configError.value = error instanceof Error ? error.message : "配置保存失败"; }
  finally { configSaving.value = false; }
}

async function saveAsProfile() {
  configSaving.value = true; configMessage.value = ""; configError.value = "";
  try {
    const name = profileNameDraft.value.trim();
    if (!name) throw new Error("请先填写自定义 profile 名称");
    const created = await api<StrategyProfile>("/api/rag_eval/profiles", {
      method: "POST",
      body: JSON.stringify({
        name,
        retrieval_profile: retrievalProfile.value,
        ragas_profile: ragasProfile.value,
        retrieval: { ...retrievalDraft.value },
        ragas: { ...evaluationRagasOptions() },
      }),
    });
    await loadStrategyProfileCatalog();
    applyStrategyProfile(created.profile_id);
    configMessage.value = "已创建自定义 profile：" + created.name;
  } catch (error) { configError.value = error instanceof Error ? error.message : "创建 profile 失败"; }
  finally { configSaving.value = false; }
}

async function deleteProfile() {
  const profile = selectedStrategyProfile();
  if (!profile || !profile.editable) { configError.value = "内置 profile 不可删除"; return; }
  if (!window.confirm("确定删除 profile“" + profile.name + "”吗？")) return;
  configSaving.value = true; configMessage.value = ""; configError.value = "";
  try {
    await api("/api/rag_eval/profiles/" + encodeURIComponent(profile.profile_id), { method: "DELETE" });
    await loadStrategyProfileCatalog();
    configMessage.value = "自定义 profile 已删除";
  } catch (error) { configError.value = error instanceof Error ? error.message : "删除 profile 失败"; }
  finally { configSaving.value = false; }
}

async function publishConfig() {
  configSaving.value = true; configMessage.value = ""; configError.value = "";
  try {
    const profile = selectedStrategyProfile();
    if (!profile || !profile.editable) throw new Error("只有自定义 profile 可以发布为正式配置");
    await api<StrategyProfile>("/api/rag_eval/profiles/" + encodeURIComponent(profile.profile_id) + "/publish", {
      method: "POST",
      body: JSON.stringify({ note: "从 RAG 评测中心显式发布" }),
    });
    await loadProductionConfig();
    await loadStrategyProfileCatalog();
    applyStrategyProfile(profile.profile_id);
    configMessage.value = "已发布为正式 RAG 配置，默认 profile 已切换";
  } catch (error) { configError.value = error instanceof Error ? error.message : "正式配置发布失败"; }
  finally { configSaving.value = false; }
}

async function startEvaluation() {
  actionError.value = "";
  if (!ingestionReady.value || !ingestion.value) { actionError.value = "请先在工作台完成知识源摄取并生成 staged index"; return; }
  if (!datasetText.value.trim()) { actionError.value = "请粘贴通用 rag_eval_v1 题集 JSON"; return; }
  let dataset: Record<string, unknown>;
  try { dataset = JSON.parse(datasetText.value) as Record<string, unknown>; }
  catch { actionError.value = "题集 JSON 格式无效，请检查引号和括号是否完整"; return; }
  if (dataset.schema_version !== "rag_eval_v1" || !Array.isArray(dataset.samples) || !dataset.samples.length) { actionError.value = "题集必须包含 schema_version=rag_eval_v1 和非空 samples"; return; }
  const strategy = selectedStrategyProfile();
  if (!strategy) { actionError.value = "当前策略 profile 不存在，请重新加载"; return; }
  const steps = executeRagas.value
    ? ["validate_datasets", "retrieval_eval", "ragas_eval", "trace_export", "summary"]
    : ["validate_datasets", "retrieval_eval", "summary"];
  evaluationLoading.value = true; evaluationResult.value = null; events.value = [];
  try {
    const state = await api<RunState>("/api/rag_eval/isolated/evaluation-runs", {
      method: "POST",
      body: JSON.stringify({
        ingestion_run_id: ingestion.value.run_id,
        index_version: ingestion.value.index_version,
        eval_dataset: dataset,
        strategy_profile: { profile_id: strategy.profile_id, name: strategy.name, kind: strategy.kind },
        retrieval: { profile: retrievalProfile.value, overrides: { ...retrievalDraft.value } },
        ragas: { profile: ragasProfile.value, ...evaluationRagasOptions(), run: executeRagas.value, prepare_only: false },
        steps,
      }),
    });
    evaluationRun.value = state;
    evaluationAwaitingCompletion.value = state.run_id;
    localStorage.setItem("evaluation_run_id", state.run_id);
    watchRun("evaluation", state.run_id);
    evaluationSection.value = "events";
  } catch (error) { evaluationLoading.value = false; actionError.value = error instanceof Error ? error.message : "评测任务启动失败"; }
}

async function cancelEvaluation() {
  if (!evaluationRun.value) return;
  try {
    evaluationRun.value = await api<RunState>(`/api/rag_eval/isolated/evaluation-runs/${encodeURIComponent(evaluationRun.value.run_id)}/cancel`, { method: "POST", body: "{}" });
    notifyEvaluationFinished(evaluationRun.value);
  }
  catch (error) { actionError.value = error instanceof Error ? error.message : "取消评测失败"; }
}

async function restoreIngestionRun(preferredId: string | null): Promise<boolean> {
  if (preferredId) {
    try {
      const state = await refreshRun("ingestion", preferredId);
      if (!terminalStatuses.includes(state.status)) watchRun("ingestion", preferredId);
      return true;
    } catch {
      localStorage.removeItem("ingestion_run_id");
      localStorage.removeItem("r5_ingestion_run_id");
    }
  }

  try {
    const history = await api<IngestionHistory>("/api/rag_eval/isolated/ingestion-runs?page=1&page_size=50");
    const state = history.items.find((item) => ["created", "queued", "running", "cancelling"].includes(item.status))
      || history.items.find((item) => item.status === "staged");
    if (!state) return false;
    ingestion.value = state;
    localStorage.setItem("ingestion_run_id", state.run_id);
    if (state.source_ids?.length) selectedSourceIds.value = [...state.source_ids];
    if (!terminalStatuses.includes(state.status)) watchRun("ingestion", state.run_id);
    sourceNotice.value = "已从持久化记录恢复摄取状态：" + state.run_id;
    return true;
  } catch {
    return false;
  }
}

async function refreshWorkspace() {
  actionError.value = "";
  await loadCatalog();
  const ingestionId = localStorage.getItem("ingestion_run_id") || localStorage.getItem("r5_ingestion_run_id");
  await restoreIngestionRun(ingestionId);
}

async function restoreRuns() {
  const ingestionId = localStorage.getItem("ingestion_run_id") || localStorage.getItem("r5_ingestion_run_id");
  const evaluationId = localStorage.getItem("evaluation_run_id") || localStorage.getItem("r5_evaluation_run_id");
  await restoreIngestionRun(ingestionId);
  if (evaluationId) {
    try {
      const state = await refreshRun("evaluation", evaluationId);
      if (!terminalStatuses.includes(state.status)) watchRun("evaluation", evaluationId);
    } catch {
      localStorage.removeItem("evaluation_run_id");
      localStorage.removeItem("r5_evaluation_run_id");
    }
  }
}

watch([historyRange, historySource], () => { if (activeNav.value === "reports" || evaluationSection.value === "comparison") void refreshComparison(); });
watch(comparisonMode, () => { if (evaluationSection.value === "comparison") void refreshComparison(); });
watch(strategyProfileId, (profileId, previousProfileId) => {
  if (profileId !== previousProfileId && strategyProfiles.value.length) {
    localStorage.setItem(strategyProfileStorageKey, profileId);
    applyStrategyProfile(profileId);
  }
});

onMounted(async () => {
  sidebarCollapsed.value = localStorage.getItem("sidebar_collapsed") === "true" || localStorage.getItem("r5_sidebar_collapsed") === "true";
  await loadCatalog();
  await loadConfig();
  await restoreRuns();
});
onUnmounted(() => {
  stopWatching();
  dismissEvaluationToast();
});
</script>

<template>
  <div v-if="evaluationToast" class="evaluation-toast" role="status" aria-live="polite">
    <Check :size="17" />
    <span>{{ evaluationToast }}</span>
    <button type="button" aria-label="关闭提示" @click="dismissEvaluationToast">×</button>
  </div>
  <div class="app-shell" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
    <aside class="app-sidebar">
      <div class="brand-row">
        <div class="brand-mark"><span class="brand-icon"><BarChart3 :size="18" /></span><span class="brand-label">因果知识台</span></div>
        <button type="button" class="sidebar-toggle" :title="sidebarCollapsed ? '展开导航栏' : '收起导航栏'" :aria-label="sidebarCollapsed ? '展开导航栏' : '收起导航栏'" @click="toggleSidebar"><PanelLeftOpen v-if="sidebarCollapsed" :size="17" /><PanelLeftClose v-else :size="17" /></button>
      </div>
      <div class="sidebar-caption">CAUSAL AGENT</div>
      <nav class="side-nav" aria-label="主导航">
        <button class="nav-item" :class="{ active: activeNav === 'workspace' }" title="工作台" aria-label="工作台" @click="selectNav('workspace')"><LayoutDashboard :size="17" /><span>工作台</span></button>
        <button class="nav-item" :class="{ active: activeNav === 'evaluation' }" title="评测中心" aria-label="评测中心" @click="selectNav('evaluation')"><Gauge :size="17" /><span>评测中心</span></button>
        <div v-if="activeNav === 'evaluation'" class="nav-submenu" aria-label="评测中心导航">
          <button class="nav-subitem" :class="{ active: evaluationSection === 'config' }" @click="selectEvaluationSection('config')">评测配置</button>
          <button class="nav-subitem" :class="{ active: evaluationSection === 'events' }" @click="selectEvaluationSection('events')">评测流程事件</button>
          <button class="nav-subitem" :class="{ active: evaluationSection === 'comparison' }" @click="selectEvaluationSection('comparison')">对比分析</button>
        </div>
        <button class="nav-item" :class="{ active: activeNav === 'reports' }" title="报告编辑" aria-label="报告编辑" @click="selectNav('reports')"><FileChartColumn :size="17" /><span>报告编辑</span></button>
      </nav>
      <div class="sidebar-footer"><span class="sidebar-status-dot"></span><div><strong>隔离环境</strong><small>staged index only</small></div></div>
    </aside>

    <section class="app-main" :class="{ 'comparison-main': activeNav === 'evaluation' && evaluationSection === 'comparison' }">
      <header class="topbar">
        <div>
          <p class="kicker">知识检索与评测</p>
          <h1>{{ activeNav === 'workspace' ? '隔离知识源工作台' : activeNav === 'reports' ? '报告编辑' : evaluationSection === 'config' ? '评测配置' : evaluationSection === 'events' ? '评测流程事件' : '对比分析' }}</h1>
        </div>
        <div class="topbar-meta"><span class="live-dot"></span><span>后端接口已连接</span><button class="icon-button" title="刷新当前数据" aria-label="刷新当前数据" @click="activeNav === 'reports' ? loadEvaluationHistory() : refreshWorkspace()"><RefreshCw :size="16" :class="{ spinning: sourceLoading || historyLoading }" /></button></div>
      </header>

      <main class="content" :class="{ 'comparison-content': activeNav === 'evaluation' && evaluationSection === 'comparison' }">
        <template v-if="activeNav === 'workspace'">
          <div class="stage-line" aria-label="运行阶段"><div class="stage-marker active"><span>01</span><strong>知识源摄取</strong><small>多模态解析 · 标准化 · Chroma</small></div><div class="stage-connector"></div><div class="stage-marker" :class="{ active: ingestionReady }"><span>02</span><strong>评测中心</strong><small>retrieval · Ragas · 报告</small></div></div>
          <div v-if="actionError || catalogError" class="alert danger-alert"><AlertCircle :size="17" /><span>{{ actionError || catalogError }}</span></div>
          <div v-if="sourceNotice" class="alert success-alert"><Check :size="17" /><span>{{ sourceNotice }}</span></div>
          <section class="workspace-grid workbench-layout">
            <article class="panel source-panel">
              <div class="panel-header"><div class="panel-title"><span class="icon-badge coral"><Database :size="18" /></span><div><p class="eyebrow">SOURCE INPUT</p><h2>选择知识源</h2></div></div><div class="source-panel-actions"><span class="count-label">{{ selectedSources.length }} / {{ sources.length }}</span><input ref="uploadInput" class="visually-hidden" type="file" :accept="supportedUploadExtensions.join(',')" @change="uploadSource" /><button type="button" class="secondary-button upload-button" :disabled="busy" @click="openUploadDialog"><Upload :size="15" />{{ uploadLoading ? '上传中' : '上传知识源' }}</button></div></div>
              <div class="source-capability-note"><strong>多模态解析</strong><span>支持 {{ supportedUploadLabel }}；文本、表格、图片以及 PDF 中的版面、公式、表格和图片会统一解析为可追溯的知识单元。</span></div>
              <div v-if="sourceLoading && !sources.length" class="empty-line"><LoaderCircle class="spin" :size="17" />加载来源目录</div>
              <div v-else-if="!sources.length" class="empty-line"><FileText :size="17" />暂无可选来源</div>
              <div v-else class="source-list"><div v-for="source in sources" :key="source.source_id" class="source-row" :class="{ selected: selectedSourceIds.includes(source.source_id) }"><label class="source-select"><input type="checkbox" :checked="selectedSourceIds.includes(source.source_id)" @change="toggleSource(source.source_id)" /><span class="source-check"><Check :size="14" /></span><span class="source-copy"><strong>{{ source.name }}</strong><small>{{ source.source_kind === 'uploaded' ? '用户上传' : '固定来源' }} · {{ source.page_count ? `${source.page_count} 页` : '页数待读取' }} · {{ formatBytes(source.size_bytes) }} · {{ source.content_sha256.slice(0, 12) }}</small></span></label><button v-if="source.source_kind === 'uploaded'" type="button" class="source-delete-button" :disabled="busy || sourceDeleteLoading === source.source_id" :title="`删除 ${source.name}`" :aria-label="`删除 ${source.name}`" @click="deleteSource(source)"><Trash2 :size="15" /></button></div></div>
              <div class="run-options"><label>运行范围<select v-model="pageLimit"><option value="4">快速联调 · 4 页</option><option value="12">Smoke · 12 页</option><option value="all">全部来源页</option><option value="custom">自定义页码范围</option></select></label><span>{{ pageLimit === 'custom' ? '按来源分别执行物理页范围' : '快速模式按选中来源顺序累计页数' }}；每次创建新的 staged index</span></div>
              <div v-if="pageLimit === 'custom'" class="custom-range-panel"><div class="custom-range-heading"><strong>按来源设置物理页码</strong><small>页码从 1 开始，首尾包含；本次共 {{ customPageTotal }} 页</small></div><div v-for="source in selectedSources" :key="`range-${source.source_id}`" class="custom-range-row"><span>{{ source.name }}</span><input v-model="pageRanges[source.source_id].start" type="number" min="1" aria-label="开始页" /><span>至</span><input v-model="pageRanges[source.source_id].end" type="number" min="1" aria-label="结束页" /><small>页</small></div></div>
              <div class="panel-footer"><button class="primary-button" :disabled="busy || !selectedSourceIds.length" @click="startIngestion"><Play :size="16" />{{ ingestionReady ? '重新摄取' : '开始摄取' }}</button><button v-if="ingestion && ['created','running','cancelling'].includes(ingestion.status)" class="secondary-button danger" :disabled="ingestion.status === 'cancelling'" @click="cancelIngestion">取消</button></div>
              <div v-if="ingestion" class="run-summary"><div class="summary-line"><span>摄取任务</span><code>{{ ingestion.run_id }}</code><span class="status-pill" :class="statusTone(ingestion.status)">{{ statusLabel(ingestion.status) }}</span></div><div class="progress-track"><span :style="{ width: ingestion.status === 'staged' ? '100%' : ingestion.status === 'running' ? '48%' : '0%' }"></span></div><div class="summary-metrics"><span>units <b>{{ ingestion.unit_count ?? '--' }}</b></span><span>vectors <b>{{ ingestion.vector_count ?? '--' }}</b></span><span>index <b>{{ ingestion.index_version || '--' }}</b></span></div></div>
            </article>
              <aside class="panel workspace-guide"><div class="panel-header"><div class="panel-title"><span class="icon-badge teal"><SlidersHorizontal :size="18" /></span><div><p class="eyebrow">NEXT STEP</p><h2>统一评测流程</h2></div></div></div><div class="guide-body"><div class="guide-state" :class="{ ready: ingestionReady }"><Check :size="17" /><span>{{ ingestionReady ? 'staged index 已就绪' : '等待 staged index' }}</span></div><p>工作台只负责选择知识源和生成隔离索引。题集、retrieval、Ragas judge、事件和报告统一在评测中心管理。</p><button class="primary-button" :disabled="!ingestionReady" @click="selectNav('evaluation')"><Gauge :size="16" />前往评测中心</button><button class="secondary-button" :disabled="!evaluationRun" @click="evaluationRun && openReport(evaluationRun.run_id)"><FileChartColumn :size="16" />编辑最近报告</button></div></aside>
          </section>
        </template>

        <template v-else-if="activeNav === 'evaluation'">
          <section v-if="evaluationSection === 'config' && configData" class="panel strategy-profile-panel">
            <div class="strategy-profile-controls">
              <label>策略 profile<select v-model="strategyProfileId"><option v-for="profile in strategyProfiles" :key="profile.profile_id" :value="profile.profile_id">{{ profile.name }}{{ profile.kind === 'builtin' ? '（内置只读）' : '（自定义）' }}</option></select></label>
              <label>profile 名称<input v-model="profileNameDraft" type="text" maxlength="120" /></label>
              <div class="strategy-profile-actions">
                <button class="secondary-button" :disabled="configSaving" @click="saveAsProfile">另存为自定义</button>
                <button class="secondary-button" :disabled="configSaving || selectedStrategyProfile()?.editable !== true" @click="deleteProfile">删除</button>
              </div>
            </div>
            <small class="strategy-profile-hint">内置 profile 不可直接修改；保存自定义 profile 后，只有显式发布才会切换正式默认配置。当前正式：{{ strategyProfiles.find((profile) => profile.profile_id === publishedProfileId)?.name || 'active_current' }}</small>
          </section>
          <div class="evaluation-intro"><div><p class="kicker">评测中心</p><h2>{{ evaluationSection === 'config' ? '统一启动 retrieval baseline 与 Ragas judge' : evaluationSection === 'events' ? '跟踪本次评测的每个阶段' : '比较不同时间、知识源与策略运行' }}</h2><p>评测绑定明确的 staged index 和通用 rag_eval_v1 题集；每次运行都会生成独立报告产物。</p></div><span v-if="evaluationRun" class="status-pill" :class="statusTone(evaluationRun.status)">{{ statusLabel(evaluationRun.status) }}</span></div>
          <div v-if="actionError || configError || comparisonError" class="alert danger-alert"><AlertCircle :size="17" /><span>{{ actionError || configError || comparisonError }}</span></div>
          <div v-if="configMessage" class="alert success-alert"><Check :size="17" /><span>{{ configMessage }}</span></div>

          <template v-if="evaluationSection === 'config'">
            <div class="ai-waiting-notice"><AlertCircle :size="17" /><span>{{ executeRagas ? '本次流程包含回答生成和 Ragas judge，涉及大模型；开始后请耐心等待，完成时会弹窗提示。' : '当前为只运行 retrieval 模式，不调用回答生成模型或 Ragas judge。' }}</span></div>
            <section class="config-layout">
              <article class="panel evaluation-config-panel">
                <div class="panel-header"><div class="panel-title"><span class="icon-badge teal"><SlidersHorizontal :size="18" /></span><div><p class="eyebrow">EVALUATION CONFIG</p><h2>当前评测配置</h2></div></div><button class="secondary-button" :disabled="configLoading" @click="loadConfig"><RefreshCw :size="15" :class="{ spinning: configLoading }" />重新加载</button></div>
                <div v-if="configLoading && !configData" class="empty-line"><LoaderCircle class="spin" :size="17" />加载评测配置</div>
                <div v-else-if="configData" class="config-body">
                  <div class="config-selectors"><label>检索 profile<select v-model="retrievalProfile"><option v-for="profile in Object.keys(configData.retrieval_profiles)" :key="profile" :value="profile">{{ profile }}</option></select></label><label>Ragas profile<select v-model="ragasProfile"><option v-for="profile in configData.ragas.available_profiles" :key="profile" :value="profile">{{ profile }}</option></select></label></div>
                  <div class="config-section-heading"><strong>检索参数</strong><small>鼠标悬停参数说明可查看建议范围和硬限制</small></div>
                  <div class="config-fields"><label v-for="field in retrievalFieldKeys" :key="`retrieval-${field}`" class="config-field"><span class="field-title"><span>{{ configMeta(field).label }}</span><span class="config-help" :title="configTooltip(field)">?</span></span><input :value="draftDisplay(retrievalDraft, field)" type="number" :step="configMeta(field).integer ? 1 : 0.01" @input="updateDraft(retrievalDraft, field, $event)" /><small>建议 {{ formatRange(configMeta(field).recommended) }} · 硬限制 {{ formatRange(configMeta(field).allowed) }}</small></label></div>
                  <div class="config-section-heading"><strong>Ragas judge 参数</strong><small>超出硬限制会被后端拒绝，建议范围外会提示复核</small></div>
                  <div class="config-fields"><label v-for="field in ragasFieldKeys" :key="`ragas-${field}`" class="config-field"><span class="field-title"><span>{{ configMeta(field).label }}</span><span class="config-help" :title="configTooltip(field)">?</span></span><input :value="draftDisplay(ragasDraft, field)" type="number" :step="configMeta(field).integer ? 1 : 0.01" @input="updateDraft(ragasDraft, field, $event)" /><small>建议 {{ formatRange(configMeta(field).recommended) }} · 硬限制 {{ formatRange(configMeta(field).allowed) }}</small></label></div>
                  <div class="metric-selector"><strong>Ragas 指标</strong><label v-for="metric in metricOptions" :key="metric"><input type="checkbox" :checked="isMetricSelected(metric)" @change="toggleMetric(metric)" />{{ metric }}</label></div>
                   <label class="switch-row"><input v-model="executeRagas" type="checkbox" /><span class="switch-control"></span><span><strong>执行完整 Ragas 评测</strong><small>{{ executeRagas ? '开启后会生成当前检索策略的回答和上下文，再调用 Ragas judge；涉及大模型，请耐心等待。' : '关闭后只运行 retrieval，不调用回答生成模型或 Ragas judge。' }}</small></span></label>
                  <div class="panel-footer"><button class="primary-button" :disabled="configSaving" @click="saveConfig"><Check :size="16" />保存评测配置</button><button class="secondary-button" :disabled="configSaving" @click="publishConfig"><FileChartColumn :size="16" />发布到正式配置</button></div>
                </div>
              </article>
              <aside class="panel production-panel"><div class="panel-header"><div class="panel-title"><span class="icon-badge gold"><Database :size="18" /></span><div><p class="eyebrow">PRODUCTION CONFIG</p><h2>当前正式配置</h2></div></div><span class="status-pill" :class="productionConfig?.exists ? 'success' : 'muted'">{{ productionConfig?.exists ? '已存在' : '未发布' }}</span></div><div class="production-body"><p>这里展示正式 RAG 当前读取的检索参数。只有显式点击发布后才会更新正式配置文件。</p><pre v-if="productionConfig?.retrieval_config">{{ JSON.stringify(productionConfig.retrieval_config, null, 2) }}</pre><div v-else class="empty-line">暂无正式配置</div><div class="production-meta" v-if="productionConfig?.metadata"><span>最近发布</span><code>{{ String(productionConfig.metadata.published_at || '--') }}</code></div></div></aside>
            </section>
             <section class="panel dataset-panel"><div class="panel-header"><div class="panel-title"><span class="icon-badge coral"><FileText :size="18" /></span><div><p class="eyebrow">DATASET INPUT</p><h2>通用 rag_eval_v1 题集</h2></div></div><span class="count-label">不绑定特定题集</span></div><div class="dataset-body"><p>评测数据由本次运行显式快照保存。当前正式题集可以粘贴到这里，后续知识源评测继续复用同一 schema。</p><textarea v-model="datasetText" rows="8" placeholder="请粘贴 rag_eval_v1 题集 JSON"></textarea></div><div class="bound-index"><span>评测索引</span><code>{{ ingestion?.index_version || '--' }}</code><span class="bound-check"><Check :size="13" />{{ ingestionReady ? '已就绪' : '请先摄取知识源' }}</span></div><div class="panel-footer"><button class="primary-button" :disabled="evaluationLoading || !ingestionReady" @click="startEvaluation"><Play :size="16" />{{ executeRagas ? '开始完整评测' : '开始只运行检索' }}</button><button v-if="evaluationRun && ['created','running','cancelling'].includes(evaluationRun.status)" class="secondary-button danger" :disabled="evaluationRun.status === 'cancelling'" @click="cancelEvaluation">取消</button></div></section>
          </template>

          <template v-else-if="evaluationSection === 'events'"><div v-if="evaluationActive" class="ai-waiting-notice"><LoaderCircle class="spin" :size="17" /><span>{{ evaluationWaitingMessage }}</span></div><section class="panel evaluation-events-panel"><div class="panel-header"><div class="panel-title"><span class="icon-badge slate"><CircleDot :size="18" /></span><div><p class="eyebrow">EVALUATION TRACE</p><h2>评测流程事件</h2></div></div><span class="count-label">{{ displayEvents.length }} 条（重复进度已合并）</span></div><div class="event-list evaluation-event-list"><div v-if="!displayEvents.length" class="empty-line">等待评测中心启动任务</div><div v-for="(event, index) in displayEvents" :key="`${event.timestamp}-${index}`" class="event-row"><span class="event-time">{{ formatBeijingTime(event.timestamp) }}</span><span class="event-type">{{ event.type }}</span><span>{{ event.message }}</span></div></div></section><div class="event-actions"><button class="secondary-button" @click="selectEvaluationSection('config')"><SlidersHorizontal :size="15" />返回评测配置</button><button class="secondary-button" :disabled="!evaluationRun" @click="evaluationRun && openReport(evaluationRun.run_id)"><FileChartColumn :size="15" />编辑本次报告</button></div></template>

          <template v-else><section class="comparison-layout"><article class="panel comparison-panel"><div class="panel-header"><div class="panel-title"><span class="icon-badge teal"><GitCompare :size="18" /></span><div><p class="eyebrow">EVALUATION COMPARISON</p><h2>时间趋势与运行对比</h2></div></div><span class="count-label">隔离数据</span></div><div class="comparison-controls"><label>时间跨度<select v-model="historyRange"><option value="7d">近 7 天</option><option value="30d">近 30 天</option><option value="90d">近 90 天</option><option value="all">全部历史</option></select></label><label>知识源<select v-model="historySource"><option value="">全部知识源</option><option v-for="source in sourceFilterOptions" :key="source" :value="source">{{ source }}</option></select></label><label>粒度<select v-model="comparisonGranularity"><option value="day">按天</option><option value="run">按运行</option></select></label><button class="secondary-button" @click="refreshComparison"><RefreshCw :size="15" />刷新</button></div><div class="comparison-mode-grid"><button class="comparison-mode" :class="{ selected: comparisonMode === 'time_trend' }" @click="comparisonMode = 'time_trend'"><TrendingUp :size="18" /><span>时间趋势</span><small>观察指标随时间变化</small></button><button class="comparison-mode" :class="{ selected: comparisonMode === 'run_diff' }" @click="comparisonMode = 'run_diff'"><GitCompare :size="18" /><span>运行 A/B</span><small>比较基线与候选 run</small></button><button class="comparison-mode" :class="{ selected: comparisonMode === 'strategy_diff' }" @click="comparisonMode = 'strategy_diff'"><SlidersHorizontal :size="18" /><span>策略对比</span><small>比较检索与 Ragas 配置</small></button></div><div v-if="historyLoading || diffLoading" class="comparison-empty"><LoaderCircle class="spin" :size="24" />正在读取隔离评测</div><template v-else-if="comparisonMode === 'time_trend'"><div v-if="!trendRows.length" class="comparison-empty"><TrendingUp :size="24" /><strong>暂无可比较的隔离评测</strong><p>完成通用 rag_eval_v1 评测后，这里会展示真实历史趋势。</p></div><div v-else class="comparison-table-wrap"><table class="comparison-table"><thead><tr><th>时间</th><th>运行数</th><th v-for="metric in historyMetricKeys" :key="metric">{{ metricLabel(metric) }}</th></tr></thead><tbody><tr v-for="row in trendRows" :key="row.label"><td class="mono">{{ row.label }}</td><td>{{ row.count }}</td><td v-for="metric in historyMetricKeys" :key="metric">{{ formatMetric(row.metrics[metric]) }}</td></tr></tbody></table></div></template><template v-else><div class="diff-controls"><label>基线<select v-model="diffBaseRunId"><option v-for="run in historyRuns" :key="`base-${run.run_id}`" :value="run.run_id">{{ historyLabel(run) }}</option></select></label><label>候选<select v-model="diffCandidateRunId"><option v-for="run in historyRuns" :key="`candidate-${run.run_id}`" :value="run.run_id">{{ historyLabel(run) }}</option></select></label><button class="secondary-button" @click="loadEvaluationDiff"><GitCompare :size="15" />加载对比</button></div><div v-if="!diffResult" class="comparison-empty"><GitCompare :size="24" /><strong>选择两个隔离评测运行</strong><p>运行 A/B 与策略对比要求题集 identity 一致；跨题集比较会被后端拒绝。</p></div><template v-else><div class="comparison-table-wrap metric-comparison-wrap"><table class="comparison-table metric-comparison-table"><thead><tr><th>指标</th><th>基线</th><th>候选</th><th>变化</th></tr></thead><tbody><tr v-for="metric in diffResult.metric_deltas" :key="metric.metric"><th scope="row">{{ metricLabel(metric.metric) }}</th><td>{{ formatMetric(metric.base) }}</td><td>{{ formatMetric(metric.candidate) }}</td><td><span class="metric-change" :class="metricDeltaTone(metric.delta)" :title="metricDeltaLabel(metric.delta)"><ArrowUp v-if="metric.delta !== null && metric.delta > 0" :size="15" aria-hidden="true" /><ArrowDown v-else-if="metric.delta !== null && metric.delta < 0" :size="15" aria-hidden="true" /><Minus v-else :size="15" aria-hidden="true" /><span>{{ formatMetric(metric.delta) }}</span></span></td></tr></tbody></table></div><div v-if="diffResult.config_deltas.length" class="config-diff-section"><div class="diff-section-heading"><div><h3>配置差异</h3><p>以下差异来自两次 run 的独立配置快照。</p></div><span>{{ diffResult.config_deltas.length }} 项</span></div><div class="comparison-table-wrap config-diff-wrap"><table class="comparison-table config-diff-table"><thead><tr><th>配置项</th><th>基线</th><th>候选</th></tr></thead><tbody><tr v-for="item in diffResult.config_deltas" :key="item.field"><th scope="row">{{ configFieldLabel(item.field) }}<small class="config-field-path">{{ item.field }}</small></th><td><code>{{ formatConfigValue(item.base) }}</code></td><td><code>{{ formatConfigValue(item.candidate) }}</code></td></tr></tbody></table></div></div><div class="diff-summary"><span>样本 {{ diffResult.summary.sample_count }}</span><span>整体改善 {{ diffResult.summary.improved_count }}</span><span>整体退化 {{ diffResult.summary.regressed_count }}</span><span title="持续坏例可与整体改善、整体退化和指标分歧重叠">持续坏例 {{ diffResult.summary.persistent_bad_case_count }} <small>可重叠</small></span></div><div class="comparison-legend" aria-label="指标变化图例"><span class="positive"><ArrowUp :size="14" />改善</span><span class="negative"><ArrowDown :size="14" />退化</span><span class="flat"><Minus :size="14" />持平</span><span class="unscored">未评分</span><small>数值越高越好；持续坏例可与样本结论重叠</small></div><div class="sample-diff-toolbar"><label>样本筛选<select v-model="sampleFilter"><option value="all">全部样本</option><option value="regressed">整体退化</option><option value="mixed">指标分歧</option><option value="improved">整体改善</option><option value="unchanged">基本持平</option><option value="unscored">未评分</option></select></label><label>排序<select v-model="sampleSort"><option value="default">按样本编号</option><option value="classification">退化优先</option><option value="largest_drop">最大下降优先</option></select></label><span class="sample-count-label">显示 {{ visibleSampleDeltas.length }} / {{ diffResult.sample_deltas.length }} 条</span></div><div class="comparison-table-wrap sample-diff-wrap"><table class="comparison-table sample-diff-table"><thead><tr><th>样本编号</th><th>对比结论</th><th v-for="metric in sampleMetricKeys" :key="metric">{{ metricLabel(metric) }}<small>基线 / 候选 / 变化</small></th></tr></thead><tbody><tr v-for="sample in visibleSampleDeltas" :key="sample.sample_id"><td class="mono" :title="sample.question">{{ sample.sample_id }}</td><td><span class="classification-badge" :class="sampleClassificationTone(sample.classification)">{{ sampleClassificationLabel(sample.classification) }}</span></td><td v-for="metric in sampleMetricKeys" :key="metric" class="sample-metric-cell"><template v-if="sampleMetric(sample, metric)"><div class="sample-metric"><div class="sample-metric-line"><small>基线</small><span>{{ formatMetric(sampleMetric(sample, metric)?.base) }}</span></div><div class="sample-metric-line"><small>候选</small><span :class="['sample-metric-candidate', metricDeltaTone(sampleMetric(sample, metric)?.delta ?? null)]">{{ formatMetric(sampleMetric(sample, metric)?.candidate) }} <span class="sample-metric-delta"><ArrowUp v-if="(sampleMetric(sample, metric)?.delta ?? 0) > 0" :size="13" /><ArrowDown v-else-if="(sampleMetric(sample, metric)?.delta ?? 0) < 0" :size="13" /><Minus v-else :size="13" />{{ formatMetric(sampleMetric(sample, metric)?.delta ?? null) }}</span></span></div></div></template><span v-else class="unscored">未评分</span></td></tr><tr v-if="!visibleSampleDeltas.length"><td class="sample-empty" :colspan="sampleMetricKeys.length + 2">没有符合条件的样本</td></tr></tbody></table></div></template></template></article><aside class="panel quick-actions-panel"><div class="panel-header"><div class="panel-title"><span class="icon-badge gold"><Gauge :size="18" /></span><div><p class="eyebrow">快捷操作流程</p><h2>快速处理本次对比</h2></div></div></div><div class="quick-action-list"><button class="quick-action" @click="selectEvaluationSection('config')"><span class="quick-step">01</span><span><strong>加载并修改配置</strong><small>先确认当前检索与 Ragas 参数</small></span><ChevronDown :size="16" /></button><button class="quick-action" @click="selectEvaluationSection('events')"><span class="quick-step">02</span><span><strong>核对执行事件</strong><small>确认评测没有被取消或卡住</small></span><ChevronDown :size="16" /></button><button class="quick-action" :disabled="!evaluationRun" @click="evaluationRun && openReport(evaluationRun.run_id)"><span class="quick-step">03</span><span><strong>编辑本次报告</strong><small>在报告编辑中切换三类 Markdown</small></span><ChevronDown :size="16" /></button><button class="quick-action" @click="selectNav('workspace')"><span class="quick-step">04</span><span><strong>更换知识源</strong><small>回到工作台创建新的 staged index</small></span><ChevronDown :size="16" /></button></div></aside></section></template>
        </template>

        <template v-else>
           <div class="evaluation-intro"><div><p class="kicker">REPORT WORKSPACE</p><h2>按时间、知识源和运行编辑 Markdown 报告</h2><p>报告始终来自选定的隔离 evaluation run，流程、检索和 Ragas 报告在同一页面切换；删除后历史与对比同步移除。</p></div><span v-if="selectedReportRun" class="status-pill" :class="statusTone(selectedReportRun.status)">{{ statusLabel(selectedReportRun.status) }}</span></div>
           <div v-if="reportError || comparisonError" class="alert danger-alert"><AlertCircle :size="17" /><span>{{ reportError || comparisonError }}</span></div>
           <div v-if="reportNotice" class="alert success-alert"><Check :size="17" /><span>{{ reportNotice }}</span></div>
           <section class="report-layout"><aside class="panel report-sidebar"><div class="panel-header"><div class="panel-title"><span class="icon-badge gold"><FileChartColumn :size="18" /></span><div><p class="eyebrow">REPORT HISTORY</p><h2>报告运行</h2></div></div></div><div class="report-filters"><label>时间跨度<select v-model="historyRange"><option value="7d">近 7 天</option><option value="30d">近 30 天</option><option value="90d">近 90 天</option><option value="all">全部历史</option></select></label><label>知识源<select v-model="historySource"><option value="">全部知识源</option><option v-for="source in sourceFilterOptions" :key="source" :value="source">{{ source }}</option></select></label><button class="secondary-button" @click="loadEvaluationHistory"><RefreshCw :size="15" />刷新历史</button></div><div class="report-run-list"><button v-for="run in historyRuns" :key="run.run_id" class="report-run-item" :class="{ selected: reportRunId === run.run_id }" @click="reportRunId = run.run_id; loadReportArtifact()"><span><strong>{{ runProfileName(run) }}</strong><small>{{ runDatasetSubtitle(run) }} · {{ run.question_count || 0 }} 题</small><small>{{ run.source_label || '知识源未记录' }}</small><small v-if="run.stale" class="stale-hint">长时间无进展，可确认后删除</small></span><span class="status-pill" :class="statusTone(run.status)">{{ statusLabel(run.status) }}</span></button><div v-if="!historyRuns.length" class="empty-line">暂无符合筛选条件的评测运行</div></div></aside><article class="panel report-viewer"><div class="panel-header"><div><p class="eyebrow">{{ currentReportRunLabel }}</p><h2>{{ reportTab === 'pipeline' ? '流程报告' : reportTab === 'retrieval' ? '检索报告' : 'Ragas 报告' }}</h2></div><div class="report-header-actions"><span class="count-label">{{ selectedReportRun?.index_version || '--' }}</span><button class="secondary-button danger" :disabled="!reportDeleteCanProceed || reportDeleteLoading" @click="deleteReport"><Trash2 :size="15" />{{ reportDeleteLoading ? '删除中…' : selectedReportRun?.stale ? '删除卡住任务' : selectedReportRun && ['created', 'running', 'cancelling'].includes(selectedReportRun.status) ? '运行中不可删' : '删除报告' }}</button></div></div><div class="report-tabs" role="tablist"><button v-for="tab in (['pipeline','retrieval','ragas'] as ReportTab[])" :key="tab" :class="{ selected: reportTab === tab }" @click="selectReportTab(tab)">{{ tab === 'pipeline' ? '流程报告' : tab === 'retrieval' ? '检索报告' : 'Ragas 报告' }}</button></div><div v-if="reportLoading" class="report-empty"><LoaderCircle class="spin" :size="24" />正在加载 Markdown 报告</div><div v-else-if="!reportMarkdown" class="report-empty"><FileText :size="25" /><strong>请选择一个评测运行</strong><span>完成一次隔离评测后，报告会出现在这里。</span></div><div v-else class="markdown-preview" v-html="renderMarkdown(reportMarkdown)"></div></article></section>
        </template>
        <footer class="page-footer"><span>每次摄取生成新的隔离运行目录</span><span>active pointer 不参与本流程</span><span>索引：{{ ingestion?.index_version || '--' }}</span></footer>
      </main>
    </section>
  </div>
</template>
