"""
RAG评测管理路由 —— 面向开发者的HTTP API。
"""
import json
import logging
import math
import queue
import time
from flask import Blueprint, jsonify, request, Response, session

from app.rag_eval.service import (
    get_rag_eval_status,
    get_rag_eval_config,
    get_production_rag_config,
    publish_current_config_to_production,
    update_rag_eval_config,
    ConfigValidationError,
    run_pipeline_async,
    get_pipeline_runtime_state,
    get_latest_results,
    list_runs,
    list_runs_page,
    delete_run,
    get_run_detail,
    get_latest_analysis,
    get_run_analysis,
    get_run_diff,
    subscribe_progress,
    unsubscribe_progress,
    get_step_descriptions,
    request_pipeline_cancel,
    current_event_timestamp,
)
from app.rag_eval.isolated_runs import (
    delete_uploaded_source,
    isolated_run_manager,
    list_source_catalog,
    register_uploaded_source,
)
from app.rag_eval.profile_store import (
    create_custom_profile,
    delete_custom_profile,
    list_strategy_profiles,
    publish_custom_profile,
    update_custom_profile,
)
from config.settings import settings

rag_eval_bp = Blueprint("rag_eval", __name__, url_prefix="/api/rag_eval")


def _json_response(data, status=200):
    """统一JSON响应格式。"""
    return jsonify(_json_safe(data)), status


def _json_safe(value):
    """把 NaN/Infinity 转成 null，避免浏览器 JSON.parse 失败。"""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


# ---- 状态与配置 ----

@rag_eval_bp.route("/status", methods=["GET"])
def api_status():
    """获取当前benchmark、向量库和最新评测的汇总状态。"""
    try:
        return _json_response({"success": True, "data": get_rag_eval_status()})
    except Exception as exc:
        logging.error("获取RAG评测状态失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/config", methods=["GET"])
def api_get_config():
    """获取所有可调参数，按类别分组（retrieval_profile / ragas / pipeline）。"""
    try:
        return _json_response({"success": True, "data": get_rag_eval_config()})
    except Exception as exc:
        logging.error("获取RAG评测配置失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/config", methods=["PUT"])
