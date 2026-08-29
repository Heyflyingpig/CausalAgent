const test = require('node:test');
const assert = require('node:assert/strict');

const streamState = require('../../../app/static/js/stream_state.js');

test('transport event IDs are accepted once', () => {
    const state = streamState.createState();
    assert.equal(streamState.acceptEventId(state, '12'), true);
    assert.equal(streamState.acceptEventId(state, '12'), false);
});

test('text deltas use semantic keys and preserve the raw full buffer', () => {
    const state = streamState.createState();
    const first = {
        step_id: 'step-1', stream_id: 'stream-1', sequence: 1, delta: '**hello',
    };
    const second = {
        step_id: 'step-1', stream_id: 'stream-1', sequence: 2, delta: '**',
    };

    assert.deepEqual(streamState.appendTextDelta(state, first), {
        duplicate: false, buffer: '**hello',
    });
    assert.deepEqual(streamState.appendTextDelta(state, first), {
        duplicate: true, buffer: '**hello',
    });
    assert.deepEqual(streamState.appendTextDelta(state, second), {
        duplicate: false, buffer: '**hello**',
    });
});

test('retry discards only the failed stream', () => {
    const state = streamState.createState();
    streamState.appendTextDelta(state, {
        step_id: 'step-1', stream_id: 'old', sequence: 1, delta: 'old draft',
    });
    streamState.appendTextDelta(state, {
        step_id: 'step-1', stream_id: 'new', sequence: 1, delta: 'new draft',
    });

    assert.equal(streamState.discardStream(state, 'old'), true);
    assert.equal(state.streams.has('old'), false);
    assert.equal(state.streams.get('new'), 'new draft');
});

test('only an ordinary text result corrects an existing draft', () => {
    assert.equal(streamState.shouldCorrectDraft(true, { type: 'text', summary: 'done' }), true);
    assert.equal(
        streamState.shouldCorrectDraft(true, { type: 'text', layout: 'report', summary: 'report' }),
        false,
    );
    assert.equal(streamState.shouldCorrectDraft(true, { type: 'causal_graph' }), false);
    assert.equal(streamState.shouldCorrectDraft(false, { type: 'text' }), false);
});
