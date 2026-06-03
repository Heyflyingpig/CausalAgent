# Ragas Baseline Report（Ragas 基线报告）

## Run Info（运行信息）

| field（字段） | value（值） |
| --- | --- |
| status（状态） | pass |
| ragas_version（Ragas 版本） | 0.4.3 |
| judge_model（评测模型） | deepseek-v4-flash |
| judge_profile（评测器配置） | pubmedqa_smoke20_ctx5_1200 |
| active_profile（启用配置） | pubmedqa_smoke20 |
| dataset_path（数据集路径） | D:\project\CausalAgent-demopaper\Agent\knowledge_base\rag\data\external\pubmedqa\processed\pubmedqa_eval_dataset.json |
| sample_count（样本数） | 20 |
| source_sample_count（源样本数） | 1000 |
| build_seconds（构建耗时秒数） | 195.5820 |
| eval_seconds（评测耗时秒数） | 1604.6110 |
| repeat_count（重复评测次数） | 1 |
| loaded_from_cache（是否读取数据集缓存） | False |
| loaded_score_from_cache（是否读取分数缓存） | False |
| ragas_timeout（Ragas 超时秒数） | 1800 |
| ragas_max_workers（Ragas 最大并发数） | 1 |
| answer_relevancy_strictness（回答相关性严格度） | 1 |
| low_score_threshold（低分阈值） | 0.5 |

## Score Summary（分数汇总）

| metric（指标） | mean（均值） | std（标准差） | valid | nan（空值数） | total（总数） |
| --- | ---: | ---: | ---: | ---: | ---: |
| faithfulness（忠实性） | 0.8015 | 0.0000 | 20 | 0 | 20 |
| answer_relevancy（回答相关性） | 0.7740 | 0.0000 | 20 | 0 | 20 |
| context_utilization（上下文利用率） | 0.8711 | 0.0000 | 20 | 0 | 20 |
| context_recall（上下文召回率） | 0.4792 | 0.0000 | 20 | 0 | 20 |

## Low Score / NaN Cases（低分或空值样本）

| q（题号） | metric（指标） | score | reason（原因） | question（问题） |
| ---: | --- | ---: | --- | --- |
| 1 | context_recall（上下文召回率） | 0.2500 | below_threshold | Do mitochondria play a role in remodelling lace plant leaves during programmed cell death? |
| 2 | faithfulness（忠实性） | 0.4000 | below_threshold | Landolt C and snellen e acuity: differences in strabismus amblyopia? |
| 4 | context_recall（上下文召回率） | 0.0000 | below_threshold | Are the long-term results of the transanal pull-through equal to those of the transabdominal pull-through? |
| 5 | context_recall（上下文召回率） | 0.3333 | below_threshold | Can tailored interventions increase mammography use among HMO women? |
| 6 | answer_relevancy（回答相关性） | 0.0000 | below_threshold | Double balloon enteroscopy: is it efficacious and safe in a community setting? |
| 6 | context_recall（上下文召回率） | 0.0000 | below_threshold | Double balloon enteroscopy: is it efficacious and safe in a community setting? |
| 8 | context_recall（上下文召回率） | 0.3333 | below_threshold | Is adjustment for reporting heterogeneity necessary in sleep disorders? |
| 10 | context_recall（上下文召回率） | 0.0000 | below_threshold | A short stay or 23-hour ward in a general and academic children's hospital: are they effective? |
| 12 | context_recall（上下文召回率） | 0.0000 | below_threshold | Therapeutic anticoagulation in the trauma patient: is it safe? |
| 13 | context_recall（上下文召回率） | 0.0000 | below_threshold | Differentiation of nonalcoholic from alcoholic steatohepatitis: are routine laboratory markers useful? |
| 14 | context_utilization（上下文利用率） | 0.3333 | below_threshold | Prompting Primary Care Providers about Increased Patient Risk As a Result of Family History: Does It Work? |
| 14 | context_recall（上下文召回率） | 0.3333 | below_threshold | Prompting Primary Care Providers about Increased Patient Risk As a Result of Family History: Does It Work? |
| 16 | context_recall（上下文召回率） | 0.0000 | below_threshold | Patient-Controlled Therapy of Breathlessness in Palliative Care: A New Therapeutic Concept for Opioid Administration? |
| 17 | faithfulness（忠实性） | 0.0000 | below_threshold | Is there still a need for living-related liver transplantation in children? |
| 17 | answer_relevancy（回答相关性） | 0.0000 | below_threshold | Is there still a need for living-related liver transplantation in children? |
| 17 | context_recall（上下文召回率） | 0.3333 | below_threshold | Is there still a need for living-related liver transplantation in children? |

