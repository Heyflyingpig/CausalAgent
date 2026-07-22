"use strict";

const observedTimes = [];
let overviewBlockingCount = 0;
let integrityBlockingCount = 0;
let overviewBlockingMessages = [];
let overviewBlockingKnown = false;
let integrityBlockingKnown = false;

function byId(id) {
    return document.getElementById(id);
}

function statusLabel(status) {
    return ({ healthy: '正常', warning: '警告', error: '异常', unknown: '未知' })[status] || '未知';
}

function displayValue(value, fallback = '—') {
    return value === null || value === undefined || value === '' ? fallback : String(value);
}

function formatDate(value) {
    if (!value) return '时间未知';
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString('zh-CN', { hour12: false });
}

function formatBytes(value) {
    const bytes = Number(value || 0);
    if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
    return `${(bytes / (1024 ** index)).toFixed(index === 0 ? 0 : 2)} ${units[index]}`;
}

function formatNumber(value) {
    if (value === null || value === undefined) return '—';
    const number = Number(value);
    return Number.isFinite(number) ? number.toLocaleString('zh-CN') : String(value);
}

function metaText(result) {
    if (!result) return '来源未知';
    const estimate = result.is_estimate ? ' · 估算' : '';
    return `${displayValue(result.source_alias, '来源未知')} · ${formatDate(result.observed_at)}${estimate}`;
}

function trackObservedAt(value) {
    if (!value) return;
    const timestamp = new Date(value).getTime();
    if (!Number.isNaN(timestamp)) observedTimes.push(timestamp);
    if (observedTimes.length) {
        byId('lastObservedAt').textContent = `最后采集：${formatDate(Math.max(...observedTimes))}`;
    }
}

function updateCard(cardId, result, value, detail) {
    const card = byId(cardId);
    const status = result?.status || 'unknown';
    card.classList.remove('status-healthy', 'status-warning', 'status-error', 'status-unknown');
    card.classList.add(`status-${status}`);
    card.querySelector('.status-badge').textContent = statusLabel(status);
    card.querySelector('.card-value').textContent = displayValue(value);
    card.querySelector('.card-detail').textContent = detail || result?.warning || '暂无补充信息';
    card.querySelector('.card-meta').textContent = metaText(result);
    trackObservedAt(result?.observed_at);
}

function addCell(row, value, className = '') {
    const cell = document.createElement('td');
    cell.textContent = displayValue(value);
    if (className) cell.className = className;
    row.appendChild(cell);
    return cell;
}

function addStatusCell(row, status) {
    const cell = document.createElement('td');
    const pill = document.createElement('span');
    pill.className = `result-pill ${status || 'unknown'}`;
    pill.textContent = statusLabel(status);
    cell.appendChild(pill);
    row.appendChild(cell);
}

function showTableState(tableId, stateId, rows, emptyMessage) {
    const table = byId(tableId);
    const state = byId(stateId);
    if (rows.length) {
        table.hidden = false;
        state.hidden = true;
    } else {
        table.hidden = true;
        state.hidden = false;
        state.classList.remove('error');
        state.textContent = emptyMessage;
    }
}

function showSectionError(tableId, stateId, message) {
    byId(tableId).hidden = true;
    const state = byId(stateId);
    state.hidden = false;
    state.classList.add('error');
    state.textContent = message;
}

function renderOverviewError(message) {
    const failed = {
        status: 'unknown',
        observed_at: null,
        source_alias: '来源未知',
        is_estimate: false,
        warning: message,
    };
    updateCard('revisionCard', failed, '未知', message);
    updateCard('primaryCard', failed, '未知', message);
    updateCard('replicaCard', failed, '未知', message);
    updateCard('connectionsCard', failed, '未知', message);
    overviewBlockingCount = 0;
    overviewBlockingMessages = [];
    overviewBlockingKnown = false;
    renderBlockingCard();
    byId('tablesMeta').textContent = '来源未知';
    showSectionError('tablesTable', 'tablesState', message);
}

async function fetchJson(url) {
    const response = await fetch(url, { headers: { Accept: 'application/json' } });
    if (response.status === 401 || response.status === 403) {
        window.location.assign('/');
        throw new Error('管理员会话无效');
    }
    const payload = await response.json();
    if (!response.ok || !payload.success) {
        throw new Error(payload.error || `请求失败 (${response.status})`);
    }
    return payload;
}

