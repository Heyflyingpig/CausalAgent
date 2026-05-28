# Ragas 论文带读教程：从论文思想到本项目 RAG 评测落地

本文是对 `Ragas: Automated Evaluation of Retrieval Augmented Generation` 的带读笔记，并结合当前项目 phase0 已经完成的 RAG 评测基础，说明我们应该如何把论文思想转化成一个更自动化、更可信、更容易回归的 RAG 评测系统。

本教程的重点不是复述论文，而是回答三个问题：

1. Ragas 论文到底解决了什么问题？
2. 它的指标和我们当前 `rag_eval.py` 有什么关系？
3. 在当前 phase0 基础上，下一步应该怎么接入自动化评测？

## 0. 当前项目 Phase0 基础

在读 Ragas 之前，先明确我们现在已经有什么。

当前 RAG 相关内容已经集中到：

```text
Agent/knowledge_base/rag/
```

当前已经完成：

- 本地知识库：
  - `source/` 存放 PDF / 文档资料。
  - `models/` 存放本地 embedding 模型 `bge-small-zh-v1.5`。
  - `db/` 存放 FAISS 向量库。
- RAG 主链路：
  - `query_rag.py`
  - dense retrieve
  - dense threshold
  - MMR
  - sparse retrieve
  - merge / rerank
  - final evidence
- 检索评测：
  - `rag_eval.py`
  - `rag_eval_sample.json`
  - `generate_rag_candidates.py`
  - `output/reports/rag_eval_report.md`
  - `output/reports/rag_eval_sweep_report.md`
- 已有检索阶段指标：
  - `recall_at_k`
  - `precision_at_k`
  - `mrr`
  - `hit_rate`
  - `stage_metrics`
  - `loss_reason_counts`

Phase0 的价值是：我们已经能评估“检索链路有没有把人工指定的 gold chunk 找回来”。  
Phase0 的限制是：它仍然依赖 `gold_chunk_ids`，而 chunk id 会随着知识库扩充、chunk 策略变化、PDF 解析变化而失效。

Ragas 论文正好可以帮助我们走向下一阶段：减少对人工 chunk 级 gold 的依赖，建立自动化 RAG 评测 baseline。

## 1. 论文一句话总结

Ragas 提出了一套用于 RAG 系统的自动化评测框架，重点评估三个方面：

- 检索到的上下文是否聚焦且相关。
- 生成答案是否真正回答了用户问题。
- 生成答案是否忠于检索到的上下文。

论文特别强调：很多 RAG 项目在真实业务中没有人工 reference answer，也没有完整标注数据。因此，Ragas 试图在没有大量人工标注的情况下，用 LLM-as-judge 的方式评估 RAG pipeline。

这和我们当前遇到的问题非常接近：

```text
人工 gold_chunk_ids 可信，但维护成本高；
知识库变大后，chunk 级 gold 容易失效；
我们需要自动化 baseline 来提高评测效率。
```

## 2. 论文的问题背景

RAG 的基本流程是：

```text
question -> retrieve context -> generate answer
```

论文认为，RAG 系统的质量不能只看最终答案，因为最终答案背后至少有两个模块：

- retrieval module：负责找证据。
- generation module：负责基于证据回答。

如果最终回答不好，可能有多种原因：

- 检索没找到相关上下文。
- 检索找到了，但上下文太冗余。
- 上下文是对的，但 LLM 没用好。
- LLM 编造了上下文里没有的内容。
- LLM 回答偏题。

这正是我们为什么之前把 `rag_eval.py` 做成分阶段指标的原因。  
不过 Ragas 进一步提醒我们：除了检索是否命中 gold chunk，还要评估生成答案是否忠于 evidence。

## 3. Ragas 的三个核心维度

论文中重点讨论三个 quality aspects。

### 3.1 Faithfulness

Faithfulness 关注的是：

```text
answer 里的 claim 是否能被 retrieved context 支撑。
```

它不是问“答案是否真实”，而是问：

