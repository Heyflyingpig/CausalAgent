"use strict";

const REFRESH_GROUP_KEYS = ['realtime', 'sql_performance', 'capacity'];
const MANUAL_REFRESH_TIMEOUT_MS = 60000;
const MANUAL_POLL_INTERVAL_MS = 1500;

const observedTimes = [];
let latestDashboard = null;
let refreshPolicy = {};
let autoRefreshTimer = null;
let dashboardRequest = null;

// 按 ID 获取页面元素。
function byId(id) {
    return document.getElementById(id);
}

// 判断值是否为普通对象。
function isObject(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

// 将监控状态转换为中文标签。
function statusLabel(status) {
    return ({ healthy: '正常', warning: '警告', error: '异常', unknown: '未知' })[status] || '未知';
}

// 将空值转换为页面占位符。
function displayValue(value, fallback = '—') {
    return value === null || value === undefined || value === '' ? fallback : String(value);
}

// 将采集时间格式化为本地时间。
function formatDate(value) {
    if (!value) return '时间未知';
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime())
        ? String(value)
        : parsed.toLocaleString('zh-CN', { hour12: false });
}

// 将字节数转换为易读容量。
function formatBytes(value) {
    const bytes = Number(value || 0);
    if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
    return `${(bytes / (1024 ** index)).toFixed(index === 0 ? 0 : 2)} ${units[index]}`;
}

// 将数值转换为本地化文本。
function formatNumber(value) {
    if (value === null || value === undefined || value === '') return '—';
    const number = Number(value);
    return Number.isFinite(number) ? number.toLocaleString('zh-CN') : String(value);
}

// 读取兼容旧采集结构的指标值。
function metricValue(metric) {
    if (isObject(metric) && Object.prototype.hasOwnProperty.call(metric, 'value')) {
        return metric.value;
    }
    return metric;
}

// 合并分组快照与组内指标的展示元数据。
function metricResult(metric, group) {
    return {
        ...(isObject(group) ? group : {}),
        ...(isObject(metric) ? metric : {}),
        observed_at: metric?.observed_at || group?.observed_at || null,
        source_alias: metric?.source_alias || group?.source_alias || '共享监控快照',
    };
}

// 生成来源、采集时间和快照状态文本。
function metaText(result) {
    if (!result) return '尚无快照';
    const suffixes = [];
    if (result.is_estimate) suffixes.push('估算');
    if (result.is_stale) suffixes.push('已过期');
    if (result.refresh_pending) suffixes.push('刷新排队中');
    const suffix = suffixes.length ? ` · ${suffixes.join(' · ')}` : '';
    return `${displayValue(result.source_alias, '共享监控快照')} · ${formatDate(result.observed_at)}${suffix}`;
}

// 记录本次响应中的采集时间。
function trackObservedAt(value) {
    if (!value) return;
    const timestamp = new Date(value).getTime();
    if (!Number.isNaN(timestamp)) observedTimes.push(timestamp);
}

// 更新页头的全局最后采集时间。
function renderLastObservedAt() {
    byId('lastObservedAt').textContent = observedTimes.length
        ? `最后采集：${formatDate(Math.max(...observedTimes))}`
        : '尚未生成监控快照';
}

// 返回快照的有效展示状态。
function displayStatus(result) {
    if (!result) return 'unknown';
    if (result.is_stale && result.status === 'healthy') return 'warning';
    return result.status || 'unknown';
}

// 更新顶部状态卡片。
function updateCard(cardId, result, value, detail) {
    const card = byId(cardId);
    const status = displayStatus(result);
    card.classList.remove('status-healthy', 'status-warning', 'status-error', 'status-unknown');
    card.classList.add(`status-${status}`);
    card.querySelector('.status-badge').textContent = statusLabel(status);
    card.querySelector('.card-value').textContent = displayValue(value);
    card.querySelector('.card-detail').textContent = detail || result?.warning || '暂无补充信息';
    card.querySelector('.card-meta').textContent = metaText(result);
    trackObservedAt(result?.observed_at);
}