## Cross Metric Bad Cases（跨指标问题样本）

| field（字段） | value（值） |
| --- | --- |
| shared_count（共同样本数） | 20 |
| ragas_only_count | 0 |
| retrieval_only_count（仅检索样本数） | 80 |
| bad_case_count | 12 |
| ragas_low_threshold | 0.5 |
| retrieval_recall_low_threshold | 0.67 |
| retrieval_mrr_low_threshold | 0.5 |

| q（题号） | retrieval_recall（检索召回率） | retrieval_mrr（检索 MRR） | final_gold_rank（最终 gold 排名） | low_ragas | nan_ragas（Ragas 空值指标） | categories（类别） | question（问题） |
| ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| 1 | 1.0000 | 1.0000 | 1 | context_recall | None | retrieval_ok_ragas_bad, loss:final_hit | Do mitochondria play a role in remodelling lace plant leaves during programmed cell death? |
| 2 | 1.0000 | 1.0000 | 1 | faithfulness | None | retrieval_ok_ragas_bad, loss:final_hit | Landolt C and snellen e acuity: differences in strabismus amblyopia? |
| 4 | 1.0000 | 1.0000 | 1 | context_recall | None | retrieval_ok_ragas_bad, loss:final_hit | Are the long-term results of the transanal pull-through equal to those of the transabdominal pull-through? |
| 5 | 1.0000 | 1.0000 | 1 | context_recall | None | retrieval_ok_ragas_bad, loss:final_hit | Can tailored interventions increase mammography use among HMO women? |
| 6 | 1.0000 | 0.3333 | 3 | answer_relevancy, context_recall | None | retrieval_and_generation_bad, loss:final_hit | Double balloon enteroscopy: is it efficacious and safe in a community setting? |
| 8 | 1.0000 | 1.0000 | 1 | context_recall | None | retrieval_ok_ragas_bad, loss:final_hit | Is adjustment for reporting heterogeneity necessary in sleep disorders? |
| 10 | 1.0000 | 1.0000 | 1 | context_recall | None | retrieval_ok_ragas_bad, loss:final_hit | A short stay or 23-hour ward in a general and academic children's hospital: are they effective? |
| 12 | 1.0000 | 1.0000 | 1 | context_recall | None | retrieval_ok_ragas_bad, loss:final_hit | Therapeutic anticoagulation in the trauma patient: is it safe? |
| 13 | 1.0000 | 1.0000 | 1 | context_recall | None | retrieval_ok_ragas_bad, loss:final_hit | Differentiation of nonalcoholic from alcoholic steatohepatitis: are routine laboratory markers useful? |
| 14 | 1.0000 | 1.0000 | 1 | context_utilization, context_recall | None | retrieval_ok_ragas_bad, loss:final_hit | Prompting Primary Care Providers about Increased Patient Risk As a Result of Family History: Does It Work? |
| 16 | 1.0000 | 1.0000 | 1 | context_recall | None | retrieval_ok_ragas_bad, loss:final_hit | Patient-Controlled Therapy of Breathlessness in Palliative Care: A New Therapeutic Concept for Opioid Administration? |
| 17 | 1.0000 | 1.0000 | 1 | faithfulness, answer_relevancy, context_recall | None | retrieval_ok_ragas_bad, loss:final_hit | Is there still a need for living-related liver transplantation in children? |

