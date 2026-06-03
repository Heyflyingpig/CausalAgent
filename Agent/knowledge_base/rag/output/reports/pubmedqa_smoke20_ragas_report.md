# Ragas Baseline Report（Ragas 基线报告）

## Run Info（运行信息）

| field（字段） | value（值） |
| --- | --- |
| status（状态） | pass |
| ragas_version（Ragas 版本） | 0.4.3 |
| judge_model（评测模型） | deepseek-v4-flash |
| judge_profile（评测器配置） | pubmedqa_smoke20 |
| active_profile（启用配置） | pubmedqa_smoke20 |
| dataset_path（数据集路径） | D:\project\CausalAgent-demopaper\Agent\knowledge_base\rag\data\external\pubmedqa\processed\pubmedqa_eval_dataset.json |
| sample_count（样本数） | 20 |
| source_sample_count（源样本数） | 1000 |
| build_seconds（构建耗时秒数） | 0.0000 |
| eval_seconds（评测耗时秒数） | 1317.1280 |
| repeat_count（重复评测次数） | 1 |
| loaded_from_cache（是否读取数据集缓存） | True |
| loaded_score_from_cache（是否读取分数缓存） | False |
| ragas_timeout（Ragas 超时秒数） | 1200 |
| ragas_max_workers（Ragas 最大并发数） | 1 |
| answer_relevancy_strictness（回答相关性严格度） | 1 |
| low_score_threshold（低分阈值） | 0.5 |

## Score Summary（分数汇总）

| metric（指标） | mean（均值） | std（标准差） | valid | nan（空值数） | total（总数） |
| --- | ---: | ---: | ---: | ---: | ---: |
| faithfulness（忠实性） | 0.7773 | 0.0000 | 20 | 0 | 20 |
| answer_relevancy（回答相关性） | 0.7014 | 0.0000 | 20 | 0 | 20 |
| context_utilization（上下文利用率） | 0.8500 | 0.0000 | 20 | 0 | 20 |
| context_recall（上下文召回率） | 0.5750 | 0.0000 | 20 | 0 | 20 |

## Low Score / NaN Cases（低分或空值样本）

| q（题号） | metric（指标） | score | reason（原因） | question（问题） |
| ---: | --- | ---: | --- | --- |
| 3 | answer_relevancy（回答相关性） | 0.0000 | below_threshold | Syncope during bathing in infants, a pediatric form of water-induced urticaria? |
| 4 | faithfulness（忠实性） | 0.0000 | below_threshold | Are the long-term results of the transanal pull-through equal to those of the transabdominal pull-through? |
| 4 | answer_relevancy（回答相关性） | 0.0000 | below_threshold | Are the long-term results of the transanal pull-through equal to those of the transabdominal pull-through? |
| 4 | context_utilization（上下文利用率） | 0.0000 | below_threshold | Are the long-term results of the transanal pull-through equal to those of the transabdominal pull-through? |
| 4 | context_recall（上下文召回率） | 0.3333 | below_threshold | Are the long-term results of the transanal pull-through equal to those of the transabdominal pull-through? |
| 5 | context_recall（上下文召回率） | 0.1667 | below_threshold | Can tailored interventions increase mammography use among HMO women? |
| 6 | faithfulness（忠实性） | 0.0000 | below_threshold | Double balloon enteroscopy: is it efficacious and safe in a community setting? |
| 6 | answer_relevancy（回答相关性） | 0.0000 | below_threshold | Double balloon enteroscopy: is it efficacious and safe in a community setting? |
| 6 | context_recall（上下文召回率） | 0.0000 | below_threshold | Double balloon enteroscopy: is it efficacious and safe in a community setting? |
| 8 | context_recall（上下文召回率） | 0.3333 | below_threshold | Is adjustment for reporting heterogeneity necessary in sleep disorders? |
| 13 | context_recall（上下文召回率） | 0.0000 | below_threshold | Differentiation of nonalcoholic from alcoholic steatohepatitis: are routine laboratory markers useful? |
| 14 | context_recall（上下文召回率） | 0.3333 | below_threshold | Prompting Primary Care Providers about Increased Patient Risk As a Result of Family History: Does It Work? |
| 16 | faithfulness（忠实性） | 0.2000 | below_threshold | Patient-Controlled Therapy of Breathlessness in Palliative Care: A New Therapeutic Concept for Opioid Administration? |
| 17 | answer_relevancy（回答相关性） | 0.0000 | below_threshold | Is there still a need for living-related liver transplantation in children? |
| 17 | context_recall（上下文召回率） | 0.3333 | below_threshold | Is there still a need for living-related liver transplantation in children? |
| 18 | context_recall（上下文召回率） | 0.0000 | below_threshold | Do patterns of knowledge and attitudes exist among unvaccinated seniors? |