// 向表格行追加普通文本单元格。
function addCell(row, value, className = '') {
    const cell = document.createElement('td');
    cell.textContent = displayValue(value);
    if (className) cell.className = className;
    row.appendChild(cell);
    return cell;
}

// 向表格行追加状态标签单元格。
function addStatusCell(row, status) {
    const cell = document.createElement('td');
    const pill = document.createElement('span');
    pill.className = `result-pill ${status || 'unknown'}`;
    pill.textContent = statusLabel(status);
    cell.appendChild(pill);
    row.appendChild(cell);
}

// 同步表格及其空态、警告态或错误态。
function renderTableState(tableId, stateId, rows, message = '', tone = '') {
    const table = byId(tableId);
    const state = byId(stateId);
    table.hidden = rows.length === 0;
    state.classList.remove('error', 'warning');
    if (tone) state.classList.add(tone);
    state.textContent = message;
    state.hidden = !message;
}

// 在页面顶部展示一次状态通知。
function setNotice(message = '', tone = 'error') {
    const notice = byId('pageNotice');
    notice.hidden = !message;
    notice.textContent = message;
    notice.classList.remove('info', 'warning');
    if (message && tone !== 'error') notice.classList.add(tone);
}

// 读取 JSON API，并统一处理身份失效和业务错误。
async function fetchJson(url, options = {}) {
    const response = await fetch(url, {
        ...options,
        headers: { Accept: 'application/json', ...(options.headers || {}) },
    });
    if (response.status === 401 || response.status === 403) {
        window.location.assign('/');
        throw new Error('管理员会话无效');
    }
    let payload;
    try {
        payload = await response.json();
    } catch (_error) {
        throw new Error(`服务端返回了无效响应 (${response.status})`);
    }
    if (!response.ok || !payload.success) {
        throw new Error(payload.error || `请求失败 (${response.status})`);
    }
    return payload;
}

// 提取阻塞项中的可读消息。
function issueMessage(issue) {
    if (typeof issue === 'string') return issue;
    return issue?.message || issue?.label || '发现未命名阻塞项';
}

// 渲染仓库 revision 和表容量快照。
function renderCapacity(group = {}) {
    const revisionMetric = group.revision;
    const revision = metricValue(revisionMetric) || {};
    const revisionMeta = metricResult(revisionMetric, group);
    const repositoryHeads = revision.repository_heads || [];
    const instanceRevisions = revision.instance_revisions || [];
    const revisionValue = revision.matches === true
        ? '一致'
        : revision.matches === false ? '不一致' : '未知';
    updateCard(
        'revisionCard',
        revisionMeta,
        revisionValue,
        `仓库 ${displayValue(repositoryHeads.join(', '))} · 实例 ${displayValue(instanceRevisions.join(', '))}`,
    );

    const tablesMetric = group.tables;
    const tableValue = metricValue(tablesMetric);
    const tables = Array.isArray(tableValue) ? tableValue : [];
    const tbody = byId('tablesTable').querySelector('tbody');
    tbody.replaceChildren();
    tables.forEach(table => {
        const row = document.createElement('tr');
        addCell(row, table.table_name);
        addCell(row, formatNumber(table.table_rows));
        addCell(row, formatBytes(table.data_length));
        addCell(row, formatBytes(table.index_length));
        addCell(row, formatBytes(table.total_length));
        tbody.appendChild(row);
    });

    const tablesMeta = metricResult(tablesMetric, group);
    byId('tablesMeta').textContent = metaText(tablesMeta);
    trackObservedAt(group.observed_at);
    let message = '';
    let tone = '';
    if (group.refresh_pending) {
        message = '表容量刷新请求已登记，正在等待 monitor 完成采集。';
        tone = 'warning';
    } else if (group.is_stale) {
        message = '表容量快照已过期，当前展示的是最近一次可用结果。';
        tone = 'warning';
    } else if (group.warning || tablesMeta.warning) {
        message = group.warning || tablesMeta.warning;
        tone = displayStatus(group) === 'error' ? 'error' : 'warning';
    } else if (!tables.length) {
        message = group.observed_at ? '当前数据库没有可展示的表容量数据。' : '表容量快照尚未生成。';
    }
    renderTableState('tablesTable', 'tablesState', tables, message, tone);
}