## Per Question（逐题详情）

### Q1. Do mitochondria play a role in remodelling lace plant leaves during programmed cell death?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2, E3
- scores: faithfulness=0.7500, answer_relevancy=0.9474, context_utilization=0.5833, context_recall=0.2500
- answer_preview（回答预览）: 是的，根据检索到的证据，线粒体在蕾丝植物（Aponogeton madagascariensis）叶片程序性细胞死亡（PCD）过程中发挥作用。证据表明，线粒体动力学参与发育调控的PCD，并且通过线粒体膜电位（ΔΨm）和线粒体通透性转换孔（PTP）的形成等机制相关。

### Q2. Landolt C and snellen e acuity: differences in strabismus amblyopia?

- question_type（问题类型）: 
- context_count（上下文数量）: 4
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2
- scores: faithfulness=0.4000, answer_relevancy=0.7217, context_utilization=1.0000, context_recall=1.0000
- answer_preview（回答预览）: 在斜视性弱视眼中，Landolt C视力与Snellen E视力之间的差异很小。平均小数视力值分别为0.14（Landolt C）和0.16（Snellen E），Snellen E值略高，平均差异约为0.55行（Snellen E更高）。

### Q3. Syncope during bathing in infants, a pediatric form of water-induced urticaria?

- question_type（问题类型）: 
- context_count（上下文数量）: 4
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: medium
- citations: E1, E2
- scores: faithfulness=0.8333, answer_relevancy=0.6944, context_utilization=1.0000, context_recall=1.0000
- answer_preview（回答预览）: 证据表明，婴儿在洗澡时出现的晕厥（苍白、张力减退、静止、无反应）被认为可能是水源性荨麻疹的一种儿童等效表现。研究观察到两名婴儿在试验性洗澡后血组胺水平升高，且症状在几周不洗澡后改善，部分患儿后续仍对水或阳光敏感。因此，上述表现可以被视为儿童型水源性荨麻疹的一种可能形式。

### Q4. Are the long-term results of the transanal pull-through equal to those of the transabdominal pull-through?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: medium
- citations: E1, E2, E3
- scores: faithfulness=1.0000, answer_relevancy=0.7317, context_utilization=0.5833, context_recall=0.0000
- answer_preview（回答预览）: 根据现有证据，经肛门拖出术（TERPT）与经腹拖出术（ABD）的长期总体评分相似，但在控便评分方面ABD组显著更优，排便模式评分方面TERPT组更优。因此，两者的长期结果并不完全相等。

### Q5. Can tailored interventions increase mammography use among HMO women?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2, E3
- scores: faithfulness=0.6667, answer_relevancy=0.8931, context_utilization=1.0000, context_recall=0.3333
- answer_preview（回答预览）: 是的，定制化干预（尤其是电话咨询）可以显著提高HMO女性进行乳腺X线摄影检查的比例。一项研究发现，与常规护理相比，电话咨询使按时筛查的比例从61%提高到71%，而定制化印刷材料则提高到67%。

### Q6. Double balloon enteroscopy: is it efficacious and safe in a community setting?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: insufficient_evidence
- answer_confidence（回答置信度）: low
- citations: E1, E2, E3, E5
- scores: faithfulness=0.6667, answer_relevancy=0.0000, context_utilization=0.9500, context_recall=0.0000
- answer_preview（回答预览）: 根据当前检索到的证据，无法可靠回答该问题。证据中描述的双气囊小肠镜（DBE）研究均来自医院或医疗中心环境，并未提供在社区环境中有效性和安全性的数据。

### Q7. 30-Day and 1-year mortality in emergency general surgery laparotomies: an area of concern and need for improvement?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2
- scores: faithfulness=0.6667, answer_relevancy=0.7437, context_utilization=1.0000, context_recall=0.5000
- answer_preview（回答预览）: 依据检索到的证据，急诊普外开腹手术的30天和1年死亡率较高，且存在显著年龄差异。E1指出近期研究显示30天死亡率为14-15%，并希望这些数据能促进数据收集和改进护理。E2提供了具体数据：在477例开腹手术中，总体30天死亡率为12.4%（<70岁）和22%（≥70岁），1年死亡率为25%（<70岁）和38%（≥70岁