## Cross Metric Bad Cases（跨指标问题样本）

| field（字段） | value（值） |
| --- | --- |
| shared_count（共同样本数） | 20 |
| ragas_only_count | 0 |
| retrieval_only_count（仅检索样本数） | 0 |
| bad_case_count | 10 |
| ragas_low_threshold | 0.5 |
| retrieval_recall_low_threshold | 0.67 |
| retrieval_mrr_low_threshold | 0.5 |

| q（题号） | retrieval_recall（检索召回率） | retrieval_mrr（检索 MRR） | final_gold_rank（最终 gold 排名） | low_ragas | nan_ragas（Ragas 空值指标） | categories（类别） | question（问题） |
| ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| 3 | 1.0000 | 1.0000 | 1 | answer_relevancy | None | retrieval_ok_ragas_bad, loss:final_hit | Syncope during bathing in infants, a pediatric form of water-induced urticaria? |
| 4 | 1.0000 | 1.0000 | 1 | faithfulness, answer_relevancy, context_utilization, context_recall | None | retrieval_ok_ragas_bad, loss:final_hit | Are the long-term results of the transanal pull-through equal to those of the transabdominal pull-through? |
| 5 | 1.0000 | 1.0000 | 1 | context_recall | None | retrieval_ok_ragas_bad, loss:final_hit | Can tailored interventions increase mammography use among HMO women? |
| 6 | 1.0000 | 0.3333 | 3 | faithfulness, answer_relevancy, context_recall | None | retrieval_and_generation_bad, loss:final_hit | Double balloon enteroscopy: is it efficacious and safe in a community setting? |
| 8 | 1.0000 | 1.0000 | 1 | context_recall | None | retrieval_ok_ragas_bad, loss:final_hit | Is adjustment for reporting heterogeneity necessary in sleep disorders? |
| 13 | 1.0000 | 1.0000 | 1 | context_recall | None | retrieval_ok_ragas_bad, loss:final_hit | Differentiation of nonalcoholic from alcoholic steatohepatitis: are routine laboratory markers useful? |
| 14 | 1.0000 | 1.0000 | 1 | context_recall | None | retrieval_ok_ragas_bad, loss:final_hit | Prompting Primary Care Providers about Increased Patient Risk As a Result of Family History: Does It Work? |
| 16 | 1.0000 | 1.0000 | 1 | faithfulness | None | retrieval_ok_ragas_bad, loss:final_hit | Patient-Controlled Therapy of Breathlessness in Palliative Care: A New Therapeutic Concept for Opioid Administration? |
| 17 | 1.0000 | 1.0000 | 1 | answer_relevancy, context_recall | None | retrieval_ok_ragas_bad, loss:final_hit | Is there still a need for living-related liver transplantation in children? |
| 18 | 1.0000 | 1.0000 | 1 | context_recall | None | retrieval_ok_ragas_bad, loss:final_hit | Do patterns of knowledge and attitudes exist among unvaccinated seniors? |

## Per Question（逐题详情）

### Q1. Do mitochondria play a role in remodelling lace plant leaves during programmed cell death?

