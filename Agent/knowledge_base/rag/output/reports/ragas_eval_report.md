# Ragas Baseline Report（Ragas 基线报告）

## Run Info（运行信息）

| field（字段） | value（值） |
| --- | --- |
| status（状态） | pass |
| ragas_version（Ragas 版本） | 0.4.3 |
| judge_model（评测模型） | deepseek-v4-flash |
| judge_profile（评测器配置） | pubmedqa_smoke20_ctx5_1200_evidence1200_compact_rationale_prompt |
| active_profile（启用配置） | pubmedqa_smoke20 |
| dataset_path（数据集路径） | D:\project\CausalAgent-demopaper\Agent\knowledge_base\rag\data\external\pubmedqa\processed\pubmedqa_eval_dataset.json |
| sample_count（样本数） | 20 |
| source_sample_count（源样本数） | 1000 |
| build_seconds（构建耗时秒数） | 0.0000 |
| eval_seconds（评测耗时秒数） | 1765.9570 |
| repeat_count（重复评测次数） | 1 |
| loaded_from_cache（是否读取数据集缓存） | True |
| loaded_score_from_cache（是否读取分数缓存） | False |
| ragas_timeout（Ragas 超时秒数） | 1800 |
| ragas_max_workers（Ragas 最大并发数） | 1 |
| answer_relevancy_strictness（回答相关性严格度） | 1 |
| low_score_threshold（低分阈值） | 0.5 |

## Score Summary（分数汇总）

| metric（指标） | mean（均值） | std（标准差） | valid | nan（空值数） | total（总数） |
| --- | ---: | ---: | ---: | ---: | ---: |
| faithfulness（忠实性） | 0.8944 | 0.0000 | 20 | 0 | 20 |
| answer_relevancy（回答相关性） | 0.7983 | 0.0000 | 20 | 0 | 20 |
| context_utilization（上下文利用率） | 0.8142 | 0.0000 | 20 | 0 | 20 |
| context_recall（上下文召回率） | 0.6417 | 0.0000 | 20 | 0 | 20 |

## Low Score / NaN Cases（低分或空值样本）

| q（题号） | metric（指标） | score | reason（原因） | question（问题） |
| ---: | --- | ---: | --- | --- |
| 3 | answer_relevancy（回答相关性） | 0.0000 | below_threshold | Syncope during bathing in infants, a pediatric form of water-induced urticaria? |
| 4 | context_recall（上下文召回率） | 0.3333 | below_threshold | Are the long-term results of the transanal pull-through equal to those of the transabdominal pull-through? |
| 6 | answer_relevancy（回答相关性） | 0.0000 | below_threshold | Double balloon enteroscopy: is it efficacious and safe in a community setting? |
| 6 | context_recall（上下文召回率） | 0.0000 | below_threshold | Double balloon enteroscopy: is it efficacious and safe in a community setting? |
| 8 | context_recall（上下文召回率） | 0.3333 | below_threshold | Is adjustment for reporting heterogeneity necessary in sleep disorders? |
| 13 | context_recall（上下文召回率） | 0.0000 | below_threshold | Differentiation of nonalcoholic from alcoholic steatohepatitis: are routine laboratory markers useful? |
| 14 | context_recall（上下文召回率） | 0.3333 | below_threshold | Prompting Primary Care Providers about Increased Patient Risk As a Result of Family History: Does It Work? |
| 17 | context_recall（上下文召回率） | 0.3333 | below_threshold | Is there still a need for living-related liver transplantation in children? |

## Cross Metric Bad Cases（跨指标问题样本）

| field（字段） | value（值） |
| --- | --- |
| shared_count（共同样本数） | 20 |
| ragas_only_count | 0 |
| retrieval_only_count（仅检索样本数） | 80 |
| bad_case_count | 7 |
| ragas_low_threshold | 0.5 |
| retrieval_recall_low_threshold | 0.67 |
| retrieval_mrr_low_threshold | 0.5 |

| q（题号） | retrieval_recall（检索召回率） | retrieval_mrr（检索 MRR） | final_gold_rank（最终 gold 排名） | low_ragas | nan_ragas（Ragas 空值指标） | categories（类别） | question（问题） |
| ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| 3 | 1.0000 | 1.0000 | 1 | answer_relevancy | None | retrieval_ok_ragas_bad, loss:final_hit | Syncope during bathing in infants, a pediatric form of water-induced urticaria? |
| 4 | 1.0000 | 1.0000 | 1 | context_recall | None | retrieval_ok_ragas_bad, loss:final_hit | Are the long-term results of the transanal pull-through equal to those of the transabdominal pull-through? |
| 6 | 1.0000 | 0.3333 | 3 | answer_relevancy, context_recall | None | retrieval_and_generation_bad, loss:final_hit | Double balloon enteroscopy: is it efficacious and safe in a community setting? |
| 8 | 1.0000 | 1.0000 | 1 | context_recall | None | retrieval_ok_ragas_bad, loss:final_hit | Is adjustment for reporting heterogeneity necessary in sleep disorders? |
| 13 | 1.0000 | 1.0000 | 1 | context_recall | None | retrieval_ok_ragas_bad, loss:final_hit | Differentiation of nonalcoholic from alcoholic steatohepatitis: are routine laboratory markers useful? |
| 14 | 1.0000 | 1.0000 | 1 | context_recall | None | retrieval_ok_ragas_bad, loss:final_hit | Prompting Primary Care Providers about Increased Patient Risk As a Result of Family History: Does It Work? |
| 17 | 1.0000 | 1.0000 | 1 | context_recall | None | retrieval_ok_ragas_bad, loss:final_hit | Is there still a need for living-related liver transplantation in children? |

