# RAG release 与 Agent worker 生命周期 spec

## Problem Statement

当前 Agent worker 的启动检查仍主要依据旧知识库目录是否存在，不能证明当前 active pointer 指向的多模态 release 可被本进程安全使用。这样会把“目录存在”误认为“正式 release 可用”，直到首次 RAG 查询才暴露 pointer、manifest、embedding 或索引目录问题。

同时，worker 目前没有明确的优雅退出语义。容器停止时无法先停止领取新 Job、等待运行中的 Job，超时后也没有清楚说明 Job lease 如何交给后续 worker 恢复。多模态索引目录也没有明确的 active、previous、candidate 保留观测，发布流程容易留下无法判断是否可清理的历史目录。

现有架构已经把索引构建/评测/发布与查询 Runtime 解耦，也已经保留 lazy RagRuntime 和 Job lease 恢复机制。本 spec 只补齐 release readiness、worker drain、保留策略和运行文档，不改变这些既有边界。

## Solution

在现有 active release 解析链路上增加一次轻量、无重资源初始化的 readiness 检查。worker 启动时检查 active pointer、相对路径安全性、manifest 存在性与哈希、正式知识源资格、embedding 指纹、release version、collection 标识和向量目录可用性；不加载 embedding 模型、Chroma、BM25 或回答模型。检查结果写入进程级 Runtime 状态，并在 slot ready 日志中带出安全的状态、release id 和错误码。

当检查失败时，worker 继续启动并以无 RAG 降级模式运行。内部状态固定标记为 `rag_unavailable`，对外仍沿用已有稳定的 `status=unavailable` 语义；诊断只输出稳定错误码和 release id，不输出本地路径、manifest 正文、提示词、响应正文、密钥或异常堆栈。正式 retrieval policy 的缺失或非法配置继续沿用当前代码默认值回退，并记录配置来源，不把 policy 文件问题扩大为整个 RAG release 不可用。

worker 收到 SIGTERM 或 SIGINT 后进入 graceful drain：停止领取新 Job，允许已经运行的 Job 在配置的 drain 时限内完成；默认 `JOB_DRAIN_TIMEOUT_SECONDS=60`。超时后取消本地执行任务并关闭 slot 资源，但不强行把对应 Job 标记为 failed 或 cancelled；其运行 lease 保持可由既有 stale recovery 机制接管。Compose worker 的 `stop_grace_period` 至少为 75 秒，给 drain 超时后的资源关闭留下余量。

active pointer 发布时保留上一个 active pointer 为 previous pointer。状态查询增加 active、previous、candidate 版本的保留摘要和超额提示：active 与 previous 各保留一个槽位，candidate 表示已经生成但尚未成为 active 的候选版本。任何版本都不自动物理删除；清理只提供安全观测/手动决策所需信息。retrieval policy 配置与 index release 继续独立演进，发布或回滚 release 不隐式切换 policy。

同步更新实际承载 Agent worker 的 Compose 配置、运行时/部署/架构文档、README 和新增日志，明确“发布后通过 drain 与重启使新 release 生效”，不声称支持热切换、蓝绿切换或零停机。当前生产 Compose 若缺少 Agent worker 或 checkpoint 拓扑，不在本次凭空补造整套生产基础设施；文档必须以实际 Compose 为准，必要的拓扑差异作为后续事项显式记录。

## User Stories

