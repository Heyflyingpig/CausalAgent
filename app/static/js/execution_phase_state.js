(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    root.ExecutionPhaseState = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    const HISTORY_EVENT_TYPES = new Set([
        'node_start', 'progress', 'decision', 'tool_call_start',
        'tool_call_result', 'node_retry', 'node_end',
    ]);
    const ACTIVE_PHASE_STATUSES = new Set(['queued', 'running']);

    function isHistoryEvent(type) {
        return HISTORY_EVENT_TYPES.has(type);
    }

    function isActivePhase(status) {
        return ACTIVE_PHASE_STATUSES.has(status);
    }

    function mergeActiveJob(existing, incoming) {
        const merged = { ...(existing || {}), ...(incoming || {}) };
        if (existing && existing.rendered_event_id !== undefined) {
            merged.rendered_event_id = Number(existing.rendered_event_id || 0);
            merged.last_event_id = merged.rendered_event_id;
        }
        return merged;
    }

    return { isHistoryEvent, isActivePhase, mergeActiveJob };
});