def api_update_config():
    """更新运行时可调参数（内存中生效，restart后恢复默认）。"""
    try:
        overrides = request.get_json(silent=True) or {}
        result = update_rag_eval_config(overrides)
        return _json_response({"success": True, "data": result})
    except ConfigValidationError as exc:
        return _json_response({"success": False, "error": str(exc)}, 400)
    except Exception as exc:
        logging.error("更新RAG评测配置失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


def _current_profile_owner_id():
    """返回当前会话用户；未登录时使用本地开发共享 profile。"""
    return session.get("user_id")


@rag_eval_bp.route("/profiles", methods=["GET"])
def api_list_strategy_profiles():
    """列出只读内置 profile 和当前用户可访问的自定义 profile。"""
    try:
        return _json_response({"success": True, "data": list_strategy_profiles(_current_profile_owner_id())})
    except Exception as exc:
        logging.error("读取RAG评测策略profile失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/profiles", methods=["POST"])
def api_create_strategy_profile():
    """创建自定义 unified retrieval/Ragas profile。"""
    try:
        payload = request.get_json(silent=True) or {}
        profile = create_custom_profile(payload, _current_profile_owner_id())
        return _json_response({"success": True, "data": profile}, 201)
    except ValueError as exc:
        return _json_response({"success": False, "error": str(exc)}, 400)
    except Exception as exc:
        logging.error("创建RAG评测策略profile失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/profiles/<profile_id>", methods=["PUT"])
def api_update_strategy_profile(profile_id):
    """更新自定义 profile；内置 profile 不可修改。"""
    try:
        payload = request.get_json(silent=True) or {}
        profile = update_custom_profile(profile_id, payload, _current_profile_owner_id())
        return _json_response({"success": True, "data": profile})
    except KeyError as exc:
        return _json_response({"success": False, "error": str(exc)}, 404)
    except ValueError as exc:
        return _json_response({"success": False, "error": str(exc)}, 400)
    except Exception as exc:
        logging.error("更新RAG评测策略profile失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/profiles/<profile_id>", methods=["DELETE"])
def api_delete_strategy_profile(profile_id):
    """删除自定义 profile；内置和当前正式 profile 不可删除。"""
    try:
        delete_custom_profile(profile_id, _current_profile_owner_id())
        return _json_response({"success": True, "data": {"profile_id": profile_id}})
    except KeyError as exc:
        return _json_response({"success": False, "error": str(exc)}, 404)
    except ValueError as exc:
        return _json_response({"success": False, "error": str(exc)}, 409)
    except Exception as exc:
        logging.error("删除RAG评测策略profile失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/profiles/<profile_id>/publish", methods=["POST"])
def api_publish_strategy_profile(profile_id):
    """发布自定义 profile 的 retrieval 快照，并切换正式 profile 指针。"""
    try:
        payload = request.get_json(silent=True) or {}
        profile = publish_custom_profile(
            profile_id,
            _current_profile_owner_id(),
            note=str(payload.get("note") or ""),
        )
        return _json_response({"success": True, "data": profile})
    except KeyError as exc:
        return _json_response({"success": False, "error": str(exc)}, 404)
    except ValueError as exc:
        return _json_response({"success": False, "error": str(exc)}, 400)
    except Exception as exc:
        logging.error("发布RAG评测策略profile失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/production-config", methods=["GET"])
def api_get_production_config():
    """获取正式 RAG 调用当前使用的检索配置。"""
    try:
        return _json_response({"success": True, "data": get_production_rag_config()})
    except Exception as exc:
        logging.error("获取正式RAG配置失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/production-config/publish", methods=["POST"])
def api_publish_production_config():
    """把当前评测检索配置发布为正式 RAG 调用配置。"""
    try:
        payload = request.get_json(silent=True) or {}
        return _json_response({"success": True, "data": publish_current_config_to_production(payload)})
    except Exception as exc:
        logging.error("发布正式RAG配置失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/steps", methods=["GET"])
def api_step_descriptions():
    """返回pipeline各步骤的中文描述。"""
    return _json_response({"success": True, "data": get_step_descriptions()})


# ---- R5 隔离知识源与 staged index ----

def _parse_isolated_rag_input(payload):
    """把单问题或内联 rag_eval_v1 题集转换为统一问题列表。"""
    dataset = payload.get("eval_dataset") or payload.get("dataset")
    if dataset is not None:
        if not isinstance(dataset, dict) or dataset.get("schema_version") != "rag_eval_v1":
            raise ValueError("eval_dataset.schema_version must be rag_eval_v1")
        samples = dataset.get("samples")
        if not isinstance(samples, list) or not samples:
            raise ValueError("rag_eval_v1 dataset requires a non-empty samples list")
        questions = samples
        identity = {
            "schema_version": "rag_eval_v1",
            "dataset_id": str(dataset.get("dataset_id") or payload.get("dataset_id") or "inline"),
            "sample_count": len(samples),
        }
    elif isinstance(payload.get("questions"), list):
        questions = payload["questions"]
        identity = {"schema_version": "isolated_questions_v1", "question_count": len(questions)}
    else:
        questions = [{"question": payload.get("question", "")}]
        identity = {"schema_version": "isolated_question_v1"}

    normalized = [item if isinstance(item, dict) else {"question": item} for item in questions]
    return normalized, identity

def _isolated_stream(run_id):
    """为知识源摄取和 staged index RAG 查询提供统一 SSE 流。"""
    state = isolated_run_manager.get(run_id)
    persistent_worker = state.get("execution_backend") == "persistent_worker"
    event_queue = None if persistent_worker else isolated_run_manager.subscribe(run_id)

    def generate():
        try:
            connected_event = {
                "type": "connected",
                "message": "隔离运行 SSE 连接已建立",
                "timestamp": current_event_timestamp(),
                "run_id": run_id,
            }
            yield f"data: {json.dumps(connected_event, ensure_ascii=False)}\n\n"
            if persistent_worker:
                cursor = 0
                last_heartbeat = time.monotonic()
                while True:
                    events, cursor = isolated_run_manager.read_events(run_id, cursor)
                    for event in events:
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                        if event.get("type") in {"run_done", "run_error", "run_cancelled"}:
                            return
                    current = isolated_run_manager.get(run_id)
                    if current.get("status") not in {"created", "queued", "running", "cancelling"}:
                        return
                    if time.monotonic() - last_heartbeat >= 15:
                        yield "data: {\"type\":\"heartbeat\"}\n\n"
                        last_heartbeat = time.monotonic()
                    time.sleep(1)
            while True:
                try:
                    event = event_queue.get(timeout=30)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    if event.get("type") in {"run_done", "run_error", "run_cancelled"}:
                        break
                except queue.Empty:
                    yield "data: {\"type\":\"heartbeat\"}\n\n"
        except GeneratorExit:
            pass
        finally:
            isolated_run_manager.unsubscribe(run_id)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@rag_eval_bp.route("/isolated/ingestion-runs", methods=["GET"])
def api_isolated_ingestion_history():
    """列出持久化摄取运行，供工作台恢复最近状态。"""
    try:
        page = request.args.get("page", default=1, type=int)
        page_size = request.args.get("page_size", default=50, type=int)
        return _json_response({
            "success": True,
            "data": isolated_run_manager.list_ingestion_history(
                status=request.args.get("status") or None,
                source_id=request.args.get("source_id") or None,
                page=page,
                page_size=page_size,
            ),
        })
    except (KeyError, ValueError) as exc:
        return _json_response({"success": False, "error": str(exc)}, 400)
    except Exception as exc:
        logging.error("读取隔离摄取历史失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/isolated/ingestion-runs", methods=["POST"])
def api_start_isolated_ingestion():
    """启动显式来源的全新隔离摄取任务。"""
    try:
        payload = request.get_json(silent=True) or {}
        source_ids = payload.get("source_ids")
        sources = payload.get("sources")
        max_pages = payload.get("max_pages")
        page_ranges = payload.get("page_ranges")
        if source_ids is not None and not isinstance(source_ids, list):
            raise ValueError("source_ids must be a list")
        if sources is not None and not isinstance(sources, list):
            raise ValueError("sources must be a list")
        if max_pages is not None and (isinstance(max_pages, bool) or not isinstance(max_pages, int)):
            raise ValueError("max_pages must be an integer")
        if page_ranges is not None and not isinstance(page_ranges, list):
            raise ValueError("page_ranges must be a list")
        result = isolated_run_manager.start_ingestion(
            source_ids=source_ids,
            sources=sources,
            max_pages=max_pages,
            page_ranges=page_ranges,
        )
        return _json_response({"success": True, "data": result}, 202)
    except (FileNotFoundError, ValueError) as exc:
        return _json_response({"success": False, "error": str(exc)}, 400)
    except Exception as exc:
        logging.error("启动隔离知识源摄取失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/isolated/source-catalog", methods=["GET"])
def api_isolated_source_catalog():
    """返回可选来源的稳定 ID 和摘要，隐藏宿主文件路径。"""
    try:
        return _json_response({"success": True, "data": {"sources": list_source_catalog()}})
    except Exception as exc:
        logging.error("读取隔离来源目录失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/isolated/sources", methods=["POST"])
def api_upload_isolated_source():
    """登记一个前端上传的知识源，不自动启动摄取。"""
    try:
        uploaded = request.files.get("file")
        if uploaded is None:
            raise ValueError("没有选择文件")
        content = uploaded.read(settings.MAX_UPLOAD_SIZE_BYTES + 1)
        source = register_uploaded_source(uploaded.filename, content)
        return _json_response({"success": True, "data": {"source": source}}, 201)
    except ValueError as exc:
        return _json_response({"success": False, "error": str(exc)}, 400)
    except OSError as exc:
        logging.error("保存隔离知识源失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": "知识源保存失败"}, 500)
    except Exception as exc:
        logging.error("登记隔离知识源失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/isolated/sources/<source_id>", methods=["DELETE"])
