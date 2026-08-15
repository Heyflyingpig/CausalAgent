(function exposeJobSubscriptionState(globalScope) {
    'use strict';

    function createState() {
        return {
            generations: new Map(),
            cancelInFlight: new Map(),
        };
    }

    function keyOf(jobId) {
        return jobId == null ? '' : String(jobId);
    }

    function nextGeneration(state, jobId) {
        const key = keyOf(jobId);
        if (!key) return 0;
        const generation = Number(state.generations.get(key) || 0) + 1;
        state.generations.set(key, generation);
        return generation;
    }

    function isCurrentGeneration(state, jobId, generation) {
        const key = keyOf(jobId);
        return Boolean(key) && state.generations.get(key) === generation;
    }

    function beginCancel(state, jobId, idempotencyKey) {
        const key = keyOf(jobId);
        if (!key || !idempotencyKey) return null;
        const existing = state.cancelInFlight.get(key);
        if (existing) return existing;
        state.cancelInFlight.set(key, String(idempotencyKey));
        return String(idempotencyKey);
    }

    function cancelKey(state, jobId) {
        return state.cancelInFlight.get(keyOf(jobId)) || null;
    }

    function isCancelInFlight(state, jobId) {
        return Boolean(cancelKey(state, jobId));
    }

    function finishCancel(state, jobId, idempotencyKey) {
        const key = keyOf(jobId);
        if (!key) return false;
        if (idempotencyKey === undefined || state.cancelInFlight.get(key) === idempotencyKey) {
            return state.cancelInFlight.delete(key);
        }
        return false;
    }

    function classifyCancelResponse(status, data) {
        const payload = data && typeof data === 'object' ? data : {};
        if (status === 409 && payload.code === 'job_state_conflict') {
            if (payload.status === 'canceled') {
                return { kind: 'reconciled', status: 'canceled' };
            }
            return { kind: 'conflict', status: payload.status || null };
        }
        if (status >= 200 && status < 300 && payload.success) {
            return { kind: 'accepted', status: payload.status || null };
        }
        return { kind: 'error', status: payload.status || null };
    }

    function classifyInputMode(job, cancelInFlight) {
        const status = job && job.status;
        if (status === 'waiting_input') {
            return cancelInFlight ? 'waiting_canceling' : 'waiting_input';
        }
        if (status === 'queued' || status === 'running') {
            return cancelInFlight ? 'running_canceling' : 'running';
        }
        return 'idle';
    }

    const api = {
        createState,
        keyOf,
        nextGeneration,
        invalidate: nextGeneration,
        isCurrentGeneration,
        beginCancel,
        cancelKey,
        isCancelInFlight,
        finishCancel,
        classifyCancelResponse,
        classifyInputMode,
    };
    globalScope.JobSubscriptionState = api;
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }
}(typeof globalThis !== 'undefined' ? globalThis : window));
