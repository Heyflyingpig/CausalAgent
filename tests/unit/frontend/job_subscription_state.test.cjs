const test = require('node:test');
const assert = require('node:assert/strict');

const subscriptionState = require('../../../app/static/js/job_subscription_state.js');

test('a stale SSE subscription cannot become current after invalidation', () => {
    const state = subscriptionState.createState();
    const first = subscriptionState.nextGeneration(state, 'job-1');

    assert.equal(subscriptionState.isCurrentGeneration(state, 'job-1', first), true);

    const invalidated = subscriptionState.invalidate(state, 'job-1');
    assert.notEqual(invalidated, first);
    assert.equal(subscriptionState.isCurrentGeneration(state, 'job-1', first), false);

    const second = subscriptionState.nextGeneration(state, 'job-1');
    assert.equal(subscriptionState.isCurrentGeneration(state, 'job-1', second), true);
    assert.equal(subscriptionState.isCurrentGeneration(state, 'job-1', first), false);
});

test('cancellation idempotency keys are isolated per Job and stable while in flight', () => {
    const state = subscriptionState.createState();

    assert.equal(subscriptionState.beginCancel(state, 'job-1', 'request-1'), 'request-1');
    assert.equal(subscriptionState.beginCancel(state, 'job-1', 'request-2'), 'request-1');
    assert.equal(subscriptionState.beginCancel(state, 'job-2', 'request-3'), 'request-3');
    assert.equal(subscriptionState.isCancelInFlight(state, 'job-1'), true);
    assert.equal(subscriptionState.isCancelInFlight(state, 'job-2'), true);

    assert.equal(subscriptionState.finishCancel(state, 'job-1', 'request-2'), false);
    assert.equal(subscriptionState.cancelKey(state, 'job-1'), 'request-1');
    assert.equal(subscriptionState.finishCancel(state, 'job-1', 'request-1'), true);
    assert.equal(subscriptionState.isCancelInFlight(state, 'job-1'), false);
    assert.equal(subscriptionState.isCancelInFlight(state, 'job-2'), true);
});

test('cancel response distinguishes accepted, reconciled, and real terminal conflicts', () => {
    assert.deepEqual(
        subscriptionState.classifyCancelResponse(202, { success: true, status: 'canceled' }),
        { kind: 'accepted', status: 'canceled' },
    );
    assert.deepEqual(
        subscriptionState.classifyCancelResponse(
            409,
            { code: 'job_state_conflict', status: 'canceled' },
        ),
        { kind: 'reconciled', status: 'canceled' },
    );
    assert.deepEqual(
        subscriptionState.classifyCancelResponse(
            409,
            { code: 'job_state_conflict', status: 'succeeded' },
        ),
        { kind: 'conflict', status: 'succeeded' },
    );
});

test('input action maps active Job states to running, waiting, and idle controls', () => {
    assert.equal(subscriptionState.classifyInputMode({ status: 'queued' }, false), 'running');
    assert.equal(subscriptionState.classifyInputMode({ status: 'running' }, false), 'running');
    assert.equal(
        subscriptionState.classifyInputMode({ status: 'running' }, true),
        'running_canceling',
    );
    assert.equal(
        subscriptionState.classifyInputMode({ status: 'waiting_input' }, false),
        'waiting_input',
    );
    assert.equal(
        subscriptionState.classifyInputMode({ status: 'waiting_input' }, true),
        'waiting_canceling',
    );
    assert.equal(subscriptionState.classifyInputMode({ status: 'succeeded' }, false), 'idle');
    assert.equal(subscriptionState.classifyInputMode(null, false), 'idle');
});
