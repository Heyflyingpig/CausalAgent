/* RAG评测工作台 - 前端交互逻辑 */
(function () {
  "use strict";

  let currentRunId = null;
  let eventSource = null;
  let latestConfig = null;
  let latestAnalysis = null;
  let selectedReportIndex = 0;
  let reportRefreshTimer = null;
  let pipelineEventKeys = new Set();
  let pipelinePhaseState = { order: [], items: {} };
  let uiLang = localStorage.getItem("ragEvalLang") || "zh";
  let selectedCaseIndex = 0;
  let historyRuns = [];
  let historyPage = 1;
  let historyPagination = { page: 1, page_size: 10, total: 0, total_pages: 1 };
  let diffCandidateRunId = null;
  const HISTORY_PAGE_SIZE = 10;
  const BASE_PAGE_TITLE = document.title || "RAG 评测工作台";
  const RUN_NOTICE_DISMISSED_KEY = "ragEvalDismissedNoticeRunId";

  const METRIC_LABELS = {
    retrieval_recall_at_k: { zh: "检索 Top-K 召回率", en: "Recall@K" },
    retrieval_mrr: { zh: "检索 MRR", en: "MRR" },
    retrieval_hit_rate: { zh: "检索命中率", en: "Hit Rate" },
    ragas_faithfulness: { zh: "忠实性", en: "Faithfulness" },
    ragas_answer_relevancy: { zh: "回答相关性", en: "Answer Relevancy" },
    ragas_context_utilization: { zh: "上下文利用率", en: "Context Utilization" },
    ragas_context_recall: { zh: "上下文召回率", en: "Context Recall" },
    bad_case_trace_count: { zh: "坏例链路数", en: "Bad Case Traces" },
    faithfulness: { zh: "忠实性", en: "Faithfulness" },
    answer_relevancy: { zh: "回答相关性", en: "Answer Relevancy" },
    context_utilization: { zh: "上下文利用率", en: "Context Utilization" },
    context_recall: { zh: "上下文召回率", en: "Context Recall" },
    Recall: { zh: "召回率", en: "Recall" },
    MRR: { zh: "平均倒数排名", en: "MRR" },
    "Gold Docs": { zh: "Gold 文档", en: "Gold Docs" },
    Loss: { zh: "损失原因", en: "Loss" },
  };

  const CONFIG_LABELS = {
    dense_fetch_k: { zh: "稠密检索候选数", en: "Dense fetch K" },
    dense_mmr_k: { zh: "稠密 MMR 保留数", en: "Dense MMR K" },
    sparse_fetch_k: { zh: "稀疏检索候选数", en: "Sparse fetch K" },
    final_top_k: { zh: "最终证据数", en: "Final top K" },
    dense_score_threshold: { zh: "稠密分数阈值", en: "Dense score threshold" },
    final_rerank_threshold: { zh: "最终重排阈值", en: "Final rerank threshold" },
    mmr_lambda: { zh: "MMR 相关性权重", en: "MMR lambda" },
    official_only_when_available: { zh: "有官方语料时仅用官方语料", en: "Official only when available" },
    mode: { zh: "运行模式", en: "Mode" },
    limit: { zh: "样本数上限", en: "Limit" },
    selected_metrics: { zh: "评测指标", en: "Selected metrics" },
    max_contexts: { zh: "最大上下文数", en: "Max contexts" },
    max_context_chars: { zh: "单段上下文最大字符数", en: "Max context chars" },
    max_response_chars: { zh: "回答最大字符数", en: "Max response chars" },
    ragas_timeout: { zh: "Ragas 超时时间", en: "Ragas timeout" },
    ragas_max_workers: { zh: "Ragas 最大并发数", en: "Ragas max workers" },
    ragas_max_retries: { zh: "Ragas 最大重试次数", en: "Ragas max retries" },
    ragas_max_wait: { zh: "Ragas 最长重试等待", en: "Ragas max wait" },
    repeat_count: { zh: "重复评测次数", en: "Repeat count" },
    low_score_threshold: { zh: "低分坏例阈值", en: "Low score threshold" },
    retrieval_recall_low_threshold: { zh: "检索召回低分阈值", en: "Retrieval recall low threshold" },
    retrieval_mrr_low_threshold: { zh: "检索 MRR 低分阈值", en: "Retrieval MRR low threshold" },
    retrieval_hit_rate_min: { zh: "检索命中率下限", en: "Retrieval hit rate min" },
    retrieval_recall_at_k_min: { zh: "检索 Top-K 召回率下限", en: "Retrieval Recall@K min" },
    ragas_faithfulness_min: { zh: "忠实性下限", en: "Faithfulness min" },
    steps: { zh: "Pipeline 步骤", en: "Pipeline steps" },
    run_name: { zh: "Run 名称", en: "Run name" },
  };

  const PARAM_META = {
    dense_fetch_k: {
      meaning: "稠密向量检索阶段先召回的候选 chunk 数。",
      allowed: [1, 200],
      recommended: [10, 80],
      integer: true,
      impact: "调大可提高召回但会变慢，并可能引入更多噪声。",
    },
    dense_mmr_k: {
      meaning: "稠密候选经过 MMR 去重后保留的数量。",
      allowed: [1, 100],
      recommended: [5, 30],
      integer: true,
      impact: "调大可保留更多语义候选；过大会削弱去重效果。",
    },
    sparse_fetch_k: {
      meaning: "关键词/稀疏检索阶段先召回的候选 chunk 数。",
      allowed: [0, 200],
      recommended: [5, 50],
      integer: true,
      impact: "调大有利于补足关键词命中；过大会增加融合排序噪声。",
    },
    final_top_k: {
      meaning: "最终送入回答或评测的证据数量。",
      allowed: [1, 20],
      recommended: [3, 8],
      integer: true,
      impact: "调大可提升上下文覆盖，但可能降低忠实性和上下文利用率。",
    },
    dense_score_threshold: {
      meaning: "稠密检索候选的最低分数阈值。",
      allowed: [0, 1],
      recommended: [0.3, 0.7],
      impact: "调高会过滤弱相关候选；过高可能漏召回。",
    },
    final_rerank_threshold: {
      meaning: "融合重排后进入最终证据的最低分数阈值。",
      allowed: [0, 1],
      recommended: [0, 0.4],
      impact: "调高可减少噪声证据；过高会减少可用上下文。",
    },
    mmr_lambda: {
      meaning: "MMR 中相关性相对多样性的权重。",
      allowed: [0, 1],
      recommended: [0.5, 0.85],
      impact: "越大越偏相关性，越小越偏多样性。",
    },
    official_only_when_available: {
      meaning: "当存在官方语料时，是否只使用官方语料。",
      options: "true / false",
      impact: "开启可提高来源一致性；关闭可扩大召回范围。",
    },
    mode: {
      meaning: "检索评测运行模式。",
      options: "single / sweep",
      impact: "single 用于当前配置评测；sweep 用于批量比较候选配置。",
    },
    limit: {
      meaning: "本次评测最多处理的样本数；null 表示按 profile 默认或全量。",
      allowed: [1, 1000],
      recommended: [30, 100],
      integer: true,
      allowNull: true,
      impact: "调大结果更稳定但耗时和 API 成本更高。",
    },
    selected_metrics: {
      meaning: "Ragas 需要计算的指标列表。",
      options: "faithfulness, answer_relevancy, context_utilization, context_recall",
      impact: "指标越多，评测越全面，但 API 调用和耗时会增加。",
    },
    max_contexts: {
      meaning: "构造 Ragas 样本时最多送入的上下文段数。",
      allowed: [1, 12],
      recommended: [4, 8],
      integer: true,
      impact: "调大可提升 context_recall；过大会增加噪声和评测成本。",
    },
    max_context_chars: {
      meaning: "单段上下文送入 Ragas 的最大字符数。",
      allowed: [300, 4000],
      recommended: [1200, 2000],
      integer: true,
      impact: "调大可保留更多证据细节；过大会拖慢评测。",
    },
    max_response_chars: {
      meaning: "送入 Ragas 的回答最大字符数。",
      allowed: [200, 3000],
      recommended: [800, 1500],
      integer: true,
      impact: "调大可保留完整答案；过大通常只增加评测成本。",
    },
    ragas_timeout: {
      meaning: "单个 Ragas 任务允许等待的最长时间，单位秒。",
      officialDefault: "180 秒",
      allowed: [60, 3600],
      recommended: [300, 900],
      integer: true,
      impact: "调大可减少 timeout 失败；过大会让异常任务拖慢整轮评测。",
    },
    ragas_max_workers: {
      meaning: "Ragas judge 并发 worker 数。",
      officialDefault: "16",
      allowed: [1, 16],
      recommended: [1, 8],
      integer: true,
      impact: "调大可加速评测，但更容易触发 API 限流。",
    },
    ragas_max_retries: {
      meaning: "Ragas 单任务失败后的最大重试次数。",
      officialDefault: "10",
      allowed: [0, 10],
      recommended: [2, 5],
      integer: true,
      impact: "调大可提高限流场景成功率，但会拉长失败等待。",
    },
    ragas_max_wait: {
      meaning: "Ragas 重试退避的最长等待时间，单位秒。",
      officialDefault: "60 秒",
      allowed: [1, 300],
      recommended: [10, 60],
      integer: true,
      impact: "调大可降低限流失败，但会拉长整体评测时间。",
    },
    repeat_count: {
      meaning: "同一配置重复评测次数。",
      allowed: [1, 10],
      recommended: [1, 3],
      integer: true,
      impact: "调大可观察 judge 波动，但 API 成本成倍增加。",
    },
    low_score_threshold: {
      meaning: "Ragas 分数低于该值时标记为低分坏例。",
      allowed: [0, 1],
      recommended: [0.4, 0.7],
      impact: "调高会发现更多可疑样本；过高会把边界样本也标为坏例。",
    },
    retrieval_recall_low_threshold: {
      meaning: "跨指标坏例中判断检索召回偏低的阈值。",
      allowed: [0, 1],
      recommended: [0.5, 0.8],
      impact: "调高会更严格地暴露召回问题。",
    },
    retrieval_mrr_low_threshold: {
      meaning: "跨指标坏例中判断检索排序偏低的 MRR 阈值。",
      allowed: [0, 1],
      recommended: [0.3, 0.7],
      impact: "调高会更严格地暴露排序问题。",
    },
    retrieval_hit_rate_min: {
      meaning: "summary 阈值检查中的检索命中率下限。",
      allowed: [0, 1],
      recommended: [0.7, 0.95],
      impact: "调高会让回归检查更严格。",
    },
    retrieval_recall_at_k_min: {
      meaning: "summary 阈值检查中的 Top-K 召回率下限。",
      allowed: [0, 1],
      recommended: [0.7, 0.95],
      impact: "调高会让召回回归检查更严格。",
    },
    ragas_faithfulness_min: {
      meaning: "summary 阈值检查中的忠实性下限。",
      allowed: [0, 1],
      recommended: [0.6, 0.9],
      impact: "调高会更严格地拦截不忠实答案。",
    },
  };

  document.addEventListener("DOMContentLoaded", () => {
    setupTabNav();
    setupButtons();
    refreshStatus();
  });

  function setupTabNav() {
    document.querySelectorAll(".tabnav-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const tabId = btn.dataset.tab;
        document.querySelectorAll(".tabnav-btn").forEach(item => item.classList.remove("active"));
        document.querySelectorAll(".tab-panel").forEach(panel => panel.classList.remove("active"));
        btn.classList.add("active");
        document.getElementById("tab-" + tabId).classList.add("active");
        if (tabId === "overview") refreshStatus();
        if (tabId === "config") loadConfig();
        if (tabId === "pipeline") {
          ensurePipelineSteps();
          loadPipelineState();
        }
        if (tabId === "analysis") loadAnalysis();
        if (tabId === "reports") loadReports();
        if (tabId === "history") loadHistory();
      });
    });
  }

  function setupButtons() {
    const refreshStatusButton = document.getElementById("btn-refresh-status");
    refreshStatusButton.addEventListener("click", () => {
      triggerRefreshImpact(refreshStatusButton);
      refreshStatus();
    });
    document.getElementById("btn-toggle-lang").addEventListener("click", toggleLanguage);
    const refreshAnalysisButton = document.getElementById("btn-refresh-analysis");
    refreshAnalysisButton.addEventListener("click", () => {
      triggerRefreshImpact(refreshAnalysisButton);
      loadAnalysis();
    });
    document.getElementById("btn-save-config").addEventListener("click", saveConfig);
    document.getElementById("btn-publish-production-config").addEventListener("click", publishProductionConfig);
    document.getElementById("btn-run-pipeline").addEventListener("click", runPipeline);
    document.getElementById("btn-cancel-pipeline").addEventListener("click", cancelPipeline);
    const refreshReportsButton = document.getElementById("btn-refresh-reports");
    refreshReportsButton.addEventListener("click", () => {
      triggerRefreshImpact(refreshReportsButton);
      loadReports();
    });
    document.getElementById("btn-save-report").addEventListener("click", saveSelectedReport);
    setupRunNoticeButtons();
    setupHistoryEvents();
    setupInteractionEffects();
    updateLanguageButton();
  }

  function setupInteractionEffects() {
    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (window.matchMedia && !window.matchMedia("(pointer: fine)").matches) return;
    setupCursorTrail();
    document.addEventListener("pointerdown", event => {
      if (event.button !== 0 || event.pointerType === "touch") return;
      spawnClickBurst(event.clientX, event.clientY, false);
    }, { passive: true });
  }

  function ensureInteractionLayer() {
    let layer = document.getElementById("interaction-layer");
    if (layer) return layer;
    layer = document.createElement("div");
    layer.id = "interaction-layer";
    layer.className = "interaction-layer";
    document.body.appendChild(layer);
    return layer;
  }

  function setupCursorTrail() {
    const layer = ensureInteractionLayer();
    const dots = Array.from({ length: 7 }, (_, index) => {
      const dot = document.createElement("span");
      dot.className = "cursor-trail-dot";
      dot.style.setProperty("--trail-scale", String(1 - index * 0.08));
      dot.style.opacity = "0";
      layer.appendChild(dot);
      return { el: dot, x: 0, y: 0 };
    });
    let targetX = 0;
    let targetY = 0;
    let active = false;
    document.addEventListener("pointermove", event => {
      if (event.pointerType === "touch") return;
      targetX = event.clientX;
      targetY = event.clientY;
      active = true;
    }, { passive: true });
    function tick() {
      let followX = targetX;
      let followY = targetY;
      dots.forEach((dot, index) => {
        dot.x += (followX - dot.x) * (0.34 - index * 0.025);
        dot.y += (followY - dot.y) * (0.34 - index * 0.025);
        dot.el.style.opacity = active ? String(Math.max(0.12, 0.42 - index * 0.045)) : "0";
        dot.el.style.transform = "translate3d(" + dot.x + "px, " + dot.y + "px, 0) translate(-50%, -50%) scale(var(--trail-scale))";
        followX = dot.x;
        followY = dot.y;
      });
      requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }

  function spawnClickBurst(x, y, heavy) {
    const layer = ensureInteractionLayer();
    const count = heavy ? 14 : 9;
    for (let i = 0; i < count; i++) {
      const spark = document.createElement("span");
      const angle = (Math.PI * 2 * i) / count + Math.random() * 0.35;
      const distance = (heavy ? 34 : 22) + Math.random() * (heavy ? 28 : 18);
      spark.className = heavy ? "click-spark heavy" : "click-spark";
      spark.style.left = x + "px";
      spark.style.top = y + "px";
      spark.style.setProperty("--dx", Math.cos(angle) * distance + "px");
      spark.style.setProperty("--dy", Math.sin(angle) * distance + "px");
      spark.style.setProperty("--spark-delay", (Math.random() * 35) + "ms");
      layer.appendChild(spark);
      window.setTimeout(() => spark.remove(), heavy ? 760 : 620);
    }
  }

  function triggerRefreshImpact(button) {
    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const rect = button.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    button.classList.remove("refresh-impact");
    document.body.classList.remove("refresh-impact-frame");
    void button.offsetWidth;
    button.classList.add("refresh-impact");
    document.body.classList.add("refresh-impact-frame");
    spawnRefreshRing(x, y);
    spawnClickBurst(x, y, true);
    window.setTimeout(() => {
      button.classList.remove("refresh-impact");
      document.body.classList.remove("refresh-impact-frame");
    }, 420);
  }

  function spawnRefreshRing(x, y) {
    const ring = document.createElement("span");
    ring.className = "refresh-impact-ring";
    ring.style.left = x + "px";
    ring.style.top = y + "px";
    ensureInteractionLayer().appendChild(ring);
    window.setTimeout(() => ring.remove(), 520);
  }

  function setupRunNoticeButtons() {
    document.getElementById("btn-run-notice-reports").addEventListener("click", () => {
      restorePageTitle();
      document.querySelector('[data-tab="reports"]').click();
    });
    document.getElementById("btn-run-notice-analysis").addEventListener("click", () => {
      restorePageTitle();
      document.querySelector('[data-tab="analysis"]').click();
    });
    document.getElementById("btn-run-notice-dismiss").addEventListener("click", () => {
      hideRunNotice(true);
      restorePageTitle();
    });
  }

  function setupHistoryEvents() {
    const historyBody = document.getElementById("history-tbody");
    if (historyBody) {
      historyBody.addEventListener("click", event => {
        const button = event.target.closest("[data-history-action]");
        if (!button || !historyBody.contains(button)) return;
        const runId = button.dataset.runId || "";
        if (button.dataset.historyAction === "detail") showRunDetail(runId);
        if (button.dataset.historyAction === "reports") showRunReports(runId);
        if (button.dataset.historyAction === "delete") deleteRun(runId);
      });
    }

    const pagination = document.getElementById("history-pagination");
    if (pagination) {
      pagination.addEventListener("click", event => {
        const button = event.target.closest("[data-history-page]");
        if (!button || button.disabled || !pagination.contains(button)) return;
        loadHistory(Number(button.dataset.historyPage || 1));
      });
    }

    const closeButton = document.getElementById("btn-close-run-detail");
    if (closeButton) closeButton.addEventListener("click", closeRunDetail);
  }

  async function apiGet(path) {
    const res = await fetch(path);
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  }

  async function apiPut(path, body) {
    const res = await fetch(path, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  }

  async function apiPost(path, body) {
    const options = { method: "POST" };
    if (body) {
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(body);
    }
    const res = await fetch(path, options);
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  }

  async function apiDelete(path) {
    const res = await fetch(path, { method: "DELETE" });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(payload.error || ("HTTP " + res.status));
    return payload;
  }

  async function refreshStatus() {
    try {
      const statusResp = await apiGet("/api/rag_eval/status");
      if (!statusResp.success) throw new Error(statusResp.error || "status failed");

      const [resultsResp, analysisResp] = await Promise.allSettled([
        apiGet("/api/rag_eval/results/latest"),
        apiGet("/api/rag_eval/analysis/latest"),
      ]);

      const latestResults = resultsResp.status === "fulfilled" && resultsResp.value.success
        ? (resultsResp.value.data || {})
        : {};
      latestAnalysis = analysisResp.status === "fulfilled" && analysisResp.value.success
        ? analysisResp.value.data
        : null;
      renderOverview(statusResp.data, latestResults, latestAnalysis);
      setConnectionStatus("online", "已连接");
      await loadPipelineState({ silent: true });
    } catch (err) {
      setConnectionStatus("offline", "连接失败");
      renderEmptyOverview(err.message);
    }
  }

  function renderOverview(status, results, analysis) {
    const run = status.latest_run || {};
    const metrics = run.key_metrics || {};
    const trace = results.trace || {};
    renderMetricStrip([
      ["retrieval_recall_at_k", metrics.retrieval_recall_at_k, "检索召回"],
      ["retrieval_mrr", metrics.retrieval_mrr, "排序质量"],
      ["ragas_faithfulness", metrics.ragas_faithfulness, "Ragas"],
      ["bad_case_trace_count", trace.bad_case_trace_count, "坏例链路"],
    ]);

    const bm = status.benchmark || {};
    document.getElementById("benchmark-name").textContent = bm.name || "--";
    document.getElementById("benchmark-state").textContent = bm.dataset_exists ? "ready" : "missing";
    setKVs("benchmark-info", [
      ["数据集路径", bm.dataset_path || "--"],
      ["样本数", bm.sample_count || "--"],
      ["更新时间", status.last_updated || "--"],
    ]);

    const vdb = status.vector_db || {};
    document.getElementById("vectordb-title").textContent = vdb.collection_name || "Chroma";
    document.getElementById("vectordb-state").textContent = vdb.exists ? "ready" : "missing";
    setKVs("vectordb-info", [
      ["目录", vdb.path || "--"],
      ["文档数", vdb.doc_count != null ? vdb.doc_count : "--"],
      ["大小", vdb.size_mb != null ? vdb.size_mb + " MB" : "--"],
      ["前缀", formatObject(vdb.prefix_counts || {})],
    ]);
    renderModelRuntime(status.models || {});

    document.getElementById("latest-run-title").textContent = run.display_name || run.run_id || "暂无评测结果";
    document.getElementById("latest-run-status").textContent = run.status_reason
      ? (run.status || "--") + " · " + run.status_reason
      : (run.status || "--");
    document.getElementById("latest-run-status").className = "state-tag " + (run.status || "");
    renderThresholdChecks(run.threshold_checks || []);
    renderDiagnosis("overview-diagnosis", analysis ? analysis.developer_diagnosis : null);

    if (analysis) {
      renderAnalysis(analysis);
      renderReports(analysis);
    }
  }

  function renderEmptyOverview(message) {
    renderMetricStrip([
      ["Recall@K", null, "连接失败"],
      ["MRR", null, message],
      ["Faithfulness", null, ""],
      ["Bad Case Traces", null, ""],
    ]);
  }

  function renderMetricStrip(items) {
    const el = document.getElementById("overview-metrics");
    el.innerHTML = items.map(([key, value, note]) => (
      '<div class="metric-card' + (Number(value) >= 0.9 ? " metric-good" : "") + '">' +
        '<div class="metric-label">' + escHtml(metricLabel(key)) + '</div>' +
        '<div class="metric-value">' + fmtNum(value) + '</div>' +
        '<div class="metric-note">' + escHtml(note || "") + '</div>' +
      '</div>'
    )).join("");
  }

  function renderModelRuntime(models) {
    const el = document.getElementById("model-runtime-grid");
    if (!el) return;
    const items = [
      ["Embedding", models.embedding || {}],
      ["Answer", models.answer || {}],
      ["Judge", models.judge || {}],
    ];
    el.innerHTML = items.map(([title, item]) => renderModelRuntimeCard(title, item)).join("");
  }

  function renderModelRuntimeCard(title, item) {
    const status = item.status || "unknown";
    const rows = [
      ["模式", item.mode || item.provider || "--"],
      ["模型", item.model || "--"],
      ["端点", item.endpoint || "--"],
      ["API Key", item.api_key_configured == null ? "--" : (item.api_key_configured ? "已配置" : "未配置")],
    ];
    if (item.path) rows.push(["本地路径", item.path]);
    if (item.path_exists != null) rows.push(["路径状态", item.path_exists ? "存在" : "不存在"]);
    if (item.collection_name) rows.push(["Collection", item.collection_name]);
    if (item.judge_profile) rows.push(["Judge profile", item.judge_profile]);
    if (item.purpose) rows.push(["用途", item.purpose]);
    return [
      '<article class="model-runtime-card ' + escAttr(status) + '">',
        '<div class="model-runtime-head">',
          '<div><div class="metric-label">' + escHtml(title) + '</div><h3>' + escHtml(item.model || "--") + '</h3></div>',
          '<span class="state-tag ' + escAttr(status) + '">' + escHtml(modelStatusText(status)) + '</span>',
        '</div>',
        '<div class="kv-list compact-kv">',
          rows.map(([key, value]) => '<div class="kv-row"><div class="kv-key">' + escHtml(key) + '</div><div class="kv-val">' + escHtml(String(value || "--")) + '</div></div>').join(""),
        '</div>',
        '<div class="model-runtime-message">' + escHtml(item.message || "") + '</div>',
      '</article>',
    ].join("");
  }

  function modelStatusText(status) {
    if (status === "ready") return "ready";
    if (status === "missing") return "missing";
    if (status === "warning") return "warning";
    return "unknown";
  }

  function renderThresholdChecks(checks) {
    const el = document.getElementById("threshold-checks");
    if (!checks.length) {
      el.innerHTML = '<div class="empty-state">暂无阈值检查</div>';
      return;
    }
    el.innerHTML = checks.map(item => (
      '<div class="check-card ' + escAttr(item.status || "") + '">' +
        '<div class="metric-label">' + escHtml(metricLabel(item.name || item.threshold_name || "threshold")) + '</div>' +
        '<div class="metric-value">' + fmtNum(item.actual) + '</div>' +
        '<div class="metric-note">阈值 ' + fmtNum(item.threshold) + " · " + escHtml(item.status || "") + '</div>' +
      '</div>'
    )).join("");
  }

  function setKVs(containerId, pairs) {
    document.getElementById(containerId).innerHTML = pairs.map(([key, value]) => (
      '<div class="kv-row"><div class="kv-key">' + escHtml(key) + '</div><div class="kv-val">' + escHtml(String(value)) + '</div></div>'
    )).join("");
  }

  async function loadConfig() {
    try {
      const resp = await apiGet("/api/rag_eval/config");
      if (!resp.success) throw new Error(resp.error || "config failed");
      latestConfig = resp.data;
      renderConfig(resp.data);
      await loadProductionConfig();
    } catch (err) {
      document.getElementById("config-save-msg").textContent = "配置加载失败: " + err.message;
    }
  }

  function renderConfig(data) {
    updateStaticConfigLabels();
    const profiles = data.retrieval_profiles || {};
    const profileLimits = data.retrieval_profile_limits || {};
    const activeProfile = data.active_retrieval_profile || Object.keys(profiles)[0] || "";
    const profileSelect = document.getElementById("cfg-active-retrieval-profile");
    profileSelect.innerHTML = Object.keys(profiles).map(name => (
      '<option value="' + escAttr(name) + '"' + (name === activeProfile ? " selected" : "") + ">" + escHtml(name) + "</option>"
    )).join("");
    profileSelect.onchange = () => {
      const selectedProfile = profileSelect.value;
      renderFormRows("cfg-retrieval-profiles", profiles[selectedProfile] || {}, "retrieval_profiles." + selectedProfile + ".");
      if (Object.prototype.hasOwnProperty.call(profileLimits, selectedProfile)) {
        setValue("cfg-retrieval-limit", fmtNullable(profileLimits[selectedProfile]));
      }
    };
    renderFormRows("cfg-retrieval-profiles", profiles[activeProfile] || {}, "retrieval_profiles." + activeProfile + ".");

    const retrievalEval = data.retrieval_eval || {};
    setValue("cfg-retrieval-mode", retrievalEval.mode || "single");
    setValue("cfg-retrieval-limit", fmtNullable(retrievalEval.limit));

    const ragas = data.ragas || {};
    const ragasSelect = document.getElementById("cfg-ragas-active-profile");
    ragasSelect.innerHTML = (ragas.available_profiles || []).map(name => (
      '<option value="' + escAttr(name) + '"' + (name === ragas.active_profile ? " selected" : "") + ">" + escHtml(name) + "</option>"
    )).join("");
    ragasSelect.onchange = () => {
      const profile = ((ragas.profiles || {})[ragasSelect.value]) || {};
      renderRagasParams({ ...ragas, ...profile });
    };
    renderRagasParams(ragas);
    const pipeline = data.pipeline || {};
    renderStepLists(pipeline.steps || []);
    renderFormRows("cfg-pipeline-thresholds", pipeline.thresholds || {}, "pipeline.thresholds.");
  }

  function renderRagasParams(ragas) {
    renderFormRows("cfg-ragas-params", pick(ragas, [
      "limit", "selected_metrics", "max_contexts", "max_context_chars", "max_response_chars",
      "ragas_timeout", "ragas_max_workers", "ragas_max_retries", "ragas_max_wait",
      "repeat_count", "low_score_threshold",
      "retrieval_recall_low_threshold", "retrieval_mrr_low_threshold",
    ]), "ragas.");
  }

  async function ensurePipelineSteps() {
    if (!latestConfig) {
      await loadConfig();
    } else {
      renderStepLists((latestConfig.pipeline || {}).steps || []);
    }
  }

  async function renderStepLists(steps) {
    const descriptions = await getStepDescriptions();
    const fallback = ["validate_datasets", "retrieval_eval", "ragas_eval", "summary"];
    const selected = steps.length ? steps : fallback;
    renderSteps("cfg-pipeline-steps", selected, descriptions);
    renderSteps("step-checklist", selected, descriptions);
    document.getElementById("step-desc-loading").style.display = "none";
  }

  async function getStepDescriptions() {
    try {
      const resp = await apiGet("/api/rag_eval/steps");
      return resp.success ? (resp.data || {}) : {};
    } catch (_err) {
      return {};
    }
  }

  function renderSteps(containerId, steps, descriptions) {
    document.getElementById(containerId).innerHTML = steps.map(step => (
      '<div class="step-row">' +
        '<label><input type="checkbox" value="' + escAttr(step) + '" checked> <span>' + escHtml(step) + '</span></label>' +
        '<span class="step-tag">' + escHtml(descriptions[step] || "") + '</span>' +
      '</div>'
    )).join("");
  }

  function renderFormRows(containerId, values, prefix) {
    document.getElementById(containerId).innerHTML = Object.entries(values).map(([key, value]) => {
      const shown = Array.isArray(value) ? value.join(", ") : fmtNullable(value);
      return '<label class="field">' + renderConfigFieldTitle(key) +
        '<input type="text" value="' + escAttr(shown) + '" data-key="' + escAttr(prefix + key) + '">' +
        '</label>';
    }).join("");
  }

  function renderConfigFieldTitle(key) {
    const meta = paramMeta(key);
    if (!meta) return '<span class="field-title">' + escHtml(configLabel(key)) + '</span>';
    return '<span class="field-title">' +
      '<span>' + escHtml(configLabel(key)) + '</span>' +
      '<span class="param-help" tabindex="0" aria-label="' + escAttr(configLabel(key) + " 参数说明") + '">*</span>' +
      '<span class="param-tooltip" role="tooltip">' + renderParamTooltip(meta) + '</span>' +
    '</span>';
  }

  function renderParamTooltip(meta) {
    const parts = ['<strong>含义</strong><span>' + escHtml(meta.meaning || "") + '</span>'];
    if (meta.officialDefault) parts.push('<strong>官方默认值</strong><span>' + escHtml(meta.officialDefault) + '</span>');
    if (meta.recommended) parts.push('<strong>建议范围</strong><span>' + escHtml(formatRange(meta.recommended, meta.unit) + "；超出仍可保存，仅提示复核") + '</span>');
    if (meta.allowed) parts.push('<strong>工作台范围</strong><span>' + escHtml(formatRange(meta.allowed, meta.unit) + "；超出会拦截保存") + '</span>');
    if (meta.options) parts.push('<strong>可选值</strong><span>' + escHtml(meta.options) + '</span>');
    if (meta.impact) parts.push('<strong>影响</strong><span>' + escHtml(meta.impact) + '</span>');
    return parts.join("");
  }

  async function saveConfig() {
    const msg = document.getElementById("config-save-msg");
    msg.className = "inline-message";
    msg.textContent = "保存中...";
    try {
      const validation = validateConfigInputs();
      if (validation.errors.length) {
        msg.className = "inline-message error";
        msg.innerHTML = "保存失败。" + renderNoticeList("需要修正", validation.errors);
        return;
      }
      const overrides = collectConfigOverrides();
      const resp = await apiPut("/api/rag_eval/config", overrides);
      if (!resp.success) throw new Error(resp.error || "save failed");
      msg.className = validation.warnings.length ? "inline-message warning" : "inline-message";
      msg.innerHTML = "配置已保存到当前进程内存。" + renderNoticeList("建议复核", validation.warnings);
      await loadConfig();
    } catch (err) {
      msg.className = "inline-message error";
      msg.textContent = "保存失败: " + err.message;
    }
  }

  async function loadProductionConfig() {
    try {
      const resp = await apiGet("/api/rag_eval/production-config");
      if (!resp.success) throw new Error(resp.error || "production config failed");
      renderProductionConfig(resp.data || {});
    } catch (err) {
      document.getElementById("production-config-view").innerHTML = '<div class="empty-state">正式配置加载失败: ' + escHtml(err.message) + '</div>';
    }
  }

  async function publishProductionConfig() {
    const msg = document.getElementById("production-config-msg");
    const btn = document.getElementById("btn-publish-production-config");
    msg.textContent = "发布中...";
    btn.disabled = true;
    try {
      if (!latestConfig) await loadConfig();
      const validation = validateConfigInputs();
      if (validation.errors.length) {
        throw new Error("配置校验失败：" + validation.errors.join("；"));
      }
      const configOverrides = collectConfigOverrides();
      const saveResp = await apiPut("/api/rag_eval/config", configOverrides);
      if (!saveResp.success) throw new Error(saveResp.error || "save config before publish failed");
      const expectedConfig = productionConfigFromOverrides(configOverrides);
      const payload = {
        source_run_id: currentRunId || (latestAnalysis || {}).run_id || "",
        note: "published from rag eval workbench",
        config_overrides: configOverrides,
      };
      const resp = await apiPost("/api/rag_eval/production-config/publish", payload);
      if (!resp.success) throw new Error(resp.error || "publish failed");
      const mismatches = diffConfigValues(expectedConfig, (resp.data || {}).config || {});
      renderProductionConfig(resp.data || {});
      renderProductionPublishMessage(msg, mismatches, validation.warnings);
    } catch (err) {
      msg.textContent = "发布失败: " + err.message;
    } finally {
      btn.disabled = false;
    }
  }

  function productionConfigFromOverrides(overrides) {
    const profileName = overrides.active_retrieval_profile || "";
    const profile = ((overrides.retrieval_profiles || {})[profileName]) || {};
    return pick(profile, [
      "dense_fetch_k", "dense_mmr_k", "sparse_fetch_k", "final_top_k",
      "dense_score_threshold", "final_rerank_threshold", "mmr_lambda",
      "official_only_when_available",
    ]);
  }

  function diffConfigValues(expected, actual) {
    return Object.entries(expected).filter(([key, value]) => String(actual[key]) !== String(value)).map(([key, value]) => ({
      key,
      expected: value,
      actual: actual[key],
    }));
  }

  function renderProductionPublishMessage(msg, mismatches, warnings) {
    msg.className = mismatches.length ? "inline-message error" : (warnings.length ? "inline-message warning" : "inline-message");
    const warningHtml = renderNoticeList("建议复核", warnings);
    const mismatchHtml = mismatches.length
      ? '<div class="publish-warning-list"><strong>发布校验未通过</strong><ul>' + mismatches.map(item => (
        '<li>' + escHtml(configLabel(item.key)) + ': 期望 ' + escHtml(fmtNullable(item.expected)) + '，实际 ' + escHtml(fmtNullable(item.actual)) + '</li>'
      )).join("") + '</ul><div>请确认后端服务已重启并加载最新代码。</div></div>'
      : "";
    msg.innerHTML = (mismatches.length
      ? "发布请求已返回，但正式配置与当前表单不一致。"
      : "已发布当前表单检索配置到正式 RAG 配置文件；独立 worker 会在后续查询时读取。"
    ) + warningHtml + mismatchHtml;
  }

  function renderNoticeList(title, items) {
    if (!items || !items.length) return "";
    return '<div class="publish-warning-list"><strong>' + escHtml(title) + '</strong><ul>' +
      items.map(item => '<li>' + escHtml(item) + '</li>').join("") +
      '</ul></div>';
  }

  function renderProductionConfig(data) {
    const metadata = data.metadata || {};
    const config = data.config || {};
    document.getElementById("production-config-view").className = "production-config-view";
    document.getElementById("production-config-view").innerHTML = [
      '<div class="run-overview-grid">',
        renderProductionInfo("来源", data.source || "--"),
        renderProductionInfo("配置文件", data.path || "--"),
        renderProductionInfo("发布时间", metadata.published_at || "--"),
        renderProductionInfo("来源 Run", metadata.source_run_id || "--"),
      '</div>',
      renderProductionConfigSummary(config, metadata),
      '<div class="table-wrap"><table class="data-table compact-table"><thead><tr><th>参数</th><th>值</th></tr></thead><tbody>',
        Object.entries(config).map(([key, value]) => (
          '<tr><td>' + escHtml(configLabel(key)) + '</td><td class="mono">' + escHtml(fmtNullable(value)) + '</td></tr>'
        )).join(""),
      '</tbody></table></div>',
    ].join("");
  }

  function renderProductionConfigSummary(config, metadata) {
    const rows = [
      ["Retrieval profile", metadata.active_retrieval_profile || "--"],
      ["Dense fetch K", config.dense_fetch_k],
      ["Dense MMR K", config.dense_mmr_k],
      ["Sparse fetch K", config.sparse_fetch_k],
      ["Final top K", config.final_top_k],
      ["Dense threshold", config.dense_score_threshold],
      ["Rerank threshold", config.final_rerank_threshold],
      ["MMR lambda", config.mmr_lambda],
      ["Max evidence chars", config.max_evidence_chars],
    ];
    return '<div class="production-config-summary">' +
      '<div class="run-config-preview-title">当前正式 RAG 关键参数</div>' +
      '<div class="run-config-preview-grid">' +
        rows.map(([label, value]) => (
          '<div class="run-config-preview-item"><span>' + escHtml(label) + '</span><span>' + escHtml(fmtNullable(value)) + '</span></div>'
        )).join("") +
      '</div>' +
    '</div>';
  }

  function renderProductionInfo(label, value) {
    return '<div class="run-overview-item">' +
      '<div class="metric-label">' + escHtml(label) + '</div>' +
      '<div class="run-overview-value">' + escHtml(value || "--") + '</div>' +
    '</div>';
  }

  function collectConfigOverrides() {
    const overrides = { retrieval_profiles: {}, retrieval_eval: {}, ragas: {}, pipeline: {} };
    document.querySelectorAll("#tab-config input[type=text]").forEach(input => {
      const key = input.dataset.key;
      if (!key) return;
      setNested(overrides, key, parseConfigValue(key, input.value.trim()));
    });
    overrides.active_retrieval_profile = document.getElementById("cfg-active-retrieval-profile").value;
    overrides.active_ragas_profile = document.getElementById("cfg-ragas-active-profile").value;
    overrides.retrieval_eval.mode = document.getElementById("cfg-retrieval-mode").value;
    overrides.retrieval_eval.limit = parseConfigValue("retrieval_eval.limit", document.getElementById("cfg-retrieval-limit").value.trim());
    overrides.pipeline.steps = Array.from(document.querySelectorAll("#cfg-pipeline-steps input[type=checkbox]:checked")).map(input => input.value);
    return overrides;
  }

  function renderRunConfigPreview(overrides, warnings) {
    const el = document.getElementById("pipeline-run-config-preview");
    if (!el) return;
    const retrievalProfile = overrides.active_retrieval_profile || "";
    const retrievalCfg = ((overrides.retrieval_profiles || {})[retrievalProfile]) || {};
    const ragasProfile = overrides.active_ragas_profile || "";
    const ragasCfg = overrides.ragas || {};
    const rows = [
      ["Retrieval profile", retrievalProfile],
      ["Ragas profile", ragasProfile],
      ["Limit", overrides.retrieval_eval ? overrides.retrieval_eval.limit : ""],
      ["Ragas workers", ragasCfg.ragas_max_workers],
      ["Dense fetch K", retrievalCfg.dense_fetch_k],
      ["Dense MMR K", retrievalCfg.dense_mmr_k],
      ["Sparse fetch K", retrievalCfg.sparse_fetch_k],
      ["Final top K", retrievalCfg.final_top_k],
      ["Dense threshold", retrievalCfg.dense_score_threshold],
      ["Rerank threshold", retrievalCfg.final_rerank_threshold],
      ["MMR lambda", retrievalCfg.mmr_lambda],
      ["Steps", ((overrides.pipeline || {}).steps || []).join(", ")],
    ];
    el.className = "run-config-preview";
    el.innerHTML = [
      '<div class="run-config-preview-title">本次运行配置预览</div>',
      '<div class="run-config-preview-grid">',
        rows.map(([label, value]) => (
          '<div class="run-config-preview-item"><span>' + escHtml(label) + '</span><span>' + escHtml(fmtNullable(value)) + '</span></div>'
        )).join(""),
      '</div>',
      '<div class="run-config-preview-note">' +
        escHtml(warnings && warnings.length ? "存在建议范围外参数：" + warnings.join("；") : "运行会直接提交当前表单参数，并写入本次 run 的 config_snapshot。") +
      '</div>',
    ].join("");
  }

  function validateConfigInputs() {
    const errors = [];
    const warnings = [];
    const seenMessages = new Set();
    document.querySelectorAll("#tab-config .field input[type=text][data-key]").forEach(input => {
      input.classList.remove("input-error", "input-warning");
      const key = input.dataset.key;
      const meta = paramMeta(key);
      if (!key || !meta || !meta.allowed) return;
      const raw = input.value.trim();
      if ((raw === "" || raw === "null") && meta.allowNull) return;
      const value = Number(raw);
      const label = configLabel(key);
      if (raw === "" || Number.isNaN(value)) {
        pushUnique(errors, seenMessages, label + " 必须填写数字" + (meta.allowNull ? "或 null" : ""));
        input.classList.add("input-error");
        return;
      }
      if (meta.integer && !Number.isInteger(value)) {
        pushUnique(errors, seenMessages, label + " 必须是整数");
        input.classList.add("input-error");
        return;
      }
      if (value < meta.allowed[0] || value > meta.allowed[1]) {
        pushUnique(errors, seenMessages, label + " 超出工作台范围 " + formatRange(meta.allowed, meta.unit));
        input.classList.add("input-error");
        return;
      }
      if (meta.recommended && (value < meta.recommended[0] || value > meta.recommended[1])) {
        pushUnique(warnings, seenMessages, label + " 不在建议范围 " + formatRange(meta.recommended, meta.unit) + " 内");
        input.classList.add("input-warning");
      }
    });
    return { errors, warnings };
  }

  function pushUnique(items, seen, message) {
    if (seen.has(message)) return;
    seen.add(message);
    items.push(message);
  }

  function parseConfigValue(key, value) {
    if (value === "" || value === "null") return null;
    if (value === "true") return true;
    if (value === "false") return false;
    if (key.endsWith("selected_metrics") || key.endsWith("steps")) {
      return value.split(",").map(item => item.trim()).filter(Boolean);
    }
    return Number.isNaN(Number(value)) ? value : Number(value);
  }

  function setNested(obj, path, value) {
    const parts = path.split(".");
    let current = obj;
    for (let i = 0; i < parts.length - 1; i++) {
      if (!current[parts[i]]) current[parts[i]] = {};
      current = current[parts[i]];
    }
    current[parts[parts.length - 1]] = value;
  }

  async function runPipeline() {
    const btn = document.getElementById("btn-run-pipeline");
    btn.disabled = true;
    btn.textContent = "启动中...";
    clearLog();
    hideRunNotice(false);
    sessionStorage.removeItem(RUN_NOTICE_DISMISSED_KEY);
    setPageTitle("运行中");
    resetPipelineProgress(getSelectedPipelineSteps());
    try {
      if (!latestConfig) await loadConfig();
      const validation = validateConfigInputs();
      if (validation.errors.length) {
        throw new Error("配置校验失败：" + validation.errors.join("；"));
      }
      const overrides = collectConfigOverrides();
      const runName = document.getElementById("pipeline-run-name").value.trim() || "active_benchmark_full_pipeline";
      overrides.pipeline.run_name = runName;
      renderRunConfigPreview(overrides, validation.warnings);
      const resp = await apiPost("/api/rag_eval/run", { ...overrides, run_name: runName });
      if (!resp.success) throw new Error(resp.error || "run failed");
      currentRunId = resp.data.run_id;
      localStorage.setItem("ragEvalCurrentRunId", currentRunId);
      document.getElementById("pipeline-current-run").textContent = "Run: " + currentRunId;
      setPipelineStatus("running", "运行中");
      document.getElementById("btn-cancel-pipeline").disabled = false;
      startReportAutoRefresh();
      startSSE(currentRunId);
      btn.textContent = "运行中...";
    } catch (err) {
      appendLog("error", "启动失败: " + err.message);
      btn.disabled = false;
      btn.textContent = "运行 Pipeline";
      restorePageTitle();
    }
  }

  async function cancelPipeline() {
    if (!currentRunId) return;
    const btn = document.getElementById("btn-cancel-pipeline");
    btn.disabled = true;
    try {
      const resp = await apiPost("/api/rag_eval/runs/" + encodeURIComponent(currentRunId) + "/cancel", {});
      if (!resp.success) throw new Error(resp.error || "cancel failed");
      appendLog("pipeline_cancel_requested", "已请求停止 Pipeline");
      markRunningPhasesCancelling("已请求停止，等待当前 API 调用返回后取消");
      setPipelineStatus("cancelling", "停止中");
    } catch (err) {
      appendLog("error", "停止失败: " + err.message);
      btn.disabled = false;
    }
  }

  function startSSE(runId) {
    if (eventSource) eventSource.close();
    eventSource = new EventSource("/api/rag_eval/runs/" + encodeURIComponent(runId) + "/stream");
    eventSource.onmessage = (evt) => {
      try {
        handleSSEEvent(JSON.parse(evt.data));
      } catch (err) {
        appendLog("error", "SSE解析失败: " + err.message);
      }
    };
    eventSource.onerror = () => appendLog("warn", "SSE连接异常");
  }

  async function loadPipelineState(options) {
    const silent = options && options.silent;
    try {
      const storedRunId = localStorage.getItem("ragEvalCurrentRunId");
      const path = storedRunId
        ? "/api/rag_eval/run-state?run_id=" + encodeURIComponent(storedRunId)
        : "/api/rag_eval/run-state";
      const resp = await apiGet(path);
      if (!resp.success) throw new Error(resp.error || "run state failed");
      let state = (resp.data || {}).latest_run;
      if ((!state || !(resp.data || {}).available) && storedRunId) {
        const fallback = await apiGet("/api/rag_eval/run-state");
        state = fallback.success ? ((fallback.data || {}).latest_run || null) : null;
      }
      if (!state) return;
      restorePipelineState(state);
    } catch (err) {
      if (!silent) appendLog("warn", "运行状态恢复失败: " + err.message);
    }
  }

  function restorePipelineState(state) {
    currentRunId = state.run_id;
    localStorage.setItem("ragEvalCurrentRunId", currentRunId);
    document.getElementById("pipeline-current-run").textContent = "Run: " + currentRunId;
    document.getElementById("pipeline-log").innerHTML = "";
    pipelineEventKeys = new Set();
    resetPipelineProgress(state.steps || []);
    (state.events || []).forEach(event => {
      pipelineEventKeys.add(pipelineEventKey(event));
      updatePipelineProgress(event);
      if (shouldLogPipelineEvent(event)) appendLog(event.type || "info", event.message || JSON.stringify(event), event.timestamp);
    });
    const stillRunning = state.status === "running" || state.status === "created" || state.status === "cancelling";
    const statusText = state.status === "cancelling" ? "停止中" : (stillRunning ? "运行中" : "已完成");
    setPipelineStatus(stillRunning ? state.status : state.status, statusText);
    if (stillRunning) {
      hideRunNotice(false);
      setPageTitle(state.status === "cancelling" ? "停止中" : "运行中");
    } else {
      showRunCompletionNotice(state.status, state.status_reason, state.run_id);
    }
    const btn = document.getElementById("btn-run-pipeline");
    btn.disabled = stillRunning;
    btn.textContent = stillRunning ? "运行中..." : "运行 Pipeline";
    document.getElementById("btn-cancel-pipeline").disabled = !stillRunning || state.status === "cancelling";
    if (stillRunning) startReportAutoRefresh();
    if (stillRunning) startSSE(currentRunId);
  }

  function handleSSEEvent(event) {
    const type = event.type || "info";
    const data = event.data || {};
    if (type === "heartbeat" || type === "connected") {
      setConnectionStatus("running", "运行中");
      if (type === "heartbeat") return;
    }
    if (hasSeenPipelineEvent(event)) return;
    updatePipelineProgress(event);
    if (shouldLogPipelineEvent(event)) appendLog(type, event.message || JSON.stringify(event), event.timestamp);
    if (type === "step_done" || type === "step_error" || type === "step_cancelled") {
      loadReports();
      loadAnalysis();
    }
    if (type === "pipeline_cancel_requested") {
      markRunningPhasesCancelling("已请求停止，等待当前 API 调用返回后取消");
      setPipelineStatus("cancelling", "停止中");
      document.getElementById("btn-cancel-pipeline").disabled = true;
    }
    if (type === "api_call_start" || type === "api_call_waiting") {
      const phase = data.step ? pipelinePhaseState.items[data.step] : null;
      if (phase && phase.status === "cancelling") {
        setPipelineStatus("cancelling", "停止中");
      } else {
        setPipelineStatus("running", "等待长时间 API");
      }
    }
    if (type === "api_call_done") {
      const phase = data.step ? pipelinePhaseState.items[data.step] : null;
      setPipelineStatus(phase && phase.status === "cancelling" ? "cancelling" : "running", phase && phase.status === "cancelling" ? "停止中" : "运行中");
    }
    if (type === "pipeline_done") {
      setPipelineStatus(data.status || "pass", pipelineDoneText(data.status, data.status_reason));
      showRunCompletionNotice(data.status || "pass", data.status_reason, currentRunId);
      finishRun();
      refreshStatus();
    }
    if (type === "pipeline_error") {
      setPipelineStatus("fail", "失败");
      showRunCompletionNotice("fail", "pipeline_error", currentRunId, event.message || data.error || "");
      finishRun();
    }
  }

  function finishRun() {
    const btn = document.getElementById("btn-run-pipeline");
    btn.disabled = false;
    btn.textContent = "运行 Pipeline";
    document.getElementById("btn-cancel-pipeline").disabled = true;
    stopReportAutoRefresh();
    if (eventSource) eventSource.close();
    eventSource = null;
  }

  function setPipelineStatus(status, text) {
    const el = document.getElementById("pipeline-run-status");
    el.className = "state-tag " + status;
    el.textContent = text;
    if (status === "running" || status === "created" || status === "cancelling") {
      setConnectionStatus("running", text || "运行中");
      setPageTitle(status === "cancelling" ? "停止中" : "运行中");
    } else {
      setConnectionStatus("online", "已连接");
    }
  }

  function setConnectionStatus(status, text) {
    const indicator = document.getElementById("status-indicator");
    const statusText = document.getElementById("status-text");
    if (indicator) indicator.className = "status-dot " + status;
    if (statusText) statusText.textContent = text;
  }

  function pipelineDoneText(status, reason) {
    if (status === "pass") return "完成";
    if (reason === "threshold_failed") return "未达阈值";
    if (reason === "threshold_missing") return "待复核";
    if (status === "cancelled") return "已取消";
    return "失败";
  }

  function showRunCompletionNotice(status, reason, runId, message) {
    const notice = document.getElementById("run-notice");
    if (!notice || !runId) return;
    if (sessionStorage.getItem(RUN_NOTICE_DISMISSED_KEY) === runId) return;
    const meta = runNoticeMeta(status, reason, message);
    notice.className = "run-notice " + meta.className;
    document.getElementById("run-notice-state").className = "state-tag " + meta.className;
    document.getElementById("run-notice-state").textContent = meta.stateText;
    document.getElementById("run-notice-title").textContent = meta.title;
    document.getElementById("run-notice-detail").textContent = "Run: " + runId + " · " + meta.detail;
    setPageTitle(meta.titlePrefix);
  }

  function runNoticeMeta(status, reason, message) {
    if (status === "pass") {
      return {
        className: "pass",
        stateText: "完成",
        title: "测评完成，指标通过",
        detail: "可以查看报告，或发布本次配置到正式 RAG。",
        titlePrefix: "测评完成",
      };
    }
    if (status === "cancelled") {
      return {
        className: "cancelled",
        stateText: "已取消",
        title: "测评已取消",
        detail: "本轮结果可能不完整，可以查看已有事件和中间报告。",
        titlePrefix: "已取消",
      };
    }
    if (reason === "threshold_failed") {
      return {
        className: "warn",
        stateText: "需调参",
        title: "测评完成，但未达阈值",
        detail: "建议查看调参诊断和坏例链路，再调整参数重跑。",
        titlePrefix: "需调参",
      };
    }
    if (reason === "threshold_missing") {
      return {
        className: "warn",
        stateText: "待复核",
        title: "测评完成，部分阈值缺失",
        detail: "建议查看报告并补齐阈值配置。",
        titlePrefix: "待复核",
      };
    }
    return {
      className: "fail",
      stateText: "失败",
      title: "测评失败",
      detail: message || "建议查看实时事件定位失败步骤。",
      titlePrefix: "测评失败",
    };
  }

  function hideRunNotice(rememberDismiss) {
    const notice = document.getElementById("run-notice");
    if (!notice) return;
    if (rememberDismiss && currentRunId) sessionStorage.setItem(RUN_NOTICE_DISMISSED_KEY, currentRunId);
    notice.classList.add("hidden");
  }

  function setPageTitle(prefix) {
    document.title = prefix ? "[" + prefix + "] " + BASE_PAGE_TITLE : BASE_PAGE_TITLE;
  }

  function restorePageTitle() {
    setPageTitle("");
  }

  function clearLog() {
    document.getElementById("pipeline-log").innerHTML = "";
    document.getElementById("pipeline-current-run").textContent = "";
    pipelineEventKeys = new Set();
    resetPipelineProgress([]);
  }

  function appendLog(className, message, timestamp) {
    const el = document.getElementById("pipeline-log");
    const line = document.createElement("div");
    line.className = "log-line " + className;
    line.innerHTML = '<span class="ts">' + fmtTime(timestamp) + '</span>' + escHtml(message);
    el.appendChild(line);
    el.scrollTop = el.scrollHeight;
  }

  function hasSeenPipelineEvent(event) {
    const key = pipelineEventKey(event);
    if (pipelineEventKeys.has(key)) return true;
    pipelineEventKeys.add(key);
    return false;
  }

  function pipelineEventKey(event) {
    return [event.timestamp || "", event.type || "", event.message || ""].join("|");
  }

  function getSelectedPipelineSteps() {
    return Array.from(document.querySelectorAll("#step-checklist input[type=checkbox]:checked")).map(input => input.value);
  }

  function shouldLogPipelineEvent(event) {
    const type = event.type || "info";
    if (type === "heartbeat" || type === "connected" || type === "api_call_waiting" || type === "step_progress") return false;
    if (type === "dependency_check_start" || type === "dependency_check_done") return false;
    return true;
  }

  function resetPipelineProgress(steps) {
    pipelinePhaseState = { order: [], items: {} };
    (steps || []).forEach(step => ensurePipelinePhase(step));
    renderPipelineProgress();
  }

  function ensurePipelinePhase(step) {
    if (!step) return null;
    if (!pipelinePhaseState.items[step]) {
      pipelinePhaseState.items[step] = {
        name: step,
        status: "pending",
        startedAt: "",
        finishedAt: "",
        seconds: null,
        waitedSeconds: null,
        current: null,
        total: null,
        sampleCurrent: null,
        sampleTotal: null,
        progressPhase: "",
        message: "",
      };
      pipelinePhaseState.order.push(step);
    }
    return pipelinePhaseState.items[step];
  }

  function updatePipelineProgress(event) {
    const type = event.type || "info";
    const data = event.data || {};
    if (type === "pipeline_start" && data.steps) {
      resetPipelineProgress(data.steps);
      return;
    }
    const step = data.step;
    const phase = ensurePipelinePhase(step);
    if (!phase) return;
    if (type === "step_start") {
      phase.status = "running";
      phase.startedAt = event.timestamp || phase.startedAt;
      phase.message = event.message || "";
    } else if (type === "dependency_check_start") {
      phase.status = "running";
      phase.startedAt = phase.startedAt || event.timestamp || "";
      phase.message = event.message || "";
    } else if (type === "dependency_check_done") {
      phase.status = "running";
      phase.message = event.message || "";
    } else if (type === "dependency_check_failed" || type === "dependency_compat_failed") {
      phase.status = "fail";
      phase.finishedAt = event.timestamp || phase.finishedAt;
      phase.seconds = data.seconds != null ? data.seconds : phase.seconds;
      phase.message = event.message || data.error || "";
    } else if (type === "step_progress") {
      if (phase.status !== "cancelling") {
        phase.status = "running";
      }
      phase.startedAt = phase.startedAt || event.timestamp || "";
      phase.current = data.current != null ? data.current : phase.current;
      phase.total = data.total != null ? data.total : phase.total;
      if (isSampleProgress(data)) {
        phase.sampleCurrent = data.current != null ? data.current : phase.sampleCurrent;
        phase.sampleTotal = data.total != null ? data.total : phase.sampleTotal;
      }
      phase.progressPhase = data.phase || phase.progressPhase || "";
      phase.message = buildStepProgressMessage(data, event.message);
    } else if (type === "api_call_start") {
      if (phase.status === "cancelling") {
        phase.message = phase.message || "已请求停止，等待当前 API 调用返回后取消";
        renderPipelineProgress();
        return;
      }
      phase.status = "running";
      phase.startedAt = phase.startedAt || event.timestamp || "";
      phase.message = event.message || "";
    } else if (type === "api_call_waiting") {
      if (phase.status !== "cancelling") {
        phase.status = "running";
      }
      phase.waitedSeconds = data.waited_seconds;
      phase.message = phase.status === "cancelling"
        ? "已请求停止，等待当前 API 调用返回后取消"
        : (event.message || "");
    } else if (type === "api_call_done") {
      if (phase.status !== "cancelling") {
        phase.status = data.status && data.status !== "pass" ? "fail" : "running";
      }
      phase.seconds = data.seconds != null ? data.seconds : phase.seconds;
      phase.message = phase.status === "cancelling"
        ? "当前 API 已返回，正在收尾取消"
        : (event.message || "");
    } else if (type === "step_done") {
      phase.status = !data.status || data.status === "pass" ? "pass" : "fail";
      phase.finishedAt = event.timestamp || phase.finishedAt;
      phase.seconds = data.seconds != null ? data.seconds : phase.seconds;
      phase.message = event.message || "";
    } else if (type === "step_error") {
      phase.status = "fail";
      phase.finishedAt = event.timestamp || phase.finishedAt;
      phase.seconds = data.seconds != null ? data.seconds : phase.seconds;
      phase.message = event.message || data.error || "";
    } else if (type === "step_cancelled") {
      phase.status = "cancelled";
      phase.finishedAt = event.timestamp || phase.finishedAt;
      phase.seconds = data.seconds != null ? data.seconds : phase.seconds;
      phase.message = event.message || "";
    } else if (type === "step_skipped") {
      phase.status = "skipped";
      phase.finishedAt = event.timestamp || phase.finishedAt;
      phase.message = event.message || "";
    }
    renderPipelineProgress();
  }

  function renderPipelineProgress() {
    const el = document.getElementById("pipeline-phase-progress");
    if (!el) return;
    if (!pipelinePhaseState.order.length) {
      el.innerHTML = '<div class="empty-state">阶段进度会在 Pipeline 启动后显示</div>';
      return;
    }
    el.innerHTML = pipelinePhaseState.order.map(step => renderPipelinePhase(pipelinePhaseState.items[step])).join("");
  }

  function markRunningPhasesCancelling(message) {
    let changed = false;
    pipelinePhaseState.order.forEach(step => {
      const phase = pipelinePhaseState.items[step];
      if (!phase || phase.status !== "running") return;
      phase.status = "cancelling";
      phase.message = message || "已请求停止，等待当前步骤返回后取消";
      changed = true;
    });
    if (changed) renderPipelineProgress();
  }

  function renderPipelinePhase(phase) {
    const statusText = phaseStatusText(phase);
    const progressTotal = phase.sampleTotal || phase.total;
    const progressCurrent = phase.sampleTotal ? phase.sampleCurrent : phase.current;
    const progressPct = progressTotal ? Math.max(0, Math.min(100, Math.round((Number(progressCurrent || 0) / Number(progressTotal)) * 100))) : null;
    const progressText = phase.sampleTotal
      ? "样本 " + (phase.sampleCurrent || 0) + "/" + phase.sampleTotal
      : (phase.total ? progressMetaLabel(phase.progressPhase) + " " + (phase.current || 0) + "/" + phase.total : "");
    const meta = [
      "开始 " + (phase.startedAt ? fmtTime(phase.startedAt) : "--"),
      "结束 " + (phase.finishedAt ? fmtTime(phase.finishedAt) : "--"),
      phase.seconds != null ? "耗时 " + phase.seconds + "s" : "",
      phase.waitedSeconds != null && phase.status === "running" ? "已等待 " + phase.waitedSeconds + "s" : "",
      progressText,
    ].filter(Boolean).join(" · ");
    return '<div class="phase-row ' + escAttr(phase.status) + '">' +
      '<div class="phase-topline">' +
        '<span class="phase-name">' + escHtml(phase.name) + '</span>' +
        '<span class="phase-status">' + escHtml(statusText) + '</span>' +
      '</div>' +
      '<div class="phase-bar"><div class="phase-fill"' + (progressPct != null ? ' style="width:' + progressPct + '%"' : "") + '></div></div>' +
      '<div class="phase-meta">' +
        '<span>' + escHtml(meta) + '</span>' +
        '<span>' + escHtml(phase.message || "") + '</span>' +
      '</div>' +
    '</div>';
  }

  function buildStepProgressMessage(data, fallback) {
    const total = data.total != null ? Number(data.total) : null;
    const current = data.current != null ? Number(data.current) : null;
    if (total && current != null) {
      const phase = data.phase ? data.phase + " " : "";
      const question = data.question ? " · " + String(data.question).slice(0, 80) : "";
      return phase + current + "/" + total + question;
    }
    return fallback || "";
  }

  function isSampleProgress(data) {
    const phase = String(data.phase || "");
    return Boolean(data.question || data.sample_id || ["retrieval", "build_dataset", "cancelled"].includes(phase));
  }

  function progressMetaLabel(phase) {
    return String(phase || "") === "judge" ? "Judge" : "阶段";
  }

  function phaseStatusText(phase) {
    if (phase.status === "pending") return "等待";
    if (phase.status === "cancelling") return "停止中";
    if (phase.status === "running") return "运行中";
    if (phase.status === "pass") return "完成";
    if (phase.status === "fail") return "失败";
    if (phase.status === "cancelled") return "已取消";
    if (phase.status === "skipped") return "已跳过";
    return phase.status || "--";
  }

  async function loadAnalysis() {
    try {
      const resp = await apiGet("/api/rag_eval/analysis/latest");
      if (!resp.success) throw new Error(resp.error || "analysis failed");
      latestAnalysis = resp.data;
      renderAnalysis(resp.data);
    } catch (err) {
      document.getElementById("bad-case-list").innerHTML = '<div class="empty-state">分析数据加载失败: ' + escHtml(err.message) + '</div>';
    }
  }

  function renderAnalysis(data) {
    const badCases = ((data.bad_cases || {}).traces || []);
    const traceIndex = data.trace_index || {};
    renderDiagnosis("analysis-diagnosis", data.developer_diagnosis || null);
    document.getElementById("bad-case-title").textContent = badCases.length + " / " + (traceIndex.trace_count || 0) + " 个坏例";
    const list = document.getElementById("bad-case-list");
    if (!badCases.length) {
      list.innerHTML = '<div class="empty-state">暂无坏例</div>';
      return;
    }
    list.innerHTML = badCases.map((item, index) => (
      '<button class="case-button" type="button" data-case-index="' + index + '">' +
        '<div class="case-title">#' + escHtml(item.question_index) + " " + escHtml(item.question || "") + '</div>' +
        '<div class="case-meta">' + escHtml((item.bad_case_cases || []).map(c => metricLabel(c.metric || c.source || c.reason)).filter(Boolean).join(" · ") || "坏例") + '</div>' +
      '</button>'
    )).join("");
    list.onclick = event => {
      const button = event.target.closest(".case-button");
      if (!button || !list.contains(button)) return;
      selectCase(Number(button.dataset.caseIndex));
    };
    selectCase(Math.min(selectedCaseIndex, badCases.length - 1));
  }

  function selectCase(index) {
    const cases = (((latestAnalysis || {}).bad_cases || {}).traces || []);
    const item = cases[index];
    if (!item) return;
    selectedCaseIndex = index;
    document.querySelectorAll("#bad-case-list .case-button").forEach((btn, idx) => btn.classList.toggle("active", idx === index));
    document.getElementById("case-detail-title").textContent = "#" + item.question_index + " " + item.trace_id;
    document.getElementById("case-detail").innerHTML = renderCaseDetail(item);
  }

  function renderCaseDetail(item) {
    return [
      '<div class="detail-block"><h3>问题</h3><p>' + escHtml(item.question || "") + '</p></div>',
      '<div class="detail-block"><h3>生成回答</h3><p>' + escHtml(item.answer || item.answer_preview || "--") + '</p></div>',
      '<div class="detail-block"><h3>参考答案</h3><p>' + escHtml(item.reference_answer || "--") + '</p></div>',
      '<div class="detail-block"><h3>Ragas 分数</h3>' + renderScores(item.ragas_scores || {}) + '</div>',
      '<div class="detail-block"><h3>检索</h3>' + renderRetrieval(item.retrieval || {}) + '</div>',
      '<div class="detail-block"><h3>证据</h3>' + renderEvidence(item.evidence || []) + '</div>',
    ].join("");
  }

  function renderScores(scores) {
    const entries = Object.entries(scores).filter(([key, value]) => key !== "metric_run_values" && typeof value === "number");
    if (!entries.length) return '<p class="empty-state">暂无分数</p>';
    return entries.map(([key, value]) => (
      '<div class="score-row"><span>' + escHtml(metricLabel(key)) + '</span><div class="score-bar"><div class="score-fill" style="width:' + Math.max(0, Math.min(100, value * 100)) + '%"></div></div><span>' + fmtNum(value) + '</span></div>'
    )).join("");
  }

  function renderRetrieval(retrieval) {
    return '<div class="kv-list">' +
      '<div class="kv-row"><div class="kv-key">' + escHtml(metricLabel("Recall")) + '</div><div class="kv-val">' + fmtNum(retrieval.recall) + '</div></div>' +
      '<div class="kv-row"><div class="kv-key">' + escHtml(metricLabel("MRR")) + '</div><div class="kv-val">' + fmtNum(retrieval.reciprocal_rank) + '</div></div>' +
      '<div class="kv-row"><div class="kv-key">' + escHtml(metricLabel("Gold Docs")) + '</div><div class="kv-val">' + escHtml((retrieval.gold_doc_ids || []).join(", ")) + '</div></div>' +
      '<div class="kv-row"><div class="kv-key">' + escHtml(metricLabel("Loss")) + '</div><div class="kv-val">' + escHtml((retrieval.loss_reasons || []).join(", ")) + '</div></div>' +
    '</div>';
  }

  function renderEvidence(items) {
    if (!items.length) return '<p class="empty-state">暂无证据</p>';
    return items.map(item => (
      '<div class="evidence-item">' +
        '<div class="case-title">' + escHtml(item.evidence_id || "") + " · " + escHtml(item.chunk_id || "") + '</div>' +
        '<div class="case-meta">source=' + escHtml(item.retrieval_source || "--") + " · rerank=" + fmtNum(item.rerank_score) + '</div>' +
        '<p>' + escHtml(item.content_preview || "") + '</p>' +
      '</div>'
    )).join("");
  }

  async function loadReports() {
    const path = currentRunId
      ? "/api/rag_eval/runs/" + encodeURIComponent(currentRunId) + "/analysis"
      : "/api/rag_eval/analysis/latest";
    try {
      const resp = await apiGet(path);
      if (resp.success) latestAnalysis = resp.data;
      renderReports(latestAnalysis || {});
    } catch (err) {
      renderReports(latestAnalysis || {});
      appendLog("warn", "报告刷新失败: " + err.message);
    }
  }

  function renderReports(data) {
    const reports = data.reports || [];
    const list = document.getElementById("report-list");
    renderReportSummary(data);
    if (!reports.length) {
      list.innerHTML = '<div class="empty-state">暂无报告</div>';
      document.getElementById("report-content").innerHTML = '<p class="empty-state">暂无报告</p>';
      return;
    }
    list.innerHTML = reports.map((item, index) => (
      '<button class="report-button" type="button" data-report-index="' + index + '">' +
        '<div class="report-title">' + escHtml(item.title) + '</div>' +
        '<div class="report-meta">' + escHtml(item.available ? item.filename : "未生成") + '</div>' +
      '</button>'
    )).join("");
    list.querySelectorAll(".report-button").forEach(button => {
      button.addEventListener("click", () => selectReport(Number(button.dataset.reportIndex)));
    });
    const summaryIndex = reports.findIndex(item => item.key === "summary");
    const preferred = Math.min(selectedReportIndex, reports.length - 1);
    selectReport(preferred >= 0 ? preferred : (summaryIndex >= 0 ? summaryIndex : 0));
  }

  function selectReport(index) {
    const reports = (latestAnalysis || {}).reports || [];
    const item = reports[index];
    if (!item) return;
    selectedReportIndex = index;
    document.querySelectorAll(".report-button").forEach((btn, idx) => btn.classList.toggle("active", idx === index));
    document.getElementById("report-content").innerHTML = item.available
      ? markdownToHtml(item.content || "报告为空")
      : '<p class="empty-state">报告尚未生成: ' + escHtml(item.filename) + '</p>';
  }

  function renderReportSummary(data) {
    const reports = data.reports || [];
    const trace = data.trace_index || {};
    const badCases = data.bad_cases || {};
    const summary = data.summary || {};
    const metrics = summary.key_metrics || {};
    const steps = summary.steps || [];
    const availableCount = reports.filter(item => item.available).length;
    document.getElementById("report-summary-cards").innerHTML = [
      ["Run", data.display_name || summary.display_name || data.run_id || "--", summary.status || "--"],
      ["retrieval_recall_at_k", metrics.retrieval_recall_at_k, "检索召回"],
      ["ragas_faithfulness", metrics.ragas_faithfulness, "Ragas"],
      ["bad_case_trace_count", metrics.bad_case_trace_count != null ? metrics.bad_case_trace_count : (badCases.count || 0), "坏例链路"],
    ].map(([label, value, note]) => (
      '<div class="mini-card">' +
        '<div class="metric-label">' + escHtml(metricLabel(label)) + '</div>' +
        '<div class="metric-value">' + escHtml(fmtNum(value)) + '</div>' +
        '<div class="metric-note">' + escHtml(note || "") + '</div>' +
      '</div>'
    )).join("");
    document.getElementById("report-insights").innerHTML = [
      '<div class="insight-panel">',
        '<div class="insight-title">运行结论</div>',
        '<div class="insight-body">',
          '<span class="state-tag ' + escAttr(summary.status || "idle") + '">' + escHtml(summary.status || "暂无状态") + '</span>',
          '<span>' + escHtml(summary.started_at || "--") + ' → ' + escHtml(summary.finished_at || "--") + '</span>',
          '<span>报告 ' + availableCount + ' / ' + reports.length + '</span>',
          '<span>' + escHtml(metricLabel("bad_case_trace_count")) + ' ' + escHtml(trace.bad_case_trace_count != null ? trace.bad_case_trace_count : (badCases.count || 0)) + '</span>',
        '</div>',
      '</div>',
      renderDiagnosisInline(data.developer_diagnosis || null),
      '<div class="step-result-strip">',
        steps.length ? steps.map(step => (
          '<span class="step-result ' + escAttr(step.status || "unknown") + '">' +
            escHtml(step.name || "--") + ' · ' + escHtml(step.status || "--") +
            '<small>' + escHtml(step.seconds != null ? step.seconds + "s" : "") + '</small>' +
          '</span>'
        )).join("") : '<span class="empty-state">暂无步骤结果</span>',
      '</div>',
    ].join("");
  }

  function markdownToHtml(markdown) {
    const lines = String(markdown || "").split(/\r?\n/);
    const html = [];
    let inCode = false;
    let inList = false;
    let paragraph = [];

    function flushParagraph() {
      if (!paragraph.length) return;
      html.push("<p>" + renderInlineMarkdown(paragraph.join(" ")) + "</p>");
      paragraph = [];
    }

    function closeList() {
      if (!inList) return;
      html.push("</ul>");
      inList = false;
    }

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (/^```/.test(line.trim())) {
        flushParagraph();
        closeList();
        html.push(inCode ? "</code></pre>" : "<pre><code>");
        inCode = !inCode;
        continue;
      }
      if (inCode) {
        html.push(escHtml(line) + "\n");
        continue;
      }
      if (!line.trim()) {
        flushParagraph();
        closeList();
        continue;
      }
      const tableBlock = collectMarkdownTable(lines, i);
      if (tableBlock) {
        flushParagraph();
        closeList();
        html.push(renderMarkdownTable(tableBlock.rows));
        i = tableBlock.endIndex;
        continue;
      }
      const heading = line.match(/^(#{1,4})\s+(.+)$/);
      if (heading) {
        flushParagraph();
        closeList();
        html.push("<h" + heading[1].length + ">" + renderInlineMarkdown(heading[2]) + "</h" + heading[1].length + ">");
        continue;
      }
      const listItem = line.match(/^\s*[-*]\s+(.+)$/);
      if (listItem) {
        flushParagraph();
        if (!inList) {
          html.push("<ul>");
          inList = true;
        }
        html.push("<li>" + renderInlineMarkdown(listItem[1]) + "</li>");
        continue;
      }
      paragraph.push(line.trim());
    }
    flushParagraph();
    closeList();
    if (inCode) html.push("</code></pre>");
    return html.join("");
  }

  function collectMarkdownTable(lines, startIndex) {
    const header = lines[startIndex];
    const separator = lines[startIndex + 1] || "";
    if (!header.includes("|") || !/^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(separator)) return null;
    const rows = [header, separator];
    let endIndex = startIndex + 1;
    for (let i = startIndex + 2; i < lines.length; i++) {
      if (!lines[i].includes("|") || !lines[i].trim()) break;
      rows.push(lines[i]);
      endIndex = i;
    }
    return { rows, endIndex };
  }

  function renderMarkdownTable(rows) {
    const parsed = rows.map(row => row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(cell => cell.trim()));
    const header = parsed[0] || [];
    const body = parsed.slice(2);
    return '<div class="markdown-table-wrap"><table class="markdown-table"><thead><tr>' +
      header.map(cell => "<th>" + renderInlineMarkdown(cell) + "</th>").join("") +
      "</tr></thead><tbody>" +
      body.map(row => "<tr>" + row.map(cell => "<td>" + renderInlineMarkdown(cell) + "</td>").join("") + "</tr>").join("") +
      "</tbody></table></div>";
  }

  function renderInlineMarkdown(text) {
    return escHtml(text)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  }

  function saveSelectedReport() {
    const reports = (latestAnalysis || {}).reports || [];
    const item = reports[selectedReportIndex];
    if (!item || !item.available) return;
    const blob = new Blob([item.content || ""], { type: "text/markdown;charset=utf-8" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = ((latestAnalysis || {}).run_id || "rag_eval") + "_" + item.filename;
    document.body.appendChild(link);
    link.click();
    URL.revokeObjectURL(link.href);
    link.remove();
  }

  function startReportAutoRefresh() {
    stopReportAutoRefresh();
    reportRefreshTimer = window.setInterval(loadReports, 15000);
  }

  function stopReportAutoRefresh() {
    if (reportRefreshTimer) window.clearInterval(reportRefreshTimer);
    reportRefreshTimer = null;
  }

  async function loadHistory(page) {
    try {
      historyPage = Math.max(Number(page || historyPage || 1), 1);
      const resp = await apiGet("/api/rag_eval/runs?page=" + historyPage + "&page_size=" + HISTORY_PAGE_SIZE);
      if (!resp.success) throw new Error(resp.error || "runs failed");
      const payload = resp.data || {};
      const runs = Array.isArray(payload) ? payload : (payload.items || []);
      historyPagination = Array.isArray(payload)
        ? { page: 1, page_size: runs.length || HISTORY_PAGE_SIZE, total: runs.length, total_pages: 1 }
        : {
          page: payload.page || historyPage,
          page_size: payload.page_size || HISTORY_PAGE_SIZE,
          total: payload.total || 0,
          total_pages: payload.total_pages || 1,
        };
      historyPage = historyPagination.page || historyPage;
      historyRuns = runs;
      const tbody = document.getElementById("history-tbody");
      const historyHead = document.querySelector("#history-table thead");
      if (historyHead) {
        historyHead.innerHTML = '<tr><th>Pipeline</th><th>状态</th><th>开始时间</th><th>' +
          escHtml(metricLabel("retrieval_recall_at_k")) + '</th><th>' +
          escHtml(metricLabel("ragas_faithfulness")) + '</th><th>' +
          escHtml(metricLabel("bad_case_trace_count")) + '</th><th>操作</th></tr>';
      }
      if (!runs.length) {
        tbody.innerHTML = '<tr><td colspan="7">暂无历史记录</td></tr>';
        renderHistoryPagination();
        diffCandidateRunId = null;
        setupRunDiffSelector();
        return;
      }
      tbody.innerHTML = runs.map(run => {
        const metrics = run.key_metrics || {};
        const displayName = run.display_name || run.run_id || "";
        return '<tr>' +
          '<td title="' + escAttr(run.run_id || "") + '"><div class="run-display-name">' + escHtml(displayName) + '</div></td>' +
          '<td>' + escHtml(run.status || "") + '</td>' +
          '<td>' + escHtml(run.display_time || run.started_at || "") + '</td>' +
          '<td>' + fmtNum(metrics.retrieval_recall_at_k) + '</td>' +
          '<td>' + fmtNum(metrics.ragas_faithfulness) + '</td>' +
          '<td>' + fmtNum(metrics.bad_case_trace_count) + '</td>' +
          '<td>' +
            '<button class="ghost-button" type="button" data-history-action="detail" data-run-id="' + escAttr(run.run_id || "") + '">详情</button> ' +
            '<button class="ghost-button" type="button" data-history-action="reports" data-run-id="' + escAttr(run.run_id || "") + '">报告</button> ' +
            '<button class="ghost-button danger" type="button" data-history-action="delete" data-run-id="' + escAttr(run.run_id || "") + '">删除</button>' +
          '</td>' +
        '</tr>';
      }).join("");
      renderHistoryPagination();
      setupRunDiffSelector();
    } catch (err) {
      document.getElementById("history-tbody").innerHTML = '<tr><td colspan="7">加载失败: ' + escHtml(err.message) + '</td></tr>';
      document.getElementById("run-diff-panel").innerHTML = '<div class="empty-state">对比加载失败: ' + escHtml(err.message) + '</div>';
      renderHistoryPagination();
    }
  }

  function renderHistoryPagination() {
    const container = document.getElementById("history-pagination");
    if (!container) return;
    const page = historyPagination.page || 1;
    const totalPages = historyPagination.total_pages || 1;
    const total = historyPagination.total || 0;
    if (total <= HISTORY_PAGE_SIZE) {
      container.innerHTML = total ? '<span class="history-page-info">共 ' + escHtml(String(total)) + ' 条</span>' : "";
      return;
    }
    container.innerHTML = [
      '<button class="ghost-button" type="button" ' + (page <= 1 ? "disabled" : "") + ' data-history-page="' + escAttr(page - 1) + '">上一页</button>',
      '<span class="history-page-info">第 ' + escHtml(String(page)) + ' / ' + escHtml(String(totalPages)) + ' 页 · 共 ' + escHtml(String(total)) + ' 条</span>',
      '<button class="ghost-button" type="button" ' + (page >= totalPages ? "disabled" : "") + ' data-history-page="' + escAttr(page + 1) + '">下一页</button>',
    ].join("");
  }

  async function loadRunDiff() {
    const panel = document.getElementById("run-diff-panel");
    const candidateRunId = diffCandidateRunId || candidateRunFromHistory();
    const baselineRunId = document.getElementById("diff-baseline-select").value;
    document.getElementById("diff-candidate-run").textContent = runDisplayLabelById(candidateRunId);
    if (!baselineRunId || !candidateRunId) {
      panel.innerHTML = '<div class="empty-state">请选择 baseline，并确保有本次 candidate 结果。</div>';
      return;
    }
    try {
      const resp = await apiGet(
        "/api/rag_eval/runs/diff?base_run_id=" + encodeURIComponent(baselineRunId) +
        "&candidate_run_id=" + encodeURIComponent(candidateRunId)
      );
      if (!resp.success) throw new Error(resp.error || "diff failed");
      renderRunDiff(resp.data || {});
    } catch (err) {
      panel.innerHTML = '<div class="empty-state">对比加载失败: ' + escHtml(err.message) + '</div>';
    }
  }

  function setupRunDiffSelector(candidateRunId) {
    diffCandidateRunId = candidateRunId || diffCandidateRunId || candidateRunFromHistory();
    const select = document.getElementById("diff-baseline-select");
    if (!select) return;
    const baselineRuns = historyRuns.filter(run => run.run_id && run.run_id !== diffCandidateRunId);
    if (!baselineRuns.length) {
      select.innerHTML = '<option value="">暂无可选基线</option>';
      document.getElementById("diff-candidate-run").textContent = runDisplayLabelById(diffCandidateRunId);
      loadRunDiff();
      return;
    }
    const previousValue = select.value;
    const defaultBaseline = baselineRuns.find(run => run.run_id === previousValue)
      ? previousValue
      : baselineRuns[0].run_id;
    select.innerHTML = baselineRuns.map(run => (
      '<option value="' + escAttr(run.run_id) + '"' + (run.run_id === defaultBaseline ? " selected" : "") + ">" +
        escHtml(run.display_name || run.run_id) +
      '</option>'
    )).join("");
    select.onchange = () => loadRunDiff();
    document.getElementById("diff-candidate-run").textContent = runDisplayLabelById(diffCandidateRunId);
    loadRunDiff();
  }

  function candidateRunFromHistory() {
    return (historyRuns.find(run => run.run_id) || {}).run_id || null;
  }

  function runDisplayLabelById(runId) {
    if (!runId) return "--";
    const found = historyRuns.find(run => run.run_id === runId);
    return (found && (found.display_name || found.run_id)) || runId;
  }

  function renderRunDiff(diff) {
    const panel = document.getElementById("run-diff-panel");
    if (!diff.available) {
      panel.innerHTML = '<div class="empty-state">' + escHtml(diff.message || "暂无对比数据") + '</div>';
      return;
    }
    const metricRows = (diff.metric_deltas || []).map(row => (
      '<tr class="' + escAttr(row.direction || "") + '">' +
        '<td>' + escHtml(metricLabel(row.metric)) + '</td>' +
        '<td>' + fmtNum(row.base) + '</td>' +
        '<td>' + fmtNum(row.candidate) + '</td>' +
        '<td>' + formatDelta(row.delta) + '</td>' +
      '</tr>'
    )).join("");
    const bad = diff.bad_case_delta || {};
    const configRows = (diff.config_deltas || []).map(row => (
      '<tr><td>' + escHtml(configLabel(row.field || row.label || "")) + '</td><td>' + escHtml(fmtNullable(row.base)) + '</td><td>' + escHtml(fmtNullable(row.candidate)) + '</td></tr>'
    )).join("");
    panel.innerHTML = [
      '<div class="diff-head">',
        '<div><span class="metric-label">Baseline</span><div class="mono" title="' + escAttr(diff.base_run_id || "") + '">' + escHtml(runDisplayLabelById(diff.base_run_id)) + '</div></div>',
        '<div><span class="metric-label">Candidate</span><div class="mono" title="' + escAttr(diff.candidate_run_id || "") + '">' + escHtml(runDisplayLabelById(diff.candidate_run_id)) + '</div></div>',
      '</div>',
      '<div class="diff-summary">',
        '<span>坏例 ' + escHtml(String(bad.base_count)) + ' → ' + escHtml(String(bad.candidate_count)) + ' (' + formatDelta(bad.delta) + ')</span>',
        '<span>修复题号: ' + escHtml((bad.resolved_question_indexes || []).join(", ") || "--") + '</span>',
        '<span>新增题号: ' + escHtml((bad.new_question_indexes || []).join(", ") || "--") + '</span>',
      '</div>',
      '<div class="table-wrap"><table class="data-table compact-table"><thead><tr><th>指标</th><th>基线</th><th>候选</th><th>变化</th></tr></thead><tbody>' + metricRows + '</tbody></table></div>',
      '<div class="diff-config">',
        '<h3>配置变化</h3>',
        configRows ? '<div class="table-wrap"><table class="data-table compact-table"><thead><tr><th>字段</th><th>基线</th><th>候选</th></tr></thead><tbody>' + configRows + '</tbody></table></div>' : '<div class="empty-state">关键配置无变化</div>',
      '</div>',
    ].join("");
  }

  async function showRunDetail(runId) {
    try {
      const resp = await apiGet("/api/rag_eval/runs/" + encodeURIComponent(runId));
      if (!resp.success) throw new Error(resp.error || "detail failed");
      const data = resp.data || {};
      document.getElementById("run-detail-panel").classList.remove("hidden");
      document.getElementById("run-detail-title").textContent = data.display_name || runDisplayLabelById(runId);
      renderRunDetail("run-detail-body", data);
      document.getElementById("run-detail-panel").scrollIntoView({ behavior: "smooth" });
    } catch (err) {
      alert("加载详情失败: " + err.message);
    }
  }

  function closeRunDetail() {
    document.getElementById("run-detail-panel").classList.add("hidden");
  }

  async function deleteRun(runId) {
    const safeRunId = String(runId || "").trim();
    if (!safeRunId) return;
    const displayName = runDisplayLabelById(safeRunId);
    const confirmed = window.confirm(
      "确定删除 pipeline " + displayName + "？\n这会同步删除本地 output/runs 中该 run 的所有文件。"
    );
    if (!confirmed) return;
    try {
      const resp = await apiDelete("/api/rag_eval/runs/" + encodeURIComponent(safeRunId));
      if (!resp.success) throw new Error(resp.error || "delete failed");
      if (currentRunId === safeRunId) {
        currentRunId = null;
        latestAnalysis = null;
        localStorage.removeItem("ragEvalCurrentRunId");
        document.getElementById("pipeline-current-run").textContent = "";
      }
      if (diffCandidateRunId === safeRunId) diffCandidateRunId = null;
      if ((latestAnalysis || {}).run_id === safeRunId) latestAnalysis = null;
      document.getElementById("run-detail-panel").classList.add("hidden");
      const nextPage = historyRuns.length <= 1 && historyPage > 1 ? historyPage - 1 : historyPage;
      await loadHistory(nextPage);
      refreshStatus();
    } catch (err) {
      alert("删除失败: " + err.message);
    }
  }

  async function showRunReports(runId) {
    try {
      const resp = await apiGet("/api/rag_eval/runs/" + encodeURIComponent(runId) + "/analysis");
      if (!resp.success) throw new Error(resp.error || "reports failed");
      currentRunId = runId;
      diffCandidateRunId = runId;
      latestAnalysis = resp.data;
      renderReports(latestAnalysis);
      if (historyRuns.length) setupRunDiffSelector(runId);
      document.querySelector('[data-tab="reports"]').click();
    } catch (err) {
      alert("加载历史报告失败: " + err.message);
    }
  }

  function pick(obj, keys) {
    const out = {};
    keys.forEach(key => { if (Object.prototype.hasOwnProperty.call(obj, key)) out[key] = obj[key]; });
    return out;
  }

  function setValue(id, value) {
    const el = document.getElementById(id);
    if (el) el.value = value;
  }

  function toggleLanguage() {
    uiLang = uiLang === "zh" ? "en" : "zh";
    localStorage.setItem("ragEvalLang", uiLang);
    updateLanguageButton();
    if (latestAnalysis) {
      renderDiagnosis("overview-diagnosis", latestAnalysis.developer_diagnosis || null);
      renderDiagnosis("analysis-diagnosis", latestAnalysis.developer_diagnosis || null);
      renderAnalysis(latestAnalysis);
      renderReports(latestAnalysis);
    }
    if (latestConfig) renderConfig(latestConfig);
    updateStaticConfigLabels();
    loadHistory();
    refreshStatus();
  }

  function updateLanguageButton() {
    const btn = document.getElementById("btn-toggle-lang");
    if (btn) btn.textContent = uiLang === "zh" ? "中文 / EN" : "EN / 中文";
  }

  function metricLabel(key) {
    const text = String(key || "");
    const direct = METRIC_LABELS[text];
    if (direct) return direct[uiLang] || direct.zh || text;
    const normalized = text.replace(/^ragas_/, "").replace(/_min$/, "");
    const match = METRIC_LABELS[normalized];
    if (match) return match[uiLang] || match.zh || text;
    if (uiLang === "zh") return text.replace(/_/g, " ");
    return text;
  }

  function configLabel(key) {
    const text = String(key || "");
    const shortKey = text.split(".").pop() || text;
    const label = CONFIG_LABELS[shortKey] || CONFIG_LABELS[text];
    if (!label) return uiLang === "zh" ? shortKey : text;
    const translated = label[uiLang] || label.zh || shortKey;
    return uiLang === "zh" ? translated + " (" + shortKey + ")" : translated + " (" + shortKey + ")";
  }

  function paramMeta(key) {
    const text = String(key || "");
    const shortKey = text.split(".").pop() || text;
    return PARAM_META[shortKey] || PARAM_META[text] || null;
  }

  function formatRange(range, unit) {
    return range[0] + " - " + range[1] + (unit ? " " + unit : "");
  }

  function updateStaticConfigLabels() {
    document.querySelectorAll("[data-config-label]").forEach(el => {
      el.textContent = configLabel(el.dataset.configLabel || "");
    });
    document.querySelectorAll("[data-config-title]").forEach(el => {
      el.innerHTML = renderConfigFieldTitle(el.dataset.configTitle || "");
    });
  }

  function renderDiagnosis(containerId, diagnosis) {
    const el = document.getElementById(containerId);
    if (!el) return;
    if (!diagnosis) {
      el.innerHTML = '<div class="empty-state">暂无诊断</div>';
      return;
    }
    el.className = "diagnosis-panel " + escAttr(diagnosis.severity || "info");
    el.innerHTML = [
      '<div class="diagnosis-main">',
        '<span class="state-tag ' + escAttr(diagnosis.severity || "info") + '">' + escHtml(diagnosis.severity || "info") + '</span>',
        '<div><div class="diagnosis-title">' + escHtml(diagnosis.primary_bottleneck || "暂无瓶颈") + '</div>',
        '<div class="publish-note">当前建议只影响评测参数；正式 RAG 调用仍需单独发布配置。</div>',
        '<div class="diagnosis-evidence">' + renderDiagnosisEvidence(diagnosis.evidence || []) + '</div></div>',
      '</div>',
      renderSuggestionCards(diagnosis.suggested_experiments || []),
      renderDiagnosisCounts(diagnosis),
    ].join("");
  }

  function renderDiagnosisInline(diagnosis) {
    if (!diagnosis) return "";
    return '<div class="insight-panel diagnosis-inline">' +
      '<div class="insight-title">调参诊断</div>' +
      '<div class="insight-body"><span class="state-tag ' + escAttr(diagnosis.severity || "info") + '">' +
      escHtml(diagnosis.primary_bottleneck || "--") + '</span></div>' +
      renderSuggestionCards((diagnosis.suggested_experiments || []).slice(0, 2)) +
    '</div>';
  }

  function renderDiagnosisEvidence(items) {
    if (!items.length) return '<span class="empty-state">暂无证据</span>';
    return '<ul>' + items.map(item => '<li>' + escHtml(item) + '</li>').join("") + '</ul>';
  }

  function renderSuggestionCards(items) {
    if (!items.length) return '<div class="empty-state">暂无下一步建议</div>';
    return '<div class="suggestion-grid">' + items.map(item => (
      '<div class="suggestion-card">' +
        '<div class="suggestion-title">' + escHtml(item.title || "建议") + '</div>' +
        '<p>' + escHtml(item.rationale || "") + '</p>' +
        '<code>' + escHtml(formatObject(item.params || {})) + '</code>' +
      '</div>'
    )).join("") + '</div>';
  }

  function renderDiagnosisCounts(diagnosis) {
    const categories = diagnosis.category_counts || {};
    const metrics = diagnosis.low_metric_counts || {};
    const chips = [];
    Object.entries(categories).forEach(([key, value]) => chips.push(metricLabel(key) + ": " + value));
    Object.entries(metrics).forEach(([key, value]) => chips.push(metricLabel(key) + ": " + value));
    return chips.length ? '<div class="diagnosis-chips">' + chips.map(item => '<span>' + escHtml(item) + '</span>').join("") + '</div>' : "";
  }

  function fmtNum(value) {
    if (value == null || value === "") return "--";
    if (typeof value !== "number") return String(value);
    return Number.isInteger(value) ? String(value) : value.toFixed(4);
  }

  function fmtNullable(value) {
    return value == null ? "null" : (Array.isArray(value) ? value.join(", ") : String(value));
  }

  function formatDelta(value) {
    if (value == null || value === "") return "--";
    const numberValue = Number(value);
    if (Number.isNaN(numberValue)) return String(value);
    const sign = numberValue > 0 ? "+" : "";
    return sign + (Number.isInteger(numberValue) ? String(numberValue) : numberValue.toFixed(4));
  }

  function formatObject(value) {
    const entries = Object.entries(value);
    return entries.length ? entries.map(([key, val]) => key + ":" + val).join(", ") : "--";
  }

  function fmtTime(timestamp) {
    if (!timestamp) return new Date().toLocaleTimeString();
    const parsed = new Date(timestamp);
    return Number.isNaN(parsed.getTime()) ? timestamp.slice(11, 19) : parsed.toLocaleTimeString();
  }

  function escHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function escAttr(value) {
    return escHtml(value).replace(/'/g, "&#39;");
  }

  function renderRunDetail(containerId, data) {
    const summary = data.summary || {};
    const metrics = summary.key_metrics || {};
    const config = data.config_snapshot || {};
    const pipeline = config.pipeline || {};
    const retrieval = config.retrieval_eval || {};
    const ragas = config.ragas_eval || {};
    const metricItems = [
      [metricLabel("retrieval_recall_at_k"), metrics.retrieval_recall_at_k],
      [metricLabel("retrieval_mrr"), metrics.retrieval_mrr],
      [metricLabel("retrieval_hit_rate"), metrics.retrieval_hit_rate],
      [metricLabel("ragas_faithfulness"), metrics.ragas_faithfulness],
      [metricLabel("ragas_answer_relevancy"), metrics.ragas_answer_relevancy],
      [metricLabel("ragas_context_utilization"), metrics.ragas_context_utilization],
      [metricLabel("ragas_context_recall"), metrics.ragas_context_recall],
      [metricLabel("bad_case_trace_count"), metrics.bad_case_trace_count],
    ].filter(([, value]) => value != null);
    const configItems = [
      ["Pipeline steps", (pipeline.steps || []).join(" -> ")],
      ["Retrieval profile", retrieval.retrieval_profile],
      ["Retrieval limit", retrieval.limit],
      ["Ragas profile", ragas.active_profile],
      ["Ragas limit", ragas.limit],
      ["Ragas metrics", (ragas.selected_metrics || []).join(", ")],
      ["Contexts", ragas.max_contexts != null ? ragas.max_contexts + " x " + ragas.max_context_chars : null],
      ["Response chars", ragas.max_response_chars],
      ["Workers / retries / wait", [ragas.ragas_max_workers, ragas.ragas_max_retries, ragas.ragas_max_wait].filter(value => value != null).join(" / ")],
      ["Judge profile", ragas.judge_profile],
    ].filter(([, value]) => value != null && value !== "");
    const overviewSummary = {
      ...summary,
      display_name: data.display_name,
      display_time: data.display_time,
      display_subtitle: data.display_subtitle,
      run_id: data.run_id,
    };
    document.getElementById(containerId).innerHTML = [
      '<div class="run-detail-section">',
        '<h3>运行概览</h3>',
        renderRunOverview(overviewSummary),
      '</div>',
      '<div class="run-detail-section">',
        '<h3>关键指标</h3>',
        renderRunMetricGrid(metricItems),
      '</div>',
      '<div class="run-detail-section">',
        '<h3>步骤耗时</h3>',
        renderRunSteps(summary.steps || []),
      '</div>',
      '<div class="run-detail-section">',
        '<h3>配置摘要</h3>',
        renderRunConfigTable(configItems),
      '</div>',
    ].join("");
  }

  function renderRunOverview(summary) {
    return '<div class="run-overview-grid">' +
      [
        ["Pipeline", summary.display_name],
        ["状态", summary.status_reason ? (summary.status || "--") + " · " + summary.status_reason : summary.status],
        ["Run ID", summary.run_id],
        ["开始", summary.started_at],
        ["结束", summary.finished_at],
        ["Run目录", summary.run_dir],
      ].map(([key, value]) => (
        '<div class="run-overview-item">' +
          '<div class="metric-label">' + escHtml(key) + '</div>' +
          '<div class="run-overview-value">' + escHtml(value || "--") + '</div>' +
        '</div>'
      )).join("") +
    '</div>';
  }

  function renderRunMetricGrid(items) {
    if (!items.length) return '<div class="empty-state">暂无指标</div>';
    return '<div class="run-metric-grid">' + items.map(([label, value]) => (
      '<div class="mini-card">' +
        '<div class="metric-label">' + escHtml(label) + '</div>' +
        '<div class="metric-value">' + escHtml(fmtNum(value)) + '</div>' +
      '</div>'
    )).join("") + '</div>';
  }

  function renderRunSteps(steps) {
    if (!steps.length) return '<div class="empty-state">暂无步骤</div>';
    return '<div class="run-step-table-wrap"><table class="markdown-table"><thead><tr>' +
      '<th>步骤</th><th>状态</th><th>耗时</th><th>信息</th>' +
      '</tr></thead><tbody>' +
      steps.map(step => (
        '<tr>' +
          '<td>' + escHtml(step.name || "--") + '</td>' +
          '<td><span class="state-tag ' + escAttr(step.status || "") + '">' + escHtml(step.status || "--") + '</span></td>' +
          '<td>' + escHtml(step.seconds != null ? step.seconds + "s" : "--") + '</td>' +
          '<td>' + escHtml(step.message || "") + '</td>' +
        '</tr>'
      )).join("") +
      '</tbody></table></div>';
  }

  function renderRunConfigTable(items) {
    if (!items.length) return '<div class="empty-state">暂无配置快照</div>';
    return '<div class="run-config-table-wrap"><table class="markdown-table"><tbody>' +
      items.map(([key, value]) => (
        '<tr><th>' + escHtml(key) + '</th><td>' + escHtml(String(value)) + '</td></tr>'
      )).join("") +
      '</tbody></table></div>';
  }
})();