def api_delete_isolated_source(source_id):
    """删除用户上传的来源文件，不触碰固定来源或已生成的隔离产物。"""
    try:
        return _json_response({"success": True, "data": delete_uploaded_source(source_id)})
    except KeyError as exc:
        return _json_response({"success": False, "error": str(exc)}, 404)
    except RuntimeError as exc:
        return _json_response({"success": False, "error": str(exc)}, 409)
    except ValueError as exc:
        return _json_response({"success": False, "error": str(exc)}, 400)
    except Exception as exc:
        logging.error("删除隔离知识源失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/isolated/ingestion-runs/<run_id>", methods=["GET"])
def api_isolated_ingestion_state(run_id):
    """读取隔离知识源摄取任务状态。"""
    try:
        return _json_response({"success": True, "data": isolated_run_manager.get(run_id)})
    except (KeyError, ValueError) as exc:
        return _json_response({"success": False, "error": str(exc)}, 404)


@rag_eval_bp.route("/isolated/ingestion-runs/<run_id>/stream", methods=["GET"])
def api_isolated_ingestion_stream(run_id):
    """订阅隔离知识源摄取事件。"""
    try:
        return _isolated_stream(run_id)
    except (KeyError, ValueError) as exc:
        return _json_response({"success": False, "error": str(exc)}, 404)


