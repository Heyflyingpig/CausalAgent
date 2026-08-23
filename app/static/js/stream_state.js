(function exposeChatStreamState(globalScope) {
    'use strict';

    function createState() {
        // 创建一个 job 订阅独占的传输与文字语义去重状态。
        return {
            seenEventIds: new Set(),
            seenTextEvents: new Set(),
            streams: new Map(),
        };
    }

    function acceptEventId(state, eventId) {
        // 使用数据库 SSE ID 防止重连事件被重复处理。
        if (!eventId) return true;
        if (state.seenEventIds.has(eventId)) return false;
        state.seenEventIds.add(eventId);
        return true;
    }

    function appendTextDelta(state, eventData) {
        // 按阶段、文字流和批次序号去重，并返回完整原始字符串。
        const key = `${eventData.step_id}:${eventData.stream_id}:${eventData.sequence}`;
        if (state.seenTextEvents.has(key)) {
            return { duplicate: true, buffer: state.streams.get(eventData.stream_id) || '' };
        }
        state.seenTextEvents.add(key);
        const buffer = (state.streams.get(eventData.stream_id) || '') + eventData.delta;
        state.streams.set(eventData.stream_id, buffer);
        return { duplicate: false, buffer };
    }

    function discardStream(state, streamId) {
        // 重试时只废弃失败生成实例，不影响新生成实例。
        return streamId ? state.streams.delete(streamId) : false;
    }

    function shouldCorrectDraft(hasDraft, result) {
        // 普通文字终态校正草稿；报告和因果图仍走一次性渲染。
        return Boolean(
            hasDraft
            && result
            && result.type === 'text'
            && result.layout !== 'report'
        );
    }

    const api = {
        createState,
        acceptEventId,
        appendTextDelta,
        discardStream,
        shouldCorrectDraft,
    };
    globalScope.ChatStreamState = api;
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }
}(typeof globalThis !== 'undefined' ? globalThis : window));