```text
这个答案是否忠于当前给它的证据？
```

举例：

```text
context: Pearl 认为干预语义是因果推断的核心。
answer: 因果推断只需要相关性分析。
```

即使这句话看起来像一个答案，它也不 faithful，因为它不能从 context 推出，甚至和 context 冲突。

论文中的做法大致分两步：

1. 先让 LLM 把 answer 拆成若干 statements。
2. 再让 LLM 判断每个 statement 是否被 context 支撑。

最终分数可以理解为：

```text
被 context 支撑的 statements 数量 / answer 中 statements 总数
```

和本项目的关系：

- 现在 `rag_eval.py` 只评估 retrieval。
- 后续 `ragas_eval.py` 或 `claim_eval.py` 应该评估 faithfulness。
- 这能直接回答“回答是否幻觉”这个问题。

### 3.2 Answer Relevance

Answer Relevance 关注的是：

```text
answer 是否真正回答了 question。
```

它不主要判断事实对错，而是判断回答是否对题。

例如：

```text
question: 什么是混杂因素？
answer: 因果推断是一个重要研究领域。
```

这可能不是胡说，但它没有回答问题，所以 answer relevance 低。

论文里的思路是：从 answer 反向生成可能的问题，然后和原始 question 比较语义相似度。  
实际工程中，我们不一定要完全照搬这个实现，但要保留这个评估维度。

和本项目的关系：

- 因果 Agent 里，最终回答可能很长。
- 有时答案忠于证据，但没有正面回答问题。
- Answer relevance 可以帮助区分“有证据但答偏了”的情况。

### 3.3 Context Relevance

Context Relevance 关注的是：

```text
retrieved context 是否足够聚焦，是否包含太多无关内容。
```

这点对 RAG 很重要，因为：

- context 太长会增加成本。
- 无关 context 会干扰 LLM。
- LLM 对长上下文中间位置的信息利用能力可能下降。

论文中的做法是：让 LLM 从 context 中抽取对回答 question 有用的句子，再用“有用句子占全部句子的比例”估计 context relevance。

和本项目的关系：

- 我们现在有 `precision_at_k`，但它依赖人工 `gold_chunk_ids`。
- Ragas 的 context relevance 可以在没有 gold chunk 的情况下自动评估 context 是否聚焦。
- 这可以作为我们未来替代大量人工 gold 的重要指标。

## 4. Ragas 和我们当前 rag_eval.py 的区别

当前 `rag_eval.py` 更像传统 IR / retrieval benchmark：

```text
question + gold_chunk_ids -> retrieved chunks -> recall / precision / MRR
```

Ragas 更像 RAG pipeline benchmark：

```text
question + retrieved contexts + answer -> context relevance / answer relevance / faithfulness
```

二者不是替代关系，而是互补关系。

| 维度 | 当前 rag_eval.py | Ragas |
| --- | --- | --- |
| 主要对象 | 检索结果 | 检索上下文 + 生成答案 |
| 是否需要人工 gold chunk | 需要 | 不一定需要 |
| 是否评估生成忠实性 | 否 | 是 |
| 是否适合检索参数调优 | 很适合 | 辅助 |
| 是否适合自动化回归 | 部分适合 | 很适合 |
| 是否能解释链路阶段 | 当前项目较强 | 需要配合 trace |

结论：

```text
rag_eval.py 不应该废弃。
Ragas 应该作为自动化评测层接入。
```

## 5. 论文实验：WikiEval 给我们的启发

论文构建了 WikiEval，用来验证 Ragas 指标和人工判断是否一致。

数据构造大致包括：

- 选择 Wikipedia 页面。
- 生成可以由页面内容回答的问题。
- 生成答案。
- 让人工标注 faithfulness、answer relevance、context relevance。
- 比较 Ragas 指标和人工判断的一致性。

实验结论中，Ragas 在 faithfulness 上和人工判断比较一致；answer relevance 也有效；context relevance 更难，因为判断哪些句子“真正关键”本身就比较复杂。