// 渲染主从、连接和 Worker/Job 实时快照。
function renderRealtime(group = {}) {
    const primaryMetric = group.primary;
    const primary = metricValue(primaryMetric) || {};
    const primaryMeta = metricResult(primaryMetric, group);
    const primaryValue = primary.connected === true
        ? '已连接'
        : primary.connected === false ? '不可用' : statusLabel(displayStatus(primaryMeta));
    updateCard('primaryCard', primaryMeta, primaryValue,
        primary.version ? `MySQL ${primary.version}` : primaryMeta.warning);

    const replicaMetric = group.replica;
    const replica = metricValue(replicaMetric) || {};
    const replicaMeta = metricResult(replicaMetric, group);
    const replicaSummary = replica.configured === false
        ? '未配置'
        : replica.available === true
            ? `${displayValue(replica.lag_seconds, '?')} 秒延迟`
            : replica.available === false ? '不可用' : statusLabel(displayStatus(replicaMeta));
    updateCard(
        'replicaCard',
        replicaMeta,
        replicaSummary,
        replica.available
            ? (replica.last_io_error || replica.last_sql_error
                || `IO ${displayValue(replica.io_running)} · SQL ${displayValue(replica.sql_running)}`)
            : replicaMeta.warning,
    );

    const connectionsMetric = group.connections;
    const connections = metricValue(connectionsMetric) || {};
    const connectionsMeta = metricResult(connectionsMetric, group);
    updateCard(
        'connectionsCard',
        connectionsMeta,
        connections.utilization_percent === null || connections.utilization_percent === undefined
            ? '未知'
            : `${connections.utilization_percent}%`,
        `${formatNumber(connections.threads_connected)} / ${formatNumber(connections.max_connections)} 连接 · Running ${formatNumber(connections.threads_running)} · 历史峰值 ${formatNumber(connections.max_used_connections)}`,
    );

    renderJobs(group.jobs, group);
    trackObservedAt(group.observed_at);
}

// 渲染 Worker/Job 汇总及活动任务列表。
function renderJobs(jobsMetric, realtimeGroup = {}) {
    const jobs = metricValue(jobsMetric) || {};
    const summary = jobs.summary || jobs;
    byId('queuedValue').textContent = formatNumber(summary.queued);
    byId('runningValue').textContent = formatNumber(summary.running);
    byId('staleValue').textContent = formatNumber(summary.stale);
    byId('maxAttemptsValue').textContent = formatNumber(summary.max_attempts_running);

    const jobsMeta = metricResult(jobs.meta || jobsMetric, realtimeGroup);
    byId('jobsMeta').textContent = metaText(jobsMeta);
    const rows = jobs.data || jobs.jobs || jobs.active_jobs || [];
    const safeRows = Array.isArray(rows) ? rows : [];
    const tbody = byId('jobsTable').querySelector('tbody');
    tbody.replaceChildren();
    safeRows.forEach(job => {
        const row = document.createElement('tr');
        addCell(row, job.job_id);
        addCell(row, job.status);
        addCell(row, job.worker_id);
        addCell(row, `${formatNumber(job.attempt_count)} / ${formatNumber(job.max_attempts)}`);
        addCell(row, formatDate(job.heartbeat_at));
        addCell(row, formatDate(job.created_at));
        tbody.appendChild(row);
    });

    let message = '';
    let tone = '';
    if (realtimeGroup.refresh_pending) {
        message = '实时状态刷新请求已登记，正在等待 monitor 完成采集。';
        tone = 'warning';
    } else if (realtimeGroup.is_stale) {
        message = 'Worker / Job 快照已过期，monitor 可能未正常运行。';
        tone = 'warning';
    } else if (realtimeGroup.warning || jobsMeta.warning) {
        message = realtimeGroup.warning || jobsMeta.warning;
        tone = displayStatus(realtimeGroup) === 'error' ? 'error' : 'warning';
    } else if (!safeRows.length) {
        message = realtimeGroup.observed_at ? '当前没有 queued/running 任务。' : '实时状态快照尚未生成。';
    }
    renderTableState('jobsTable', 'jobsState', safeRows, message, tone);
}