function renderBlockingCard() {
    if (!overviewBlockingKnown || !integrityBlockingKnown) {
        const pending = {
            status: 'unknown',
            observed_at: observedTimes.length ? new Date(Math.max(...observedTimes)).toISOString() : null,
            source_alias: '核心检查',
            is_estimate: false,
            warning: '等待核心状态与完整性检查完成',
        };
        updateCard('blockingCard', pending, '—', pending.warning);
        return;
    }
    const count = overviewBlockingCount + integrityBlockingCount;
    const result = {
        status: count > 0 ? 'error' : 'healthy',
        observed_at: observedTimes.length ? new Date(Math.max(...observedTimes)).toISOString() : null,
        source_alias: '核心检查',
        is_estimate: false,
        warning: null,
    };
    const detail = count > 0
        ? (overviewBlockingMessages[0] || '快速完整性检查发现阻塞项')
        : '未发现 revision、节点或完整性阻塞项';
    updateCard('blockingCard', result, count, detail);
}

function renderOverview(data) {
    const revision = data.revision;
    const revisionValue = revision.value || {};
    updateCard(
        'revisionCard',
        revision,
        revisionValue.matches === true ? '一致' : revisionValue.matches === false ? '不一致' : '未知',
        `仓库 ${displayValue((revisionValue.repository_heads || []).join(', '))} · 实例 ${displayValue((revisionValue.instance_revisions || []).join(', '))}`,
    );

    const primaryValue = data.primary.value || {};
    updateCard(
        'primaryCard',
        data.primary,
        primaryValue.connected ? '已连接' : '不可用',
        primaryValue.version ? `MySQL ${primaryValue.version}` : data.primary.warning,
    );

    const replicaValue = data.replica.value || {};
    const replicaSummary = !replicaValue.configured
        ? '未配置'
        : replicaValue.available ? `${displayValue(replicaValue.lag_seconds, '?')} 秒延迟` : '不可用';
    updateCard(
        'replicaCard',
        data.replica,
        replicaSummary,
        replicaValue.available
            ? (replicaValue.last_io_error || replicaValue.last_sql_error
                || `IO ${displayValue(replicaValue.io_running)} · SQL ${displayValue(replicaValue.sql_running)}`)
            : data.replica.warning,
    );

    const connectionsValue = data.connections.value || {};
    updateCard(
        'connectionsCard',
        data.connections,
        connectionsValue.utilization_percent === null || connectionsValue.utilization_percent === undefined
            ? '未知'
            : `${connectionsValue.utilization_percent}%`,
        `${formatNumber(connectionsValue.threads_connected)} / ${formatNumber(connectionsValue.max_connections)} 连接 · Running ${formatNumber(connectionsValue.threads_running)} · 历史峰值 ${formatNumber(connectionsValue.max_used_connections)}`,
    );

    overviewBlockingCount = (data.blocking_issues || []).length;
    overviewBlockingMessages = (data.blocking_issues || []).map(item => item.message);
    overviewBlockingKnown = ['revision', 'primary', 'replica', 'connections']
        .every(key => data[key]?.status !== 'unknown');

    const tables = data.tables.value || [];
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
    byId('tablesMeta').textContent = metaText(data.tables);
    trackObservedAt(data.observed_at);
    showTableState('tablesTable', 'tablesState', tables, data.tables.warning || '当前数据库没有可展示的表容量数据。');
    renderBlockingCard();
}

function renderIntegrity(data) {
    const checks = data.checks || [];
    const tbody = byId('integrityTable').querySelector('tbody');
    tbody.replaceChildren();
    checks.forEach(check => {
        const row = document.createElement('tr');
        addCell(row, check.label);
        addCell(row, formatNumber(check.value));
        addStatusCell(row, check.status);
        addCell(row, check.source_alias);
        tbody.appendChild(row);
    });
    integrityBlockingCount = Number(data.blocking_count || 0);
    integrityBlockingKnown = checks
        .filter(check => check.severity === 'blocking')
        .every(check => check.status !== 'unknown');
    const firstCheck = checks[0];
    byId('integrityMeta').textContent = firstCheck ? metaText(firstCheck) : `采集 ${formatDate(data.observed_at)}`;
    trackObservedAt(data.observed_at);
    showTableState('integrityTable', 'integrityState', checks, '没有返回快速完整性检查结果。');
    renderBlockingCard();
}