这给我们的启发：

1. 自动评估不是绝对真理，但可以显著加快评测循环。
2. Faithfulness 是最值得优先接入的指标。
3. Context relevance 很有价值，但要谨慎解释。
4. 少量人工复核仍然必要。

## 6. 对本项目的核心启发

### 6.1 不要继续扩大大量 gold_chunk_ids

`gold_chunk_ids` 的问题是：

- chunk id 不稳定。
- 知识库扩充后，旧 gold 可能不是唯一正确证据。
- chunk 策略变化后，gold 需要重找。
- 维护成本随着样本数量线性上升。

因此未来不应把大量 `gold_chunk_ids` 当成唯一核心 benchmark。

建议转向：

```text
少量 gold_chunk_ids -> smoke test
expected_claims -> 语义级 gold
reference_answer -> 生成质量参考
judge_rubric -> LLM judge 判分标准
Ragas metrics -> 自动化 baseline
```

### 6.2 把人工工作从“找 chunk”升级为“写 rubric”

更稳定的样本结构应该是：

```json
{
  "question": "因果关系和相关性有什么区别？",
  "question_type": "comparison",
  "expected_corpus": "official",
  "expected_claims": [
    "相关性描述变量共同变化，不等于因果作用。",
    "因果关系涉及干预或反事实变化。",
    "仅凭观察相关性通常不能推出因果关系。"
  ],
  "reference_answer": "相关性说明变量之间存在统计关联，但因果关系要求一个变量的改变会导致另一个变量改变，通常需要干预或反事实语义支持。",
  "gold_chunk_ids": [],
  "judge_rubric": {
    "must_cover": [
      "相关性不等于因果",
      "因果涉及干预或反事实",
      "观察相关性不足以证明因果"
    ],
    "avoid": [
      "把相关性直接说成因果",
      "脱离证据编造例子"
    ]
  }
}
```

这种结构比 chunk id 更稳定，因为它评估的是知识点是否被覆盖，而不是某个具体 chunk 是否被召回。

### 6.3 自动化评测不能脱离 trace

Ragas 可以给分，但如果没有 trace，我们很难知道为什么分数低。

因此本项目后续应该保持两条线并行：

```text
Ragas 自动打分
retrieval trace 分阶段诊断
```

例如：

```text
faithfulness 低：
  可能是 final evidence 不支持 answer
  也可能是 answer 编造

context relevance 低：
  可能是 dense 召回太宽
  也可能是 rerank 没排好
  也可能是 final_top_k 太大
```

只有配合 `build_retrieval_trace()`，这些自动分数才真正可解释。

## 7. 本项目接入 Ragas 的建议架构

建议新增：

```text
Agent/knowledge_base/rag/rag_eval/ragas_eval.py
```

输入来自当前 RAG：

```text
question
retrieved_contexts
answer
reference_answer 可选
expected_claims 可选
```

输出到：

```text
Agent/knowledge_base/rag/output/
  machine/
    ragas_eval_result.json
  reports/
    ragas_eval_report.md
```

最小流程：

```text
rag_eval_sample.json
  -> 调用 query_rag.py 生成 retrieved_contexts + answer
  -> 转成 Ragas dataset
  -> 运行 faithfulness / answer_relevancy / context_relevance
  -> 输出 JSON + Markdown
```

注意：Ragas baseline 的第一版不要追求覆盖所有指标。  
建议先跑：

```text
faithfulness
answer_relevancy
context_relevance
```

如果后续样本有 `reference_answer` 或 `expected_claims`，再补：

```text
context_recall
answer_correctness
claim_coverage
```

## 8. 和 Phase0 成果的对应关系

