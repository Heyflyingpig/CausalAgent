(function exposeChatLayoutState(globalScope) {
    'use strict';

    const NEW_CHAT = 'new-chat';
    const CONVERSATION = 'conversation';
    const VALID_STATES = new Set([NEW_CHAT, CONVERSATION]);

    function normalizeState(state) {
        return VALID_STATES.has(state) ? state : NEW_CHAT;
    }

    function createState(initialState = NEW_CHAT) {
        return {
            current: normalizeState(initialState),
            sendInFlight: false,
        };
    }

    function stateForHistory(messages) {
        return Array.isArray(messages) && messages.length > 0
            ? CONVERSATION
            : NEW_CHAT;
    }

    function setState(state, nextState) {
        const normalizedState = normalizeState(nextState);
        const changed = state.current !== normalizedState;
        state.current = normalizedState;
        return changed;
    }

    function beginSend(state) {
        if (state.sendInFlight) return false;
        state.sendInFlight = true;
        return true;
    }

    function endSend(state) {
        state.sendInFlight = false;
    }

    function restoreDraft(currentValue, draftValue) {
        const current = String(currentValue ?? '');
        return current.trim() ? current : String(draftValue ?? '');
    }

    const api = {
        NEW_CHAT,
        CONVERSATION,
        createState,
        stateForHistory,
        setState,
        beginSend,
        endSend,
        restoreDraft,
    };
    globalScope.ChatLayoutState = api;
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }
}(typeof globalThis !== 'undefined' ? globalThis : window));