function renderSlowQueries(data) {
    byId('slowLogValue').textContent = displayValue(data.slow_query_log);
    byId('longQueryTimeValue').textContent = data.long_query_time === null || data.long_query_time === undefined
        ? '—' : `${data.long_query_time} 秒`;
    byId('slowQueriesValue').textContent = formatNumber(data.Slow_queries);
    byId('slowMeta').textContent = metaText(data);
    trackObservedAt(data.observed_at);

    const statements = data.top_statements || [];
    const tbody = byId('slowTable').querySelector('tbody');
    tbody.replaceChildren();
    statements.forEach(statement => {
        const row = document.createElement('tr');
        addCell(row, statement.digest_text, 'digest-cell');
        addCell(row, formatNumber(statement.count_star));
        addCell(row, `${displayValue(statement.total_seconds)} 秒`);
        addCell(row, `${displayValue(statement.avg_seconds)} 秒`);
        addCell(row, formatNumber(statement.rows_examined));
        addCell(row, formatNumber(statement.rows_sent));
        tbody.appendChild(row);
    });
    showTableState(
        'slowTable',
        'slowState',
        statements,
        data.warning || '当前节点没有可展示的慢查询 digest。',
    );
}

function renderJobs(payload) {
    const summary = payload.summary || {};
    byId('queuedValue').textContent = formatNumber(summary.queued);
    byId('runningValue').textContent = formatNumber(summary.running);
    byId('staleValue').textContent = formatNumber(summary.stale);
    byId('maxAttemptsValue').textContent = formatNumber(summary.max_attempts_running);
    byId('jobsMeta').textContent = metaText(payload.meta);
    trackObservedAt(payload.meta?.observed_at);

    const jobs = payload.data || [];
    const tbody = byId('jobsTable').querySelector('tbody');
    tbody.replaceChildren();
    jobs.forEach(job => {
        const row = document.createElement('tr');
        addCell(row, job.job_id);
        addCell(row, job.status);
        addCell(row, job.worker_id);
        addCell(row, `${formatNumber(job.attempt_count)} / ${formatNumber(job.max_attempts)}`);
        addCell(row, formatDate(job.heartbeat_at));
        addCell(row, formatDate(job.created_at));
        tbody.appendChild(row);
    });
    showTableState('jobsTable', 'jobsState', jobs, payload.meta?.warning || '当前没有 queued/running 任务。');
}

async function loadIdentity() {
    const response = await fetch('/api/check_auth', { headers: { Accept: 'application/json' } });
    const data = await response.json();
    if (!data.isLoggedIn || data.role !== 'admin') {
        window.location.assign('/');
        throw new Error('管理员会话无效');
    }
    byId('adminUsername').textContent = data.username;
}

async function refreshDashboard() {
    const refreshButton = byId('refreshButton');
    const notice = byId('pageNotice');
    refreshButton.disabled = true;
    refreshButton.textContent = '刷新中…';
    notice.hidden = true;
    observedTimes.length = 0;
    overviewBlockingKnown = false;
    integrityBlockingKnown = false;
    renderBlockingCard();

    const tasks = [
        loadIdentity(),
        fetchJson('/api/admin/db/overview')
            .then(payload => renderOverview(payload.data))
            .catch(error => {
                renderOverviewError(`数据库概览加载失败：${error.message}`);
                throw error;
            }),
        fetchJson('/api/admin/db/integrity?mode=quick')
            .then(payload => renderIntegrity(payload.data))
            .catch(error => {
                integrityBlockingCount = 0;
                integrityBlockingKnown = false;
                renderBlockingCard();
                byId('integrityMeta').textContent = '来源未知';
                showSectionError('integrityTable', 'integrityState', `快速完整性检查失败：${error.message}`);
                throw error;
            }),
        fetchJson('/api/admin/db/slow-queries?limit=20')
            .then(payload => renderSlowQueries(payload.data))
            .catch(error => {
                byId('slowMeta').textContent = '来源未知';
                showSectionError('slowTable', 'slowState', `慢查询摘要加载失败：${error.message}`);
                throw error;
            }),
        fetchJson('/api/admin/jobs/workers')
            .then(renderJobs)
            .catch(error => {
                byId('jobsMeta').textContent = '来源未知';
                showSectionError('jobsTable', 'jobsState', `Worker / Job 快照加载失败：${error.message}`);
                throw error;
            }),
    ];
    const results = await Promise.allSettled(tasks);
    const errors = results
        .filter(result => result.status === 'rejected')
        .map(result => result.reason?.message || '未知错误');
    if (errors.length) {
        notice.textContent = `部分区块加载失败：${[...new Set(errors)].join('；')}`;
        notice.hidden = false;
    }
    refreshButton.disabled = false;
    refreshButton.textContent = '手动刷新';
}

async function logout() {
    const button = byId('logoutButton');
    button.disabled = true;
    try {
        await fetch('/api/logout', { method: 'POST', headers: { Accept: 'application/json' } });
    } finally {
        window.location.assign('/');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    byId('refreshButton').addEventListener('click', refreshDashboard);
    byId('logoutButton').addEventListener('click', logout);
    refreshDashboard();
});