@rag_eval_bp.route("/isolated/ingestion-runs/<run_id>/cancel", methods=["POST"])
def api_cancel_isolated_ingestion(run_id):
    """请求取消隔离知识源摄取任务。"""
    try:
        return _json_response({"success": True, "data": isolated_run_manager.cancel(run_id)})
    except (KeyError, ValueError) as exc:
        return _json_response({"success": False, "error": str(exc)}, 404)


@rag_eval_bp.route("/isolated/rag-runs", methods=["POST"])
def api_start_isolated_rag_query():
    """在指定 staged index 上启动真实检索与回答任务。"""
    try:
        payload = request.get_json(silent=True) or {}
        questions, input_identity = _parse_isolated_rag_input(payload)
        result = isolated_run_manager.start_rag_query(
            payload.get("ingestion_run_id", ""),
            payload.get("index_version", ""),
            questions,
            input_identity=input_identity,
        )
        return _json_response({"success": True, "data": result}, 202)
    except (KeyError, ValueError) as exc:
        return _json_response({"success": False, "error": str(exc)}, 400)
    except Exception as exc:
        logging.error("启动隔离 staged index RAG 测试失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/isolated/rag-runs/<run_id>", methods=["GET"])
def api_isolated_rag_state(run_id):
    """读取 staged index RAG 测试任务状态。"""
    try:
        return _json_response({"success": True, "data": isolated_run_manager.get(run_id)})
    except (KeyError, ValueError) as exc:
        return _json_response({"success": False, "error": str(exc)}, 404)


@rag_eval_bp.route("/isolated/rag-runs/<run_id>/result", methods=["GET"])
def api_isolated_rag_result(run_id):
    """读取已完成的隔离 RAG 查询结果。"""
    try:
        return _json_response({"success": True, "data": isolated_run_manager.get_result(run_id)})
    except (KeyError, ValueError) as exc:
        return _json_response({"success": False, "error": str(exc)}, 404)


@rag_eval_bp.route("/isolated/rag-runs/<run_id>/stream", methods=["GET"])
def api_isolated_rag_stream(run_id):
    """订阅 staged index RAG 测试事件。"""
    try:
        return _isolated_stream(run_id)
    except (KeyError, ValueError) as exc:
        return _json_response({"success": False, "error": str(exc)}, 404)