1. As a worker operator, I want startup to validate the active RAG release identity, so that a directory that merely exists is not reported as ready.
2. As a worker operator, I want readiness to validate the pointer and manifest relationship, so that a moved or tampered release is rejected before a Job reaches RAG.
3. As a worker operator, I want embedding compatibility checked at startup, so that a release built with a different embedding fingerprint is not silently queried.
4. As a worker operator, I want readiness to remain lightweight, so that worker startup does not load embedding models or vector stores for every slot.
5. As a worker operator, I want the first real RAG query to retain lazy Runtime loading, so that idle workers do not pay the full model/index initialization cost.
6. As a worker operator, I want an unavailable release to be represented by the stable `rag_unavailable` internal state, so that downstream routing can explicitly skip RAG.
7. As an end user, I want the existing public unavailable response semantics to remain stable, so that internal diagnostics do not leak implementation details or break clients.
8. As a security reviewer, I want readiness logs to contain only safe status, release id and error code, so that paths, manifests, prompts, responses and secrets are not exposed.
9. As a worker operator, I want missing or invalid retrieval policy configuration to fall back to the code default, so that a policy typo does not incorrectly disable an otherwise valid RAG release.
10. As a worker operator, I want policy fallback source recorded, so that I can distinguish published policy from code-default behavior during diagnosis.
11. As a deployment operator, I want SIGTERM and SIGINT to stop new Job claims, so that shutdown does not keep increasing the amount of work that must drain.
12. As a deployment operator, I want running Jobs to get a bounded drain period, so that normal container replacement can finish work without indefinite shutdown.
13. As a deployment operator, I want a drain timeout to leave an unfinished running Job recoverable by stale lease recovery, so that shutdown does not invent a false terminal failure.
14. As a deployment operator, I want the container stop grace period to exceed the drain timeout, so that the worker has time to close slot resources after the drain decision.
15. As an operator, I want the slot ready log to include the RAG readiness state and release id, so that I can correlate a worker process with the release it accepted.
16. As an index maintainer, I want a new active pointer publication to preserve the prior active pointer, so that rollback and incident diagnosis have an explicit previous release.
17. As an index maintainer, I want status output to distinguish active, previous and candidate versions, so that staged material is not mistaken for production material.
18. As an index maintainer, I want candidate overflow reported without automatic deletion, so that an observation command cannot destroy a source, index or evaluation artifact.
19. As an evaluation operator, I want staged evaluation and production publication to remain explicit, so that readiness checks cannot authorize active-pointer changes.
20. As an evaluation operator, I want an isolated evaluation to keep its own release identity, so that it cannot switch the global active pointer.
21. As a deployment operator, I want the worker-bearing Compose files to pass the same drain configuration, so that local, compatibility and staging behavior do not diverge accidentally.
22. As a staging operator, I want the active release and policy artifacts available through explicit read-only mounts, so that the container validates the same release that the host published.
23. As a maintainer, I want runtime, deployment and architecture documentation to describe the actual worker lifecycle, so that future changes do not reintroduce directory-only readiness or abrupt shutdown claims.
24. As a maintainer, I want focused tests for readiness, drain timeout, pointer retention and Compose configuration, so that the release boundary can be changed without relying on a real model call.
25. As a maintainer, I want unrelated database schema, public API and evaluation behavior unchanged, so that this reliability change remains narrowly scoped.

## Implementation Decisions

- Reuse the existing RAG Runtime configuration resolver as the highest shared seam. Add a small readiness value result rather than a second release-resolution implementation.
- Extend process-level worker Runtime state with a stable readiness status, optional release id and safe error code. Preserve construction compatibility for existing tests and callers that provide only the LLM and boolean availability.
- Keep the existing boolean `rag_available` input to graph construction. The new status is diagnostic and stateful; it must not become a second routing source that conflicts with the boolean.
- Readiness must call only configuration/pointer/manifest/index-directory checks. It must not call heavy Runtime construction, Chroma collection opening, BM25 loading, embedding model creation or an LLM request.
- Classify readiness failures into stable categories such as missing release, invalid release, missing dependency and readiness check failure. Do not serialize exception messages into public responses or normal worker logs.
- Keep retrieval policy resolution independent. Missing/invalid policy continues to use the existing code-default fallback and source marker.
- Implement shutdown as a process-level stop event shared by all slots. The slot loop checks it before claiming and while idle; a currently running `run_job` is allowed to finish during the drain window.
- On drain timeout, cancel the local slot task only after the bounded wait. Do not call terminal Job failure/cancellation paths solely because the worker process is shutting down. Rely on existing lease expiry and stale recovery for unfinished work.
- Add a positive integer `JOB_DRAIN_TIMEOUT_SECONDS` setting with default 60 seconds. Worker Compose services set it explicitly through environment substitution, and their stop grace period is at least 75 seconds.
- Preserve the existing lazy per-process RAG service singleton and its active pointer snapshot behavior. Changing active pointer still requires worker restart to affect a running process.
- Add a previous pointer beside the active pointer. Publishing a different version snapshots the current active pointer before atomically replacing the active pointer. The first publication has no previous pointer.
- Add a read-only retention/status summary to the existing multimodal maintenance status surface. It must list protected active/previous versions, candidate versions, and whether candidate count exceeds the one-candidate policy slot. It must never delete files.
- Update Compose only where the corresponding worker service exists. Development and compatibility Compose already expose the repository; staging must explicitly expose the release/index/runtime/policy directories read-only. Do not add a speculative production worker plus an unverified checkpoint topology in this change.
- Keep source, staged index, evaluation artifact, active pointer and production policy provenance visible in documentation. Do not claim that readiness is an evaluation or publication gate by itself.
- Append a new changelog entry rather than rewriting historical entries.