### Q8. Is adjustment for reporting heterogeneity necessary in sleep disorders?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2, E4
- scores: faithfulness=0.6667, answer_relevancy=1.0000, context_utilization=0.9167, context_recall=0.3333
- answer_preview（回答预览）: Yes, adjustment for reporting heterogeneity is necessary in sleep disorders, as evidence shows that using anchoring vignettes and the CHOPIT model can correct f

### Q9. Do mutations causing low HDL-C promote increased carotid intima-media thickness?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2
- scores: faithfulness=1.0000, answer_relevancy=1.0000, context_utilization=1.0000, context_recall=1.0000
- answer_preview（回答预览）: No, mutations causing low HDL-C do not promote increased carotid intima-media thickness (cIMT). Evidence from a case-control study showed that cIMT was nearly i

### Q10. A short stay or 23-hour ward in a general and academic children's hospital: are they effective?

- question_type（问题类型）: 
- context_count（上下文数量）: 4
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2, E3, E4
- scores: faithfulness=0.8571, answer_relevancy=0.8797, context_utilization=0.6389, context_recall=0.0000
- answer_preview（回答预览）: 根据检索到的证据，短住病房（short stay ward）在综合性教学医院和学术儿童医院中是有效的。证据显示，短住病房增加了医院效率（increased hospital efficiency），入院超过23小时的比例仅为1%，转至住院病房的比例很低（4%-6%），出院后72小时内非计划复诊率低于1%，且未报告不良事

### Q11. Did Chile's traffic law reform push police enforcement?

- question_type（问题类型）: 
- context_count（上下文数量）: 4
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2, E3
- scores: faithfulness=0.6667, answer_relevancy=0.8117, context_utilization=0.8333, context_recall=0.5000
- answer_preview（回答预览）: 是的，智利的交通法改革推动了警察执法。证据显示，2005年交通法改革后，警察交通执法（以人均罚单数量衡量）显著增加，并与交通事故死亡和重伤的下降相关。

### Q12. Therapeutic anticoagulation in the trauma patient: is it safe?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2, E3
- scores: faithfulness=1.0000, answer_relevancy=0.9656, context_utilization=1.0000, context_recall=0.0000
- answer_preview（回答预览）: 根据检索到的证据，创伤患者的治疗性抗凝并非完全安全，存在显著并发症风险。一项研究显示，在114名开始治疗性抗凝的创伤患者中，21%（24例）出现至少一次并发症，最常见的是血红蛋白突然下降需输血（11例），另有5例死亡（4%），其中3例死于显著出血。因此，需要谨慎评估风险与获益。

### Q13. Differentiation of nonalcoholic from alcoholic steatohepatitis: are routine laboratory markers useful?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2
- scores: faithfulness=1.0000, answer_relevancy=0.7915, context_utilization=1.0000, context_recall=0.0000
- answer_preview（回答预览）: 根据检索到的证据，常规实验室指标（如MCV、AST/ALT比值）在区分非酒精性脂肪性肝炎（NASH）和酒精性脂肪性肝炎（ASH）方面具有一定作用。具体而言，ASH患者中MCV升高（53% vs. NASH中0%），AST/ALT比值>1更常见（54.1% vs. 20.7%），且多变量分析显示MCV、AST/ALT比值

### Q14. Prompting Primary Care Providers about Increased Patient Risk As a Result of Family History: Does It Work?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2, E3
- scores: faithfulness=1.0000, answer_relevancy=0.8668, context_utilization=0.3333, context_recall=0.3333
- answer_preview（回答预览）: 根据研究，自动化的定制提示导致初级保健医生在大多数就诊中查阅或讨论了家族史（查阅占53.5%，讨论占22.9%），但仅有0.7%的就诊中医生查阅家族史并安排了检查/转诊，且未观察到显著的行为改变。因此，该方法对改变医生行为的效果有限。