@rag_eval_bp.route("/isolated/rag-runs/<run_id>/cancel", methods=["POST"])
def api_cancel_isolated_rag(run_id):
    """请求取消 staged index RAG 测试任务。"""
    try:
        return _json_response({"success": True, "data": isolated_run_manager.cancel(run_id)})
    except (KeyError, ValueError) as exc:
        return _json_response({"success": False, "error": str(exc)}, 404)


# ---- R5 Evaluation Run ----

@rag_eval_bp.route("/isolated/evaluation-runs", methods=["POST"])
def api_start_isolated_evaluation():
    """在显式 staged index 上启动 retrieval、Ragas 和报告流水线。"""
    try:
        payload = request.get_json(silent=True) or {}
        dataset = payload.get("eval_dataset") or payload.get("dataset")
        if not isinstance(dataset, dict):
            raise ValueError("eval_dataset is required")
        retrieval = payload.get("retrieval") or {}
        ragas = payload.get("ragas") or {}
        steps = payload.get("steps")
        if not isinstance(retrieval, dict) or not isinstance(ragas, dict):
            raise ValueError("retrieval and ragas must be objects")
        if steps is not None and not isinstance(steps, list):
            raise ValueError("steps must be a list")
        result = isolated_run_manager.start_evaluation(
            payload.get("ingestion_run_id", ""),
            payload.get("index_version", ""),
            dataset,
            retrieval_options=retrieval,
            ragas_options=ragas,
            strategy_profile=payload.get("strategy_profile"),
            steps=steps,
        )
        return _json_response({"success": True, "data": result}, 202)
    except (KeyError, ValueError, FileNotFoundError) as exc:
        return _json_response({"success": False, "error": str(exc)}, 400)
    except Exception as exc:
        logging.error("启动隔离 RAG 评测失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/isolated/evaluation-runs/<run_id>", methods=["GET"])
def api_isolated_evaluation_state(run_id):
    """读取隔离评测任务状态。"""
    try:
        return _json_response({"success": True, "data": isolated_run_manager.get(run_id)})
    except (KeyError, ValueError) as exc:
        return _json_response({"success": False, "error": str(exc)}, 404)


@rag_eval_bp.route("/isolated/evaluation-runs/<run_id>", methods=["DELETE"])
def api_delete_isolated_evaluation(run_id):
    """删除已结束或确认失活的隔离评测及其报告目录。"""
    try:
        payload = request.get_json(silent=True) or {}
        force = payload.get("force") is True
        result = isolated_run_manager.delete_evaluation_run(run_id, force=force)
        if result.get("status") == "running":
            return _json_response({"success": False, "error": result.get("message") or "run is still running", "data": result}, 409)
        return _json_response({"success": True, "data": result})
    except KeyError as exc:
        return _json_response({"success": False, "error": str(exc)}, 404)
    except ValueError as exc:
        return _json_response({"success": False, "error": str(exc)}, 409)
    except Exception as exc:
        logging.error("删除隔离评测失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/isolated/evaluation-history", methods=["GET"])
def api_isolated_evaluation_history():
    """列出隔离评测摘要，供趋势和运行选择使用。"""
    try:
        page = request.args.get("page", default=1, type=int)
        page_size = request.args.get("page_size", default=50, type=int)
        return _json_response({
            "success": True,
            "data": isolated_run_manager.list_evaluation_history(
                dataset_id=request.args.get("dataset_id") or None,
                index_version=request.args.get("index_version") or None,
                status=request.args.get("status") or None,
                source_name=request.args.get("source_name") or None,
                since=request.args.get("since") or None,
                until=request.args.get("until") or None,
                page=page,
                page_size=page_size,
            ),
        })
    except (KeyError, ValueError) as exc:
        return _json_response({"success": False, "error": str(exc)}, 400)
    except Exception as exc:
        logging.error("读取隔离评测历史失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/isolated/evaluation-diff", methods=["GET"])
