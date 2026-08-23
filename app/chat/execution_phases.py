"""把 Job 输入账本与公开事件组装为会话历史中的执行阶段。"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any

from app.agent.public_events import public_event_payload


HISTORY_EVENT_TYPES = {
    "node_start",
    "progress",
    "decision",
    "tool_call_start",
    "tool_call_result",
    "node_retry",
    "node_end",
}
BOUNDARY_EVENT_TYPES = {"interrupt", "final_result", "error", "canceled"}
ACTIVE_JOB_STATUSES = {"queued", "running", "waiting_input"}
BOUNDARY_PHASE_STATUSES = {
    "interrupt": "completed",
    "final_result": "completed",
    "error": "failed",
    "canceled": "canceled",
}


def _decode_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _elapsed_seconds(started_at: Any, ended_at: Any) -> float:
    if not isinstance(started_at, datetime) or not isinstance(ended_at, datetime):
        return 0.0
    return round(max(0.0, (ended_at - started_at).total_seconds()), 1)


def _history_event(row: dict[str, Any]) -> dict[str, Any] | None:
    event_type = row.get("event_type")
    if event_type not in HISTORY_EVENT_TYPES:
        return None
    payload = public_event_payload(event_type, _decode_payload(row.get("payload_json")))
    payload["event_id"] = int(row["id"])
    return payload


def assemble_execution_phases(
    *,
    messages: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
    inputs: list[dict[str, Any]],
    events: list[dict[str, Any]],
    snapshot_at: datetime,
) -> dict[int, dict[str, Any]]:
    """返回以用户 chat message ID 为键的唯一 ExecutionPhase。"""
    jobs_by_id = {str(row["job_id"]): row for row in jobs}
    inputs_by_id = {int(row["input_id"]): row for row in inputs}
    inputs_by_job: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in inputs:
        inputs_by_job[str(row["job_id"])].append(row)
    for rows in inputs_by_job.values():
        rows.sort(key=lambda row: (int(row["sequence"]), int(row["input_id"])))

    user_messages_by_input: dict[int, list[dict[str, Any]]] = defaultdict(list)
    boundary_messages_by_event: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in messages:
        input_id = row.get("analysis_job_input_id")
        if row.get("message_type") == "user" and input_id is not None:
            user_messages_by_input[int(input_id)].append(row)
        source_event_id = row.get("source_event_id")
        if row.get("message_type") == "ai" and source_event_id is not None:
            boundary_messages_by_event[int(source_event_id)].append(row)

    events_by_job: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in events:
        events_by_job[str(row["job_id"])].append(row)
    for rows in events_by_job.values():
        rows.sort(key=lambda row: int(row["id"]))

    phases_by_message_id: dict[int, dict[str, Any]] = {}
    for job_id, job in jobs_by_id.items():
        job_inputs = inputs_by_job.get(job_id, [])
        if not job_inputs:
            continue

        pending_events: list[dict[str, Any]] = []
        phase_by_input_id: dict[int, dict[str, Any]] = {}
        last_processed_event_id = 0
        saw_boundary_event = False
        for event in events_by_job.get(job_id, []):
            event_type = event.get("event_type")
            history_event = _history_event(event)
            if history_event is not None:
                pending_events.append(event)
                continue
            if event_type not in BOUNDARY_EVENT_TYPES:
                continue
            last_processed_event_id = int(event["id"])

            boundary_messages = boundary_messages_by_event.get(int(event["id"]), [])
            if len(boundary_messages) != 1:
                logging.warning(
                    "ExecutionPhase 跳过无法唯一关联的边界: job=%s event=%s messages=%s",
                    job_id,
                    event["id"],
                    len(boundary_messages),
                )
                pending_events = []
                saw_boundary_event = True
                continue
            boundary_message = boundary_messages[0]
            input_id = boundary_message.get("analysis_job_input_id")
            input_row = inputs_by_id.get(int(input_id)) if input_id is not None else None
            user_messages = user_messages_by_input.get(int(input_id), []) if input_id is not None else []
            if (
                not input_row
                or str(input_row["job_id"]) != job_id
                or str(boundary_message.get("analysis_job_id")) != job_id
                or len(user_messages) != 1
                or int(input_row.get("chat_message_id") or 0) != int(user_messages[0]["id"])
                or (not saw_boundary_event and int(input_row["sequence"]) != 0)
            ):
                logging.warning(
                    "ExecutionPhase 跳过关联不完整的边界: job=%s event=%s input=%s user_messages=%s",
                    job_id,
                    event["id"],
                    input_id,
                    len(user_messages),
                )
                pending_events = []
                saw_boundary_event = True
                continue

            input_id = int(input_id)
            phase = phase_by_input_id.get(input_id)
            public_events = [item for row in pending_events if (item := _history_event(row))]
            started_at = pending_events[0].get("created_at") if pending_events else input_row.get("created_at")
            if phase is None:
                phase = {
                    "phase_sequence": int(input_row["sequence"]),
                    "status": BOUNDARY_PHASE_STATUSES[event_type],
                    "elapsed_seconds": _elapsed_seconds(started_at, event.get("created_at")),
                    "last_event_id": int(event["id"]),
                    "events": public_events,
                    "analysis_job_id": job_id,
                    "analysis_job_input_id": input_id,
                }
                phase_by_input_id[input_id] = phase
                phases_by_message_id[int(user_messages[0]["id"])] = phase
            else:
                phase["status"] = BOUNDARY_PHASE_STATUSES[event_type]
                phase["last_event_id"] = int(event["id"])
                phase["events"].extend(public_events)
            pending_events = []
            saw_boundary_event = True

        if job.get("status") in ACTIVE_JOB_STATUSES:
            latest_input = job_inputs[-1]
            input_id = int(latest_input["input_id"])
            user_messages = user_messages_by_input.get(input_id, [])
            if len(user_messages) != 1:
                logging.warning(
                    "ExecutionPhase 跳过无法唯一关联的活动阶段: job=%s input=%s user_messages=%s",
                    job_id,
                    input_id,
                    len(user_messages),
                )
                continue
            public_events = [item for row in pending_events if (item := _history_event(row))]
            phase = phase_by_input_id.get(input_id)
            if phase is None:
                cursor_event_id = (
                    int(pending_events[-1]["id"])
                    if pending_events
                    else last_processed_event_id
                )
                phase = {
                    "phase_sequence": int(latest_input["sequence"]),
                    "status": job.get("status") or "running",
                    "elapsed_seconds": _elapsed_seconds(
                        pending_events[0].get("created_at")
                        if pending_events
                        else latest_input.get("created_at"),
                        snapshot_at,
                    ),
                    "last_event_id": cursor_event_id,
                    "events": public_events,
                    "analysis_job_id": job_id,
                    "analysis_job_input_id": input_id,
                }
                phase_by_input_id[input_id] = phase
                phases_by_message_id[int(user_messages[0]["id"])] = phase
            else:
                if pending_events:
                    phase["status"] = job.get("status") or "running"
                    phase["last_event_id"] = int(pending_events[-1]["id"])
                    phase["events"].extend(public_events)
                elif job.get("status") == "waiting_input":
                    phase["status"] = "waiting_input"

    return phases_by_message_id