// 渲染低频完整性审计快照和明确的未执行状态。
function renderIntegrity(group = {}, policy = {}) {
    const checks = Array.isArray(group.checks) ? group.checks : [];
    const tbody = byId('integrityTable').querySelector('tbody');
    tbody.replaceChildren();
    checks.forEach(check => {
        const row = document.createElement('tr');
        addCell(row, check.label || check.name);
        addCell(row, formatNumber(check.value));
        addStatusCell(row, check.status);
        addCell(row, check.source_alias || group.source_alias || '共享监控快照');
        tbody.appendChild(row);
    });

    byId('integrityMeta').textContent = metaText(group);
    trackObservedAt(group.observed_at);
    let message = '';
    let tone = '';
    if (group.refresh_pending) {
        message = '完整性审计请求已登记，正在等待 monitor 执行。';
        tone = 'warning';
    } else if (!group.observed_at) {
        message = policy.integrity_enabled
            ? '完整性审计尚未执行，monitor 将按低频策略采集；也可立即手动执行。'
            : '完整性定时审计已关闭，尚无审计结果；可点击“执行完整性审计”。';
        tone = 'warning';
    } else if (group.is_stale) {
        message = '完整性审计快照已过期，当前结果仅供参考；可手动重新执行。';
        tone = 'warning';
    } else if (group.warning) {
        message = group.warning;
        tone = displayStatus(group) === 'error' ? 'error' : 'warning';
    } else if (!checks.length) {
        message = '最近一次审计没有返回可展示的检查项。';
    } else if (!policy.integrity_enabled) {
        message = '完整性定时审计已关闭；当前展示最近一次手动或迁移后审计结果。';
        tone = 'warning';
    }
    renderTableState('integrityTable', 'integrityState', checks, message, tone);
}

// 渲染慢查询周期增量和按累计总耗时排序的 SQL digest。
function renderSqlPerformance(group = {}) {
    byId('slowLogValue').textContent = displayValue(group.slow_query_log);
    byId('longQueryTimeValue').textContent = group.long_query_time === null
        || group.long_query_time === undefined ? '—' : `${group.long_query_time} 秒`;

    const delta = group.slow_queries_delta;
    byId('slowQueriesDeltaValue').textContent = delta === null || delta === undefined
        ? (group.baseline_reset ? '基线重建中' : '—')
        : formatNumber(delta);
    byId('slowWindowValue').textContent = group.window_seconds === null
        || group.window_seconds === undefined ? '—' : `${formatNumber(group.window_seconds)} 秒`;
    byId('slowQueriesTotalValue').textContent = formatNumber(
        group.slow_queries_total ?? group.Slow_queries,
    );

    const threshold = group.slow_query_warning_threshold;
    byId('slowMeta').textContent = `${metaText(group)}${threshold === null || threshold === undefined
        ? '' : ` · 增量告警阈值 ${formatNumber(threshold)}`}`;
    trackObservedAt(group.observed_at);

    const statements = group.high_load_statements || group.top_statements || [];
    const safeStatements = Array.isArray(statements) ? statements : [];
    const tbody = byId('slowTable').querySelector('tbody');
    tbody.replaceChildren();
    safeStatements.forEach(statement => {
        const row = document.createElement('tr');
        addCell(row, statement.digest_text || statement.digest, 'digest-cell');
        addCell(row, formatNumber(statement.count_star ?? statement.execution_count));
        addCell(row, `${displayValue(statement.total_seconds)} 秒`);
        addCell(row, `${displayValue(statement.avg_seconds)} 秒`);
        addCell(row, formatNumber(statement.rows_examined));
        addCell(row, formatNumber(statement.rows_sent));
        tbody.appendChild(row);
    });

    let message = '';
    let tone = '';
    if (group.refresh_pending) {
        message = 'SQL 性能刷新请求已登记，正在等待 monitor 完成采集。';
        tone = 'warning';
    } else if (!group.observed_at) {
        message = 'SQL 性能快照尚未生成。';
        tone = 'warning';
    } else if (group.is_stale) {
        message = 'SQL 性能快照已过期，当前展示的是最近一次可用结果。';
        tone = 'warning';
    } else if (group.warning) {
        message = group.warning;
        tone = displayStatus(group) === 'error' ? 'error' : 'warning';
    } else if (!safeStatements.length) {
        message = 'Performance Schema 当前没有可展示的高负载 SQL digest。';
    }
    renderTableState('slowTable', 'slowState', safeStatements, message, tone);
}