- question_type（问题类型）: 
- context_count（上下文数量）: 3
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2, E3
- scores: faithfulness=1.0000, answer_relevancy=0.9736, context_utilization=0.5833, context_recall=0.5000
- answer_preview（回答预览）: 是的，线粒体在lace plant叶片程序性细胞死亡（PCD）中发挥作用。证据表明，在Aponogeton madagascariensis（lace plant）中，发育调控的PCD涉及线粒体动力学，包括膜电位变化和线粒体通透性转换孔（PTP）的形成。

### Q2. Landolt C and snellen e acuity: differences in strabismus amblyopia?

- question_type（问题类型）: 
- context_count（上下文数量）: 3
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2
- scores: faithfulness=1.0000, answer_relevancy=0.7048, context_utilization=1.0000, context_recall=1.0000
- answer_preview（回答预览）: 在斜视性弱视眼中，Landolt C 视力（LR）和 Snellen E 视力（SE）的差异很小。平均小数视力值 LR 为 0.14，SE 为 0.16，平均差异为 0.55 行，且 SE 的测量值略高于 LR。

### Q3. Syncope during bathing in infants, a pediatric form of water-induced urticaria?

- question_type（问题类型）: 
- context_count（上下文数量）: 3
- answer_status（回答状态）: insufficient_evidence
- answer_confidence（回答置信度）: low
- citations: E1, E2
- scores: faithfulness=0.7500, answer_relevancy=0.0000, context_utilization=1.0000, context_recall=1.0000
- answer_preview（回答预览）: 根据当前检索到的证据，无法可靠回答该问题。证据中仅提及对婴儿洗澡时晕厥症状的观察，并提出了“水源性荨麻疹类似病”的假设，但并未明确确认其为儿童水源性荨麻疹的一种形式。

### Q4. Are the long-term results of the transanal pull-through equal to those of the transabdominal pull-through?

