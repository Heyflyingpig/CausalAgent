const test = require('node:test');
const assert = require('node:assert/strict');

const layoutState = require('../../../app/static/js/chat_layout_state.js');

test('new or empty history resolves to the new-chat state', () => {
    assert.equal(layoutState.stateForHistory([]), layoutState.NEW_CHAT);
    assert.equal(layoutState.stateForHistory(null), layoutState.NEW_CHAT);
});

test('history with messages resolves directly to the conversation state', () => {
    assert.equal(
        layoutState.stateForHistory([{ sender: 'user', text: '问题' }]),
        layoutState.CONVERSATION,
    );
});

test('the first successful send changes state once', () => {
    const state = layoutState.createState();

    assert.equal(layoutState.beginSend(state), true);
    assert.equal(layoutState.setState(state, layoutState.CONVERSATION), true);
    layoutState.endSend(state);

    assert.equal(layoutState.setState(state, layoutState.CONVERSATION), false);
});

test('a failed send releases the guard and keeps the new-chat state', () => {
    const state = layoutState.createState();

    assert.equal(layoutState.beginSend(state), true);
    layoutState.endSend(state);

    assert.equal(state.current, layoutState.NEW_CHAT);
    assert.equal(layoutState.beginSend(state), true);
});

test('send failure restores a blank input without overwriting user edits', () => {
    assert.equal(layoutState.restoreDraft('', '待发送的问题'), '待发送的问题');
    assert.equal(
        layoutState.restoreDraft('用户在请求期间的修改', '原始问题'),
        '用户在请求期间的修改',
    );
});