// 汇总核心状态与审计结果，避免未审计时永久显示等待。
function renderBlockingCard(data = {}) {
    const realtime = data.realtime || {};
    const capacity = data.capacity || {};
    const integrity = data.integrity || {};
    const issues = [
        ...(Array.isArray(realtime.blocking_issues) ? realtime.blocking_issues : []),
        ...(Array.isArray(capacity.blocking_issues) ? capacity.blocking_issues : []),
    ];
    const integrityCount = Number(integrity.blocking_count || 0);
    const count = issues.length + integrityCount;
    const coreKnown = Boolean(realtime.observed_at && capacity.observed_at);
    const integrityKnown = Boolean(integrity.observed_at);
    const integrityStale = Boolean(integrity.is_stale);
    const groupStatuses = [
        ['实时状态', displayStatus(realtime)],
        ['容量状态', displayStatus(capacity)],
        ['完整性审计', displayStatus(integrity)],
    ];
    const errorGroup = groupStatuses.find(([, groupStatus]) => groupStatus === 'error');
    const uncertainGroup = groupStatuses.find(([, groupStatus]) => (
        groupStatus === 'warning' || groupStatus === 'unknown'
    ));

    let status = 'healthy';
    let detail = '未发现 revision、节点或完整性阻塞项';
    if (count > 0) {
        status = 'error';
        detail = issues.length ? issueMessage(issues[0]) : `完整性审计发现 ${integrityCount} 个阻塞项`;
    } else if (errorGroup) {
        status = 'error';
        detail = `${errorGroup[0]}采集异常，当前不能确认不存在阻塞项`;
    } else if (!coreKnown) {
        status = 'unknown';
        detail = '核心状态快照尚未生成，请确认 monitor 正常运行';
    } else if (!integrityKnown) {
        status = 'warning';
        detail = refreshPolicy.integrity_enabled
            ? '核心状态未发现阻塞；完整性审计尚未执行'
            : '核心状态未发现阻塞；完整性定时审计已关闭且尚未手动执行';
    } else if (integrityStale) {
        status = 'warning';
        detail = '核心状态未发现阻塞；完整性审计快照已过期';
    } else if (uncertainGroup) {
        status = 'warning';
        detail = `${uncertainGroup[0]}结果不完整，当前不能确认不存在阻塞项`;
    }

    const observedAt = [realtime.observed_at, capacity.observed_at, integrity.observed_at]
        .filter(Boolean)
        .sort()
        .at(-1) || null;
    updateCard('blockingCard', {
        status,
        observed_at: observedAt,
        source_alias: '共享监控快照',
        is_stale: Boolean(realtime.is_stale || capacity.is_stale),
        warning: detail,
    }, count, detail);
}

