const test = require('node:test');
const assert = require('node:assert/strict');

const phaseState = require('../../../app/static/js/execution_phase_state.js');

test('history replay accepts node events but rejects message side effects', () => {
    assert.equal(phaseState.isHistoryEvent('node_start'), true);
    assert.equal(phaseState.isHistoryEvent('tool_call_result'), true);
    assert.equal(phaseState.isHistoryEvent('text_delta'), false);
    assert.equal(phaseState.isHistoryEvent('final_result'), false);
    assert.equal(phaseState.isHistoryEvent('interrupt'), false);
});

test('only queued and running phases resume an SSE subscription', () => {
    assert.equal(phaseState.isActivePhase('queued'), true);
    assert.equal(phaseState.isActivePhase('running'), true);
    assert.equal(phaseState.isActivePhase('waiting_input'), false);
    assert.equal(phaseState.isActivePhase('completed'), false);
});

test('active API metadata cannot advance the rendered event cursor', () => {
    const merged = phaseState.mergeActiveJob(
        { rendered_event_id: 12, last_event_id: 12, thinkingElements: {} },
        { status: 'running', last_event_id: 18 },
    );

    assert.equal(merged.status, 'running');
    assert.equal(merged.last_event_id, 12);
    assert.equal(merged.rendered_event_id, 12);
});
