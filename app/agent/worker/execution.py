"""执行单个 analysis job，维护 lease monitor 并在取消后收敛执行占用。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.agent import job_service
from app.agent.worker.event_adapter import sanitize_public_error
from app.agent.worker.event_writer import OrderedEventWriter
from app.agent.worker.execution_guard import JobExecutionGuard, JobExecutionRevoked
from app.agent.worker.graph_runner import ai_call_stream
from app.agent.worker.runtime import SlotRuntime
from config.settings import settings


async def heartbeat_until_stopped(
    job_id: str,
    worker_id: str,
    attempt_count: int,
    lease_epoch: int,
    stop: asyncio.Event,
    guard: JobExecutionGuard | None = None,
) -> None:
    """刷新 leased/draining 心跳；stop.set() 后立即唤醒，不再额外等待一个周期。"""
    while not stop.is_set():
        try:
            await asyncio.wait_for(
                stop.wait(),
                timeout=settings.JOB_HEARTBEAT_INTERVAL_SECONDS,
            )
            return
        except asyncio.TimeoutError:
            pass
        try:
            authority = await asyncio.to_thread(
                job_service.refresh_execution_lease,
                job_id,
                worker_id,
                attempt_count,
                lease_epoch,
            )
        except Exception:
            logging.warning("[worker] lease monitor refresh failed job=%s", job_id, exc_info=True)
            continue
        if not authority.get("active"):
            if guard is not None:
                guard.mark_revoked()
            logging.info(
                "[worker] execution revoked job=%s status=%s state=%s",
                job_id,
                authority.get("status"),
                authority.get("execution_state"),
            )


async def run_job(
    job: dict[str, Any],
    slot_runtime: SlotRuntime,
    worker_id: str,
) -> None:
    """使用显式 slot runtime 执行 Job，并区分失败、撤销和 draining cleanup。"""
    job_id = job["job_id"]
    attempt_count = int(job["attempt_count"])
    lease_epoch = int(job.get("lease_epoch") or 0)
    guard = JobExecutionGuard(job_id, worker_id, attempt_count, lease_epoch)
    guard_token = guard.install()
    stop_heartbeat = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        heartbeat_until_stopped(
            job_id,
            worker_id,
            attempt_count,
            lease_epoch,
            stop_heartbeat,
            guard,
        )
    )
    writer: OrderedEventWriter | None = None
    graph_stream = None
    revoked = False
    cleanup_complete = True
    cleanup_errors: list[BaseException] = []

    try:
        await guard.ensure_active()
        writer = OrderedEventWriter(job, worker_id, execution_guard=guard)
        latest_input = await asyncio.to_thread(job_service.get_latest_input_value, job_id)
        await guard.check_after_call()
        if latest_input is None:
            raise RuntimeError("任务输入账本为空")
        initial_input = latest_input
        if (
            job.get("claim_kind") == "stale_recovery"
            and latest_input.get("input_type") != "initial"
        ):
            initial_input = await asyncio.to_thread(
                job_service.get_initial_input_value,
                job_id,
            )
            await guard.check_after_call()
            if initial_input is None:
                raise RuntimeError("任务初始输入账本为空")
        logging.info(
            "[worker] start job=%s worker=%s session=%s tools=%s",
            job_id,
            worker_id,
            job["session_id"],
            len(slot_runtime.mcp_tools),
        )
        graph_stream = ai_call_stream(
            latest_input,
            job["user_id"],
            f"user-{job['user_id']}",
            job["session_id"],
            job_id=job_id,
            job_attempt=attempt_count,
            input_user_file_id=job.get("input_user_file_id"),
            input_object_id=job.get("input_object_id"),
            input_file_hash=job.get("input_file_hash"),
            input_filename=job.get("input_filename"),
            graph=slot_runtime.graph,
            claim_kind=job.get("claim_kind", "initial"),
            initial_input_record=initial_input,
            execution_guard=guard,
        )
        try:
            async for payload in graph_stream:
                await guard.ensure_active()
                await writer.submit(payload)
        finally:
            stream = graph_stream
            graph_stream = None
            if stream is not None:
                await stream.aclose()

        await writer.close()
        if not writer.terminal_seen:
            await guard.ensure_active()
            completed = await asyncio.to_thread(
                job_service.complete_job,
                job_id,
                worker_id,
                attempt_count,
                {},
                lease_epoch,
            )
            if not completed:
                raise JobExecutionRevoked("success terminalization fenced")
        logging.info("[worker] finish job=%s worker=%s", job_id, worker_id)
    except JobExecutionRevoked as exc:
        revoked = True
        logging.info("[worker] job execution stopped job=%s reason=%s", job_id, exc)
        if writer is not None:
            try:
                await writer.abort(exc)
            except asyncio.CancelledError:
                cleanup_complete = False
                raise
            except BaseException as cleanup_error:
                cleanup_complete = False
                cleanup_errors.append(cleanup_error)
                logging.error(
                    "[worker] revoked job cleanup failed job=%s error=%s",
                    job_id,
                    cleanup_error,
                    exc_info=True,
                )
    except asyncio.CancelledError as exc:
        # 进程/worker 级取消不是业务取消，但也不能遗留活跃 writer；只有完整
        # cleanup 后才允许 finally 条件释放 canceled/draining 执行占用。
        revoked = True
        guard.mark_revoked()
        if writer is not None and not writer.terminal_seen:
            try:
                await writer.abort(exc)
            except asyncio.CancelledError:
                cleanup_complete = False
                raise
            except BaseException as cleanup_error:
                cleanup_complete = False
                cleanup_errors.append(cleanup_error)
                logging.error(
                    "[worker] task cancellation cleanup failed job=%s error=%s",
                    job_id,
                    cleanup_error,
                    exc_info=True,
                )
        raise
    except Exception as exc:
        logging.error(
            "[worker] job failed job=%s worker=%s error=%s",
            job_id,
            worker_id,
            exc,
            exc_info=True,
        )
        if writer is not None and not writer.terminal_seen:
            try:
                await writer.abort()
            except asyncio.CancelledError:
                cleanup_complete = False
                raise
            except BaseException as cleanup_error:
                cleanup_complete = False
                cleanup_errors.append(cleanup_error)
                logging.error(
                    "[worker] failure cleanup failed job=%s error=%s",
                    job_id,
                    cleanup_error,
                    exc_info=True,
                )
        try:
            failure_result = await asyncio.to_thread(
                job_service.fail_job,
                job_id,
                worker_id,
                attempt_count,
                sanitize_public_error(exc),
                lease_epoch=lease_epoch,
            )
        except asyncio.CancelledError:
            cleanup_complete = False
            raise
        except Exception as failure_error:
            cleanup_complete = False
            cleanup_errors.append(failure_error)
            logging.error(
                "[worker] failure terminalization could not be confirmed job=%s error=%s",
                job_id,
                failure_error,
                exc_info=True,
            )
        else:
            if isinstance(failure_result, job_service.FailJobResult):
                fenced = failure_result is not job_service.FailJobResult.APPLIED
                failure_reason = failure_result.value
            else:
                fenced = not bool(failure_result)
                failure_reason = "fenced"
            if fenced:
                # CANCELED_FENCED 和 OTHER_FENCED 都表示本次 worker 不能再推进；
                # 只有 canceled/draining 会在 finally 中尝试条件释放执行占用。
                revoked = True
                guard.mark_revoked()
                logging.info(
                    "[worker] failure terminalization fenced job=%s reason=%s",
                    job_id,
                    failure_reason,
                )
    finally:
        try:
            if graph_stream is not None:
                stream = graph_stream
                graph_stream = None
                try:
                    await stream.aclose()
                except asyncio.CancelledError:
                    cleanup_complete = False
                    raise
                except BaseException as cleanup_error:
                    cleanup_complete = False
                    cleanup_errors.append(cleanup_error)
                    logging.error(
                        "[worker] graph stream cleanup failed job=%s error=%s",
                        job_id,
                        cleanup_error,
                        exc_info=True,
                    )
            stop_heartbeat.set()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                cleanup_complete = False
                raise
            except BaseException as monitor_error:
                cleanup_complete = False
                cleanup_errors.append(monitor_error)
                logging.warning(
                    "[worker] lease monitor stopped with error job=%s",
                    job_id,
                    exc_info=True,
                )
            if revoked or guard.revoked:
                if cleanup_complete:
                    try:
                        released = await asyncio.to_thread(
                            job_service.release_execution_ownership,
                            job_id,
                            worker_id,
                            attempt_count,
                            lease_epoch,
                        )
                        if not released:
                            logging.info(
                                "[worker] execution release fenced or already complete job=%s",
                                job_id,
                            )
                    except asyncio.CancelledError:
                        cleanup_complete = False
                        raise
                    except BaseException as release_error:
                        cleanup_complete = False
                        cleanup_errors.append(release_error)
                        logging.warning(
                            "[worker] cleanup release failed; keep draining job=%s",
                            job_id,
                            exc_info=True,
                        )
                else:
                    logging.warning(
                        "[worker] cleanup incomplete; do not confirm execution release job=%s errors=%s",
                        job_id,
                        len(cleanup_errors),
                    )
        finally:
            JobExecutionGuard.reset(guard_token)