| Phase0 已有内容 | Ragas 接入时怎么复用 |
| --- | --- |
| `query_rag.py` | 提供 retrieved contexts 和 answer |
| `build_retrieval_trace()` | 提供分阶段 trace，帮助解释自动分数 |
| `rag_eval_sample.json` | 升级为自动评估数据集 |
| `rag_eval.py` | 保留检索 smoke test 和参数 sweep |
| `output/machine/` | 存放 Ragas JSON、缓存和机器可读 bad case 文件 |
| `output/reports/` | 存放 Markdown 报告 |
| `RAG测评框架开发.md` | 作为路线图 |

接入后，我们会有两类报告：

```text
retrieval report:
  看检索是否命中人工 smoke gold，以及各阶段是否掉点。

ragas report:
  看 context 是否相关、answer 是否对题、answer 是否忠于 evidence。
```

这两个报告一起看，才是完整 RAG 评测。

## 9. 推荐学习顺序

读这篇论文时，可以按下面顺序理解：

1. 先看 Abstract 和 Introduction：理解为什么 RAG 需要自动评测。
2. 看 Evaluation Strategies：重点理解 faithfulness、answer relevance、context relevance。
3. 看 WikiEval Dataset：理解论文如何用人工标注验证自动指标。
4. 看 Experiments：理解自动指标和人工判断的一致性。
5. 回到本项目：思考哪些指标能直接接入，哪些需要改数据结构。

不要一开始纠结公式。  
更重要的是理解它的评测拆分思想：

```text
context 是否好
answer 是否回答问题
answer 是否忠于 context
```

## 10. 本项目下一步实操建议

### Step 1：升级评测样本

在 `rag_eval_sample.json` 中逐步增加：

- `expected_claims`
- `reference_answer`
- `judge_rubric`

保留少量 `gold_chunk_ids`，但不要继续大规模人工找 chunk。

### Step 2：新增 ragas_eval.py

第一版只做：

- 读取前 5-10 条样本。
- 调用当前 RAG 生成 answer 和 contexts。
- 跑 Ragas 的核心指标。
- 输出 JSON 和 Markdown。

### Step 3：对照现有 rag_eval.py

同一批问题同时跑：

```text
rag_eval.py
ragas_eval.py
```

然后比较：

- retrieval recall 高但 faithfulness 低：说明生成没用好证据。
- retrieval recall 低但 answer relevance 高：可能是模型凭参数知识回答，存在不可控风险。
- context relevance 低但 faithfulness 高：说明答案没乱编，但检索上下文冗余。
- faithfulness 高但 answer relevance 低：说明答案忠于证据但答偏了。

### Step 4：接入 trace 可视化

Ragas 给分，trace 解释原因。

后续可以新增：

```text
trace_export.py
phoenix_trace.py
```

输出：

```text
question -> dense -> sparse -> rerank -> final evidence -> answer -> ragas scores
```

## 11. 最终应该形成的能力

最终 RAG 评测系统应该能做到：

- 不依赖大量人工 `gold_chunk_ids`。
- 能自动评估 context relevance、answer relevance、faithfulness。
- 能保留少量人工 smoke test，防止自动评估漂移。
- 能可视化检索和生成链路。
- 能在知识库扩充后自动回归。
- 能输出项目组能看懂的 Markdown 报告。
- 能帮助我们定位问题到底发生在：
  - chunking
  - embedding
  - dense retrieval
  - sparse retrieval
  - MMR
  - rerank
  - final evidence
  - LLM generation

## 12. 读完论文后的关键 takeaway

Ragas 论文最重要的价值不是某一个具体公式，而是它告诉我们：

```text
RAG 评测不能只看最终答案，也不能只看检索命中。
它至少要同时评估 context、answer relevance 和 faithfulness。
```

对本项目来说，最合适的路线是：

```text
保留 rag_eval.py 做少量人工强基准；
新增 ragas_eval.py 做自动化 baseline；
用 expected_claims / reference_answer 替代大量 gold_chunk_ids；
用 trace 可视化解释自动评测分数。
```

这条路线既符合 Ragas 论文思想，也适合我们当前 phase0 已经完成的工程基础。