### Q15. Do emergency ultrasound fellowship programs impact emergency medicine residents' ultrasound education?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: medium
- citations: E1, E2, E3
- scores: faithfulness=1.0000, answer_relevancy=0.9683, context_utilization=0.5833, context_recall=1.0000
- answer_preview（回答预览）: Yes, emergency ultrasound (EUS) fellowship programs impact emergency medicine (EM) residents' ultrasound education. According to the evidence, residents in prog

### Q16. Patient-Controlled Therapy of Breathlessness in Palliative Care: A New Therapeutic Concept for Opioid Administration?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2, E3
- scores: faithfulness=0.8571, answer_relevancy=0.8767, context_utilization=1.0000, context_recall=0.0000
- answer_preview（回答预览）: 根据检索到的证据，患者控制的阿片类药物疗法（PCT）被研究用于姑息治疗中晚期疾病患者的难治性呼吸困难，作为一种新的治疗概念。证据E1提出了PCT系统是否为额外治疗选择的问题，E2和E3报告了一项包含18名住院患者的观察性研究，显示了通过PCT给予阿片类药物后呼吸困难评分的下降。因此，该问题所提及的概念已被初步探索。

### Q17. Is there still a need for living-related liver transplantation in children?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: insufficient_evidence
- answer_confidence（回答置信度）: low
- citations: None
- scores: faithfulness=0.0000, answer_relevancy=0.0000, context_utilization=1.0000, context_recall=0.3333
- answer_preview（回答预览）: 根据当前检索到的证据，无法可靠回答该问题。

### Q18. Do patterns of knowledge and attitudes exist among unvaccinated seniors?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1
- scores: faithfulness=1.0000, answer_relevancy=0.8596, context_utilization=1.0000, context_recall=1.0000
- answer_preview（回答预览）: 是的，根据检索到的证据，未接种疫苗的老年人中存在知识和态度的模式。一项研究对65岁以上未接种流感疫苗的老年人进行调查，通过聚类分析识别出4个不同的群体：潜在接种者（45%，他们表示会为预防疾病而接种流感疫苗）、恐惧无知者（9%，不确定流感疫苗是否会导致疾病）、怀疑者（27%）等。

### Q19. Is there a model to teach and practice retroperitoneoscopic nephrectomy?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2
- scores: faithfulness=1.0000, answer_relevancy=0.9448, context_utilization=1.0000, context_recall=1.0000
- answer_preview（回答预览）: Yes, there is a training model for retroperitoneoscopic nephrectomy described in the evidence, which involves using piglets to establish a standard retroperiton

### Q20. Cardiovascular risk in a rural adult West African population: is resting heart rate also relevant?

- question_type（问题类型）: 
- context_count（上下文数量）: 5
- answer_status（回答状态）: answered
- answer_confidence（回答置信度）: high
- citations: E1, E2, E3
- scores: faithfulness=1.0000, answer_relevancy=0.7829, context_utilization=1.0000, context_recall=1.0000
- answer_preview（回答预览）: 是的，静息心率（RHR）在撒哈拉以南非洲农村人群中与心血管风险相关。研究证据表明，在加纳农村成年人群中，升高的静息心率（>90 bpm）患病率为19%，且RHR与年龄、腰围等多个已确立的心血管疾病风险因素显著相关，RHR的回归稀释比为0.75（95% CI 0.62-0.89），说明其在心血管风险评估中不可忽视。

## Notes（说明）

- Ragas baseline 评估的是 RAG 生成回答和 final evidence 的关系，不替代 Phase2 的 retrieval trace 诊断。
- `context_recall` 依赖 `reference_answer`，当前数据集的 reference 仍需要持续人工复查。
- 当前 Ragas judge prompt 主要是通用提示；中文因果领域样本需要后续人工抽查来校准可信度。