def api_isolated_evaluation_diff():
    """比较两个隔离评测运行，要求题集 identity 完全一致。"""
    try:
        base_run_id = request.args.get("base_run_id", "")
        candidate_run_id = request.args.get("candidate_run_id", "")
        if not base_run_id or not candidate_run_id:
            raise ValueError("base_run_id and candidate_run_id are required")
        return _json_response({
            "success": True,
            "data": isolated_run_manager.get_evaluation_diff(base_run_id, candidate_run_id),
        })
    except KeyError as exc:
        return _json_response({"success": False, "error": str(exc)}, 404)
    except ValueError as exc:
        return _json_response({"success": False, "error": str(exc)}, 409)
    except Exception as exc:
        logging.error("读取隔离评测 diff 失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/isolated/evaluation-runs/<run_id>/result", methods=["GET"])
def api_isolated_evaluation_result(run_id):
    """读取已完成隔离评测的汇总结果。"""
    try:
        return _json_response({"success": True, "data": isolated_run_manager.get_result(run_id)})
    except (KeyError, ValueError) as exc:
        return _json_response({"success": False, "error": str(exc)}, 404)


@rag_eval_bp.route("/isolated/evaluation-runs/<run_id>/artifacts/<path:artifact_name>", methods=["GET"])
def api_isolated_evaluation_artifact(run_id, artifact_name):
    """读取本次评测目录中的 JSON 或 Markdown 产物。"""
    try:
        path = isolated_run_manager.get_artifact_path(run_id, artifact_name)
        if path.suffix.lower() == ".json":
            return _json_response({"success": True, "data": json.loads(path.read_text(encoding="utf-8"))})
        return Response(path.read_text(encoding="utf-8"), mimetype="text/markdown; charset=utf-8")
    except (KeyError, ValueError, OSError, json.JSONDecodeError) as exc:
        return _json_response({"success": False, "error": str(exc)}, 404)


@rag_eval_bp.route("/isolated/evaluation-runs/<run_id>/stream", methods=["GET"])
def api_isolated_evaluation_stream(run_id):
    """订阅隔离评测事件。"""
    try:
        return _isolated_stream(run_id)
    except (KeyError, ValueError) as exc:
        return _json_response({"success": False, "error": str(exc)}, 404)


@rag_eval_bp.route("/isolated/evaluation-runs/<run_id>/cancel", methods=["POST"])
def api_cancel_isolated_evaluation(run_id):
    """请求取消隔离评测任务。"""
    try:
        return _json_response({"success": True, "data": isolated_run_manager.cancel(run_id)})
    except (KeyError, ValueError) as exc:
        return _json_response({"success": False, "error": str(exc)}, 404)


# ---- Pipeline 运行 ----

@rag_eval_bp.route("/run", methods=["POST"])
def api_run_pipeline():
    """触发完整pipeline，返回run_id供前端订阅SSE。"""
    try:
        overrides = request.get_json(silent=True) or {}
        result = run_pipeline_async(overrides)
        return _json_response({"success": True, "data": result})
    except Exception as exc:
        logging.error("触发RAG评测pipeline失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/run-state", methods=["GET"])
def api_run_state():
    """获取当前进程内pipeline运行状态，用于页面刷新后恢复运行页。"""
    try:
        run_id = request.args.get("run_id")
        return _json_response({"success": True, "data": get_pipeline_runtime_state(run_id)})
    except Exception as exc:
        logging.error("获取RAG评测运行状态失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/runs/<run_id>/stream", methods=["GET"])
def api_stream_progress(run_id):
    """SSE端点：订阅某个run的实时进度。"""
    q = subscribe_progress(run_id)

    def generate():
        try:
            # 发送初始连接确认
            connected_event = {
                "type": "connected",
                "message": "SSE连接已建立",
                "timestamp": current_event_timestamp(),
                "run_id": run_id,
            }
            yield f"data: {json.dumps(_json_safe(connected_event), ensure_ascii=False, allow_nan=False)}\n\n"
            while True:
                try:
                    event = q.get(timeout=30)
                    yield f"data: {json.dumps(_json_safe(event), ensure_ascii=False, allow_nan=False)}\n\n"
                    if event["type"] in ("pipeline_done", "pipeline_error", "pipeline_closed"):
                        break
                except Exception:
                    # 超时发送心跳
                    yield f"data: {json.dumps({'type': 'heartbeat'}, ensure_ascii=False, allow_nan=False)}\n\n"
        except GeneratorExit:
            pass
        finally:
            unsubscribe_progress(run_id)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@rag_eval_bp.route("/runs/<run_id>/cancel", methods=["POST"])