- question_type（问题类型）: 
- context_count（上下文数量）: 3
- answer_status（回答状态）: insufficient_evidence
- answer_confidence（回答置信度）: low
- citations: None
- scores: faithfulness=0.0000, answer_relevancy=0.0000, context_utilization=0.0000, context_recall=0.3333
- answer_preview（回答预览）: 证据已检索，但回答生成失败：Error code: 400 - {'error': {'message': 'This response_format type is unavailable now', 'type': 'invalid_request_error', 'param': None, 'code': 'i

### Q5. Can tailored interventions increase mammography use among HMO women?

- question_type（问题类型）: 
- context_count（上下文数量）: 3
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2, E3
- scores: faithfulness=0.8571, answer_relevancy=0.9409, context_utilization=0.8333, context_recall=0.1667
- answer_preview（回答预览）: Yes, tailored interventions (telephone counseling and tailored print communications) can increase mammography use among HMO women. In a randomized trial, teleph

### Q6. Double balloon enteroscopy: is it efficacious and safe in a community setting?

- question_type（问题类型）: 
- context_count（上下文数量）: 3
- answer_status（回答状态）: insufficient_evidence
- answer_confidence（回答置信度）: low
- citations: None
- scores: faithfulness=0.0000, answer_relevancy=0.0000, context_utilization=1.0000, context_recall=0.0000
- answer_preview（回答预览）: 根据当前检索到的证据，无法可靠回答该问题。

### Q7. 30-Day and 1-year mortality in emergency general surgery laparotomies: an area of concern and need for improvement?

- question_type（问题类型）: 
- context_count（上下文数量）: 3
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2
- scores: faithfulness=0.7500, answer_relevancy=0.8911, context_utilization=1.0000, context_recall=0.5000
- answer_preview（回答预览）: 根据检索到的证据，急诊普外科剖腹手术的30天死亡率为14-15%（近期研究），具体数据为：<70岁患者12%，≥70岁患者22%（p<0.001）；1年死亡率为：<70岁患者25%，≥70岁患者38%（p<0.001）。这表明年龄是显著的风险因素，且总体死亡率较高，是值得关注和改进的领域。

### Q8. Is adjustment for reporting heterogeneity necessary in sleep disorders?

- question_type（问题类型）: 
- context_count（上下文数量）: 3
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2
- scores: faithfulness=1.0000, answer_relevancy=1.0000, context_utilization=1.0000, context_recall=0.3333
- answer_preview（回答预览）: Yes, adjustment for reporting heterogeneity is necessary in sleep disorders, as evidenced by studies showing that correction for cut-point shifts (e.g., using a

### Q9. Do mutations causing low HDL-C promote increased carotid intima-media thickness?

- question_type（问题类型）: 
- context_count（上下文数量）: 3
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2
- scores: faithfulness=1.0000, answer_relevancy=1.0000, context_utilization=1.0000, context_recall=1.0000
- answer_preview（回答预览）: No, mutations causing low HDL-C (in LCAT, ABCA1, and APOA1) do not promote increased carotid intima-media thickness; a case-control study found nearly identical

### Q10. A short stay or 23-hour ward in a general and academic children's hospital: are they effective?

- question_type（问题类型）: 
- context_count（上下文数量）: 3
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2, E3, E4
- scores: faithfulness=0.8571, answer_relevancy=0.9687, context_utilization=0.5833, context_recall=1.0000
- answer_preview（回答预览）: 是的，根据证据，短期停留或23小时病房在综合性和学术性儿童医院中是有效的。数据显示，该病房提高了医院效率，仅1%的入院停留超过23小时，转入住院病床率低（4%-6%），72小时内非计划再就诊率低于1%，且无不良事件报告，父母满意度高。

### Q11. Did Chile's traffic law reform push police enforcement?

- question_type（问题类型）: 
- context_count（上下文数量）: 3
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2
- scores: faithfulness=1.0000, answer_relevancy=0.9220, context_utilization=1.0000, context_recall=0.5000
- answer_preview（回答预览）: 是的，智利的交通法改革推动了警方执法。证据显示，2005年交通法改革后，记录的警方交通执法有所增加，并且实证分析表明，改革与每位警官的交通罚单数量相互作用，与交通死亡和重伤的显著下降相关。

### Q12. Therapeutic anticoagulation in the trauma patient: is it safe?

- question_type（问题类型）: 
- context_count（上下文数量）: 3
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2
- scores: faithfulness=1.0000, answer_relevancy=0.7909, context_utilization=0.5833, context_recall=0.5000
- answer_preview（回答预览）: 基于现有证据，治疗性抗凝在创伤患者中存在显著并发症风险（21%的患者出现至少一种并发症，包括出血和死亡，死亡率4%），因此并非完全安全。

### Q13. Differentiation of nonalcoholic from alcoholic steatohepatitis: are routine laboratory markers useful?

- question_type（问题类型）: 
- context_count（上下文数量）: 3
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2
- scores: faithfulness=1.0000, answer_relevancy=0.8291, context_utilization=1.0000, context_recall=0.0000
- answer_preview（回答预览）: 根据检索到的证据，常规实验室指标（如AST/ALT比值、平均红细胞体积MCV）在鉴别非酒精性脂肪性肝炎（NASH）与酒精性脂肪性肝炎（ASH）方面有一定作用。ASH患者中更常见AST/ALT比值>1（54.1% vs 20.7%，P=0.0008）以及MCV升高（53% vs 0%，P<0.0001），多变量分析显示M

### Q14. Prompting Primary Care Providers about Increased Patient Risk As a Result of Family History: Does It Work?

- question_type（问题类型）: 
- context_count（上下文数量）: 3
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2, E3
- scores: faithfulness=1.0000, answer_relevancy=0.8187, context_utilization=0.8333, context_recall=0.3333
- answer_preview（回答预览）: 根据证据，虽然实施了自动定制的家族史风险提示，但在492名患者、847次就诊中，有695次有医生回应，其中53.5%查看了家族史，22.9%讨论了家族史，22.3%未处理，仅0.7%查看了并安排了测试/转诊，且没有显著变化。因此，这种提示并未显著改变初级保健提供者的行为，效果有限。

### Q15. Do emergency ultrasound fellowship programs impact emergency medicine residents' ultrasound education?

- question_type（问题类型）: 
- context_count（上下文数量）: 3
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E3
- scores: faithfulness=1.0000, answer_relevancy=0.7089, context_utilization=0.5833, context_recall=1.0000
- answer_preview（回答预览）: 是的，根据检索到的证据，急诊超声（EUS）专科培训项目对急诊医学住院医师的超声教育有显著正向影响。具体而言，在设有EUS专科培训项目的项目中，住院医师报告的超声检查数量更多（P = .04），并且在大多数床边超声应用方面与没有该培训项目的项目存在显著差异（P < .05）。

### Q16. Patient-Controlled Therapy of Breathlessness in Palliative Care: A New Therapeutic Concept for Opioid Administration?

- question_type（问题类型）: 
- context_count（上下文数量）: 3
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2, E3
- scores: faithfulness=0.2000, answer_relevancy=0.6033, context_utilization=1.0000, context_recall=1.0000
- answer_preview（回答预览）: 根据检索到的证据，该研究（pubmedqa_26578404）提出了患者自控治疗（PCT）作为姑息治疗中呼吸困难的一种新的阿片类药物给药概念，并通过一项18名晚期患者的试点观察研究初步验证了其可行性。

### Q17. Is there still a need for living-related liver transplantation in children?

- question_type（问题类型）: 
- context_count（上下文数量）: 3
- answer_status（回答状态）: insufficient_evidence
- answer_confidence（回答置信度）: low
- citations: None
- scores: faithfulness=0.7500, answer_relevancy=0.0000, context_utilization=1.0000, context_recall=0.3333
- answer_preview（回答预览）: 根据当前检索到的证据，无法可靠回答该问题。所提供的证据（E1-E3）比较了劈离式肝移植（SLT）和亲体肝移植（LRT）的结局，但均未涉及儿童患者的相关数据或讨论，因此不足以判断儿童是否仍需要亲体肝移植。

### Q18. Do patterns of knowledge and attitudes exist among unvaccinated seniors?

- question_type（问题类型）: 
- context_count（上下文数量）: 3
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1
- scores: faithfulness=0.6667, answer_relevancy=1.0000, context_utilization=1.0000, context_recall=0.0000
- answer_preview（回答预览）: Yes, patterns of knowledge and attitudes exist among unvaccinated seniors. A study of Medicare beneficiaries aged >65 years who were unvaccinated for influenza 

### Q19. Is there a model to teach and practice retroperitoneoscopic nephrectomy?

- question_type（问题类型）: 
- context_count（上下文数量）: 3
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2
- scores: faithfulness=0.7143, answer_relevancy=0.9191, context_utilization=1.0000, context_recall=1.0000
- answer_preview（回答预览）: Yes, there is a training model for retroperitoneoscopic nephrectomy (RPN) developed using piglets, as described in the provided evidence. The model establishes 

### Q20. Cardiovascular risk in a rural adult West African population: is resting heart rate also relevant?

- question_type（问题类型）: 
- context_count（上下文数量）: 3
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2
- scores: faithfulness=1.0000, answer_relevancy=0.9565, context_utilization=1.0000, context_recall=1.0000
- answer_preview（回答预览）: 是的，静息心率（RHR）在撒哈拉以南非洲农村成年人群中也是一个相关的心血管风险因素。证据表明，升高的RHR在该人群中是一个被忽视的标志物，研究发现19%的研究参与者RHR高于90 bpm，且RHR与年龄、腰围等多种已确立的心血管疾病风险因素显著相关。

## Notes（说明）

- Ragas baseline 评估的是 RAG 生成回答和 final evidence 的关系，不替代 Phase2 的 retrieval trace 诊断。
- `context_recall` 依赖 `reference_answer`，当前数据集的 reference 仍需要持续人工复查。
- 当前 Ragas judge prompt 主要是通用提示；中文因果领域样本需要后续人工抽查来校准可信度。