## Per Question（逐题详情）

### Q1. Do mitochondria play a role in remodelling lace plant leaves during programmed cell death?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2, E3
- scores: faithfulness=0.9091, answer_relevancy=0.9629, context_utilization=0.5833, context_recall=0.5000
- answer_preview（回答预览）: Yes, mitochondria play a role in developmentally regulated programmed cell death (PCD) in lace plant (Aponogeton madagascariensis) leaves. In vivo studies using

### Q2. Landolt C and snellen e acuity: differences in strabismus amblyopia?

- question_type（问题类型）: 
- context_count（上下文数量）: 4
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2
- scores: faithfulness=1.0000, answer_relevancy=0.9018, context_utilization=1.0000, context_recall=1.0000
- answer_preview（回答预览）: In a study of 100 patients (39 with strabismus amblyopia), visual acuity measured with Landolt C (LR) and Snellen E (SE) showed small but consistent differences

### Q3. Syncope during bathing in infants, a pediatric form of water-induced urticaria?

- question_type（问题类型）: 
- context_count（上下文数量）: 4
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: medium
- citations: E1, E2
- scores: faithfulness=0.6667, answer_relevancy=0.0000, context_utilization=1.0000, context_recall=1.0000
- answer_preview（回答预览）: Based on a case series of eight infants (aged 2–15 months) presenting with pallor, hypotonia, and unresponsiveness upon water immersion—resolving within seconds

### Q4. Are the long-term results of the transanal pull-through equal to those of the transabdominal pull-through?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: medium
- citations: E1, E2, E3
- scores: faithfulness=1.0000, answer_relevancy=0.8982, context_utilization=1.0000, context_recall=0.3333
- answer_preview（回答预览）: The study compared long-term outcomes of transanal endorectal pull-through (TERPT) versus conventional transabdominal (ABD) pull-through in 41 patients with Hir

### Q5. Can tailored interventions increase mammography use among HMO women?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2, E3
- scores: faithfulness=1.0000, answer_relevancy=0.9332, context_utilization=1.0000, context_recall=0.5000
- answer_preview（回答预览）: Evidence from a randomized field trial involving 1,099 women aged 50 and older in a health maintenance organization (HMO) in North Carolina shows that tailored 

### Q6. Double balloon enteroscopy: is it efficacious and safe in a community setting?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: insufficient_evidence
- answer_confidence（回答置信度）: low
- citations: E1, E2, E3
- scores: faithfulness=1.0000, answer_relevancy=0.0000, context_utilization=0.9500, context_recall=0.0000
- answer_preview（回答预览）: The retrieved evidence describes double-balloon enteroscopy (DBE) in clinical populations (44 patients in one study, 66 patients with 88 procedures in another) 

### Q7. 30-Day and 1-year mortality in emergency general surgery laparotomies: an area of concern and need for improvement?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2
- scores: faithfulness=0.9091, answer_relevancy=0.8860, context_utilization=0.5000, context_recall=0.5000
- answer_preview（回答预览）: Emergency general surgery laparotomies are associated with high mortality, with recent studies reporting 30-day mortality of 14-15%. A retrospective study of 47

### Q8. Is adjustment for reporting heterogeneity necessary in sleep disorders?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2, E4
- scores: faithfulness=0.7500, answer_relevancy=0.9815, context_utilization=0.9167, context_recall=0.3333
- answer_preview（回答预览）: Evidence from a Japanese survey (1002 adults) using anchoring vignettes and the CHOPIT model shows that adjusting for reporting heterogeneity changes the factor

### Q9. Do mutations causing low HDL-C promote increased carotid intima-media thickness?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2
- scores: faithfulness=1.0000, answer_relevancy=1.0000, context_utilization=1.0000, context_recall=1.0000
- answer_preview（回答预览）: Evidence from a case-control study of 114 subjects with 10 different mutations in LCAT, ABCA1, and APOA1 shows that despite significantly lower HDL cholesterol 

### Q10. A short stay or 23-hour ward in a general and academic children's hospital: are they effective?