// 渲染服务端返回的有效刷新策略。
function renderRefreshPolicy(policy = {}) {
    const enabled = policy.auto_refresh_enabled === true;
    const realtimeSeconds = Number(policy.realtime_interval_seconds);
    const sqlSeconds = Number(policy.sql_interval_seconds);
    const capacitySeconds = Number(policy.table_capacity_interval_seconds);
    const policyComplete = [realtimeSeconds, sqlSeconds, capacitySeconds]
        .every(value => Number.isFinite(value) && value > 0);
    byId('refreshPolicyText').textContent = !enabled
        ? '自动刷新已关闭 · 可手动刷新共享快照'
        : policyComplete
            ? `自动读取 ${realtimeSeconds} 秒 · SQL ${sqlSeconds} 秒 · 容量 ${capacitySeconds} 秒`
            : '自动刷新策略不可用 · 可手动刷新共享快照';
}

// 渲染单次 dashboard 响应的全部分层快照。
function renderDashboard(data) {
    observedTimes.length = 0;
    refreshPolicy = data.refresh_policy || {};
    renderRefreshPolicy(refreshPolicy);
    renderRealtime(data.realtime || {});
    renderCapacity(data.capacity || {});
    renderSqlPerformance(data.sql_performance || {});
    renderIntegrity(data.integrity || {}, refreshPolicy);
    renderBlockingCard(data);
    renderLastObservedAt();
}

// 在首次 dashboard 请求失败时为所有区域展示降级状态。
function renderDashboardError(message) {
    const failed = {
        status: 'unknown',
        observed_at: null,
        source_alias: '共享监控快照',
        warning: message,
    };
    updateCard('revisionCard', failed, '未知', message);
    updateCard('primaryCard', failed, '未知', message);
    updateCard('replicaCard', failed, '未知', message);
    updateCard('connectionsCard', failed, '未知', message);
    updateCard('blockingCard', failed, '—', message);
    byId('tablesMeta').textContent = '尚无快照';
    byId('integrityMeta').textContent = '尚无快照';
    byId('slowMeta').textContent = '尚无快照';
    byId('jobsMeta').textContent = '尚无快照';
    renderTableState('tablesTable', 'tablesState', [], message, 'error');
    renderTableState('integrityTable', 'integrityState', [], message, 'error');
    renderTableState('slowTable', 'slowState', [], message, 'error');
    renderTableState('jobsTable', 'jobsState', [], message, 'error');
    renderLastObservedAt();
}

// 校验当前登录态并展示管理员身份。
async function loadIdentity() {
    const response = await fetch('/api/check_auth', { headers: { Accept: 'application/json' } });
    const data = await response.json();
    if (!data.isLoggedIn || data.role !== 'admin') {
        window.location.assign('/');
        throw new Error('管理员会话无效');
    }
    byId('adminUsername').textContent = data.username;
}

// 清除现有浏览器自动读取计时器。
function clearAutoRefresh() {
    if (autoRefreshTimer !== null) {
        window.clearTimeout(autoRefreshTimer);
        autoRefreshTimer = null;
    }
}

// 根据服务端策略安排下一次轻量 dashboard 读取。
function scheduleAutoRefresh() {
    clearAutoRefresh();
    if (refreshPolicy.auto_refresh_enabled !== true) return;
    const seconds = Number(refreshPolicy.realtime_interval_seconds);
    if (!Number.isFinite(seconds) || seconds <= 0) return;
    autoRefreshTimer = window.setTimeout(() => {
        loadDashboard({ scheduleNext: true, quiet: true });
    }, seconds * 1000);
}

// 获取共享 dashboard 快照，并复用并发请求。
async function loadDashboard({ scheduleNext = true, quiet = false } = {}) {
    if (dashboardRequest) return dashboardRequest;
    dashboardRequest = fetchJson('/api/admin/db/dashboard', { cache: 'no-store' })
        .then(payload => {
            latestDashboard = payload.data || {};
            renderDashboard(latestDashboard);
            if (!quiet) setNotice();
            return latestDashboard;
        })
        .catch(error => {
            if (!latestDashboard) renderDashboardError(`数据库看板加载失败：${error.message}`);
            setNotice(`数据库看板加载失败：${error.message}`);
            throw error;
        })
        .finally(() => {
            dashboardRequest = null;
            if (scheduleNext) scheduleAutoRefresh();
        });
    return dashboardRequest;
}