## Testing Decisions

- Tests assert externally meaningful behavior and safe state transitions, not the exact private helper layout.
- Worker Runtime tests must prove: a valid fake release yields `available` and its release id; missing/invalid release yields `rag_unavailable` with a safe error code; readiness does not construct heavy RAG resources; legacy explicit `ProcessRuntime` construction remains compatible.
- Worker lifecycle tests must prove: stop event prevents further idle polling/claims; a running slot gets the configured drain window; timeout cancels the local task without invoking a terminal Job failure/cancellation mutation; all slot tasks and signal waiters are cleaned up.
- Active pointer tests must prove: first publication has no previous pointer; publishing a new version preserves the prior active pointer; status separates active/previous/candidates; candidate overflow is observable and no directory is deleted.
- Policy tests should reuse existing retrieval configuration tests to prove missing and malformed production policy still reports code-default fallback rather than `rag_unavailable`.
- Compose tests should parse the worker-bearing configurations and assert the drain environment and stop grace settings. Staging tests should assert read-only release/policy mounts where those mounts are part of the implementation.
- Documentation checks should verify the new setting, readiness/degraded mode, restart requirement and drain timeout are present without asserting stale historical metrics.
- Run focused unit tests first, then the repository-prescribed Docker unit test subset if dependencies require it. Also run Python syntax compilation, Compose parsing/config expansion where possible, `git diff --check`, and the directly affected documentation checks.
- Do not treat a zero-call evaluation, a green unit suite, a build/integrity gate, or an active pointer file write as evidence of production RAG quality improvement.

## Out of Scope

- Zero-downtime deployment, blue-green worker pools, hot Runtime reload, live active-pointer switching inside a running process, or automatic worker self-restart.
- Automatic physical deletion, pruning or garbage collection of active, previous, candidate, staged, asset or evaluation directories.
- Fallback from an invalid active release to the legacy `Agent/knowledge_base/db` corpus.
- Turning a missing RAG release into a worker-wide startup failure when LLM, database and checkpoint prerequisites are healthy.
- Marking a running Job failed or cancelled merely because the worker received a termination signal or drain timeout.
- Coupling retrieval policy publication to index release publication.
- Changing public Job APIs, database schema, checkpoint ownership, lease semantics or evaluation scoring protocols.
- Re-running production ingestion, external VLM calls, Ragas, benchmark claims or active-pointer publication as part of unit verification.
- Rebuilding the entire production Compose topology when the current production file does not actually define the corresponding worker/checkpoint services.
- Commit, push, branch cleanup or deletion of existing user data.

## Further Notes

- The current checkout and active release must be revalidated during implementation; this document is a behavioral contract, not a claim that every historical index directory is valid.
- The implementation must preserve unrelated worktree changes and must not rewrite historical changelog entries.
- The implementation is complete only when the focused tests and static/deployment checks pass, the final diff is limited to this spec, the requested worker/release behavior, its tests, and directly affected documentation/logging.
- Suggested change batch: `feat(worker):补齐 RAG release readiness 与优雅 drain`.