def api_cancel_pipeline(run_id):
    """请求温和取消某个正在运行的pipeline。"""
    try:
        result = request_pipeline_cancel(run_id)
        if result.get("status") == "not_found":
            return _json_response({"success": False, "error": "run not found"}, 404)
        return _json_response({"success": True, "data": result})
    except Exception as exc:
        logging.error("取消RAG评测pipeline失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


# ---- 结果查询 ----

@rag_eval_bp.route("/results/latest", methods=["GET"])
def api_latest_results():
    """获取最新评测结果（retrieval / ragas / claim / trace 各阶段指标）。"""
    try:
        return _json_response({"success": True, "data": get_latest_results()})
    except Exception as exc:
        logging.error("获取最新评测结果失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/analysis/latest", methods=["GET"])
def api_latest_analysis():
    """获取最新评测的报告、trace索引和坏例明细。"""
    try:
        return _json_response({"success": True, "data": get_latest_analysis()})
    except Exception as exc:
        logging.error("获取最新RAG分析数据失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/runs", methods=["GET"])
def api_list_runs():
    """列出历史run记录。"""
    try:
        page = request.args.get("page", type=int)
        page_size = request.args.get("page_size", type=int)
        if page is None and page_size is None:
            return _json_response({"success": True, "data": list_runs()})
        return _json_response({"success": True, "data": list_runs_page(page or 1, page_size or 10)})
    except Exception as exc:
        logging.error("列出历史run失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/runs/<run_id>", methods=["GET"])
def api_run_detail(run_id):
    """获取某个run的详细信息（含配置快照）。"""
    try:
        data = get_run_detail(run_id)
        if "error" in data:
            return _json_response({"success": False, "error": data["error"]}, 404)
        return _json_response({"success": True, "data": data})
    except Exception as exc:
        logging.error("获取run详情失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/runs/<run_id>", methods=["DELETE"])
def api_delete_run(run_id):
    """删除某个历史run目录及其本地output/runs文件。"""
    try:
        data = delete_run(run_id)
        if data.get("status") == "deleted":
            return _json_response({"success": True, "data": data})
        if data.get("status") == "not_found":
            return _json_response({"success": False, "error": "run not found", "data": data}, 404)
        if data.get("status") == "running":
            return _json_response({"success": False, "error": data.get("message") or "run is still running", "data": data}, 409)
        return _json_response({"success": False, "error": data.get("message") or "invalid run_id", "data": data}, 400)
    except Exception as exc:
        logging.error("删除历史run失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/runs/<run_id>/analysis", methods=["GET"])
def api_run_analysis(run_id):
    """获取某个run的报告、trace索引和坏例明细。"""
    try:
        data = get_run_analysis(run_id)
        if "error" in data:
            return _json_response({"success": False, "error": data["error"]}, 404)
        return _json_response({"success": True, "data": data})
    except Exception as exc:
        logging.error("获取run分析数据失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)


@rag_eval_bp.route("/runs/diff", methods=["GET"])
def api_run_diff():
    """对比两个run的关键指标、坏例和配置变化。"""
    try:
        base_run_id = request.args.get("base_run_id")
        candidate_run_id = request.args.get("candidate_run_id")
        return _json_response({"success": True, "data": get_run_diff(base_run_id, candidate_run_id)})
    except Exception as exc:
        logging.error("获取run对比失败: %s", exc, exc_info=True)
        return _json_response({"success": False, "error": str(exc)}, 500)