// 等待指定分组的共享刷新请求被 monitor 消费。
function snapshotObservedRequest(group, requestedAt) {
    if (!group || group.refresh_pending === true || !requestedAt) return false;
    const observedTime = new Date(group.observed_at).getTime();
    const requestedTime = new Date(requestedAt).getTime();
    return Number.isFinite(observedTime)
        && Number.isFinite(requestedTime)
        && observedTime >= requestedTime;
}

// 等待指定分组生成不早于本次请求时间的共享快照。
async function pollUntilSettled(groupKeys, requestedAt) {
    const deadline = Date.now() + MANUAL_REFRESH_TIMEOUT_MS;
    while (Date.now() < deadline) {
        const data = await loadDashboard({ scheduleNext: false, quiet: true });
        const completed = groupKeys.every(key => snapshotObservedRequest(data[key], requestedAt));
        if (completed) return true;
        await new Promise(resolve => window.setTimeout(resolve, MANUAL_POLL_INTERVAL_MS));
    }
    return false;
}

// 登记普通三组刷新并轮询到完成或超时。
async function requestSharedRefresh() {
    const button = byId('refreshButton');
    clearAutoRefresh();
    button.disabled = true;
    button.textContent = '请求刷新中…';
    try {
        const response = await fetchJson('/api/admin/db/refresh', { method: 'POST' });
        const requestedAt = response.data?.requested_at;
        setNotice('普通刷新请求已登记，正在等待 realtime、SQL 性能和表容量快照更新。', 'info');
        const completed = await pollUntilSettled(REFRESH_GROUP_KEYS, requestedAt);
        setNotice(
            completed ? '共享监控快照已刷新。' : '刷新仍在后台进行，请确认 monitor 是否正常运行。',
            completed ? 'info' : 'warning',
        );
    } catch (error) {
        setNotice(`手动刷新失败：${error.message}`);
    } finally {
        button.disabled = false;
        button.textContent = '手动刷新';
        scheduleAutoRefresh();
    }
}

// 登记独立完整性审计并轮询到完成或超时。
async function requestIntegrityAudit() {
    const button = byId('integrityButton');
    clearAutoRefresh();
    button.disabled = true;
    button.textContent = '审计请求中…';
    try {
        const response = await fetchJson('/api/admin/db/integrity/run', { method: 'POST' });
        const requestedAt = response.data?.requested_at;
        setNotice('完整性审计请求已登记，正在等待 monitor 完成审计。', 'info');
        const completed = await pollUntilSettled(['integrity'], requestedAt);
        setNotice(
            completed ? '完整性审计快照已更新。' : '审计仍在后台进行，请确认 monitor 是否正常运行。',
            completed ? 'info' : 'warning',
        );
    } catch (error) {
        setNotice(`完整性审计请求失败：${error.message}`);
    } finally {
        button.disabled = false;
        button.textContent = '执行完整性审计';
        scheduleAutoRefresh();
    }
}

// 注销当前管理员并返回登录页。
async function logout() {
    const button = byId('logoutButton');
    button.disabled = true;
    try {
        await fetch('/api/logout', { method: 'POST', headers: { Accept: 'application/json' } });
    } finally {
        window.location.assign('/');
    }
}

// 初始化页面事件、身份校验和首次快照读取。
async function initializeDashboard() {
    byId('refreshButton').addEventListener('click', requestSharedRefresh);
    byId('integrityButton').addEventListener('click', requestIntegrityAudit);
    byId('logoutButton').addEventListener('click', logout);
    try {
        await loadIdentity();
        await loadDashboard();
    } catch (_error) {
        // 身份错误会跳转；看板错误已经在各区块中降级展示。
    }
}

document.addEventListener('DOMContentLoaded', initializeDashboard);