- question_type（问题类型）: 
- context_count（上下文数量）: 4
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2, E3, E4
- scores: faithfulness=1.0000, answer_relevancy=0.7460, context_utilization=0.5833, context_recall=1.0000
- answer_preview（回答预览）: The evidence from a descriptive comparison of prospectively collected data at Westmead Hospital (general) and the New Children's Hospital (academic) demonstrate

### Q11. Did Chile's traffic law reform push police enforcement?

- question_type（问题类型）: 
- context_count（上下文数量）: 4
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2, E3
- scores: faithfulness=0.6667, answer_relevancy=0.7698, context_utilization=1.0000, context_recall=0.5000
- answer_preview（回答预览）: The study examined Chile's 2005 traffic law reform and its association with increased police enforcement. Empirical estimates using instrumental variables found

### Q12. Therapeutic anticoagulation in the trauma patient: is it safe?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: medium
- citations: E1, E2, E3
- scores: faithfulness=0.9091, answer_relevancy=0.8436, context_utilization=0.5000, context_recall=0.5000
- answer_preview（回答预览）: In a retrospective review of 114 trauma patients initiated on therapeutic anticoagulation, complications occurred in 21% of patients, including a sudden drop in

### Q13. Differentiation of nonalcoholic from alcoholic steatohepatitis: are routine laboratory markers useful?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2
- scores: faithfulness=1.0000, answer_relevancy=0.8318, context_utilization=1.0000, context_recall=0.0000
- answer_preview（回答预览）: In a retrospective study of 95 steatohepatitis patients, routine laboratory markers demonstrated utility in differentiating nonalcoholic (NASH) from alcoholic s

### Q14. Prompting Primary Care Providers about Increased Patient Risk As a Result of Family History: Does It Work?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: medium
- citations: E1, E2, E3
- scores: faithfulness=0.8000, answer_relevancy=0.7894, context_utilization=0.5833, context_recall=0.3333
- answer_preview（回答预览）: The automated, tailored prompts about family history risk for six diseases (heart disease, stroke, diabetes, and breast, colorectal, or ovarian cancer) were tes

### Q15. Do emergency ultrasound fellowship programs impact emergency medicine residents' ultrasound education?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2, E3
- scores: faithfulness=1.0000, answer_relevancy=1.0000, context_utilization=0.5833, context_recall=1.0000
- answer_preview（回答预览）: A cross-sectional study at 9 academic medical centers involving 244 emergency medicine residents found that those in programs with emergency ultrasound (EUS) fe

### Q16. Patient-Controlled Therapy of Breathlessness in Palliative Care: A New Therapeutic Concept for Opioid Administration?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: medium
- citations: E1, E2, E3
- scores: faithfulness=0.6000, answer_relevancy=0.8738, context_utilization=0.5833, context_recall=1.0000
- answer_preview（回答预览）: In a pilot observational study of 18 inpatients with advanced disease and refractory breathlessness, intravenous opioid patient-controlled therapy (PCT) was inv

### Q17. Is there still a need for living-related liver transplantation in children?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: medium
- citations: E1, E2
- scores: faithfulness=0.7692, answer_relevancy=0.7742, context_utilization=1.0000, context_recall=0.3333
- answer_preview（回答预览）: Evidence from a comparative study (1996–2000) of split-liver transplantation (SLT) and living-related liver transplantation (LRT) shows that LRT achieved higher

### Q18. Do patterns of knowledge and attitudes exist among unvaccinated seniors?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1
- scores: faithfulness=1.0000, answer_relevancy=0.9859, context_utilization=1.0000, context_recall=1.0000
- answer_preview（回答预览）: Yes, patterns of knowledge and attitudes exist among unvaccinated seniors aged >65 years, as identified in a survey of Medicare beneficiaries across five areas.

### Q19. Is there a model to teach and practice retroperitoneoscopic nephrectomy?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2
- scores: faithfulness=1.0000, answer_relevancy=0.9258, context_utilization=1.0000, context_recall=1.0000
- answer_preview（回答预览）: Yes, a training model for retroperitoneoscopic nephrectomy (RPN) exists based on a study using 15 piglets. The model simulated the entire procedure from creatin

### Q20. Cardiovascular risk in a rural adult West African population: is resting heart rate also relevant?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2, E6
- scores: faithfulness=0.9091, answer_relevancy=0.8627, context_utilization=0.5000, context_recall=1.0000
- answer_preview（回答预览）: In a cross-sectional study of 574 rural adults in Ghana, elevated resting heart rate (RHR >90 bpm) was present in 19% of participants and was significantly asso

## Notes（说明）

- Ragas baseline 评估的是 RAG 生成回答和 final evidence 的关系，不替代 Phase2 的 retrieval trace 诊断。
- `context_recall` 依赖 `reference_answer`，当前数据集的 reference 仍需要持续人工复查。
- 当前 Ragas judge prompt 主要是通用提示；中文因果领域样本需要后续人工抽查来校准可信度。
