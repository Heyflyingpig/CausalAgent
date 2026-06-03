# RAG Trace Report（RAG 链路追踪报告）

## Summary（汇总）

| field（字段） | value（值） |
| --- | ---: |
| trace_count（链路记录数） | 20 |
| bad_case_trace_count（问题样本链路数） | 15 |
| retrieval_eval_trace_count（检索评测链路数） | 20 |
| ragas_eval_trace_count（Ragas 评测链路数） | 20 |
| claim_eval_trace_count（断言评测链路数） | 20 |

## Bad Case Traces（问题样本链路）

| trace_id（链路 ID） | q（题号） | sources（来源） | claim_coverage（断言覆盖率） | evidence_support_rate（证据支撑率） | faithfulness（忠实性） | context_recall（上下文召回率） | question（问题） |
| --- | ---: | --- | ---: | ---: | ---: | ---: | --- |
| q001_b69a5165 | 1 | claim_eval_bad_case, ragas_cross_metric, ragas_low_score | 0.0000 | 1.0000 | 0.7500 | 0.2500 | Do mitochondria play a role in remodelling lace plant leaves during programmed cell death? |
| q002_3e768d72 | 2 | ragas_cross_metric, ragas_low_score | 1.0000 | 1.0000 | 0.4000 | 1.0000 | Landolt C and snellen e acuity: differences in strabismus amblyopia? |
| q004_0330666f | 4 | claim_eval_bad_case, ragas_cross_metric, ragas_low_score | 0.0000 | 0.0000 | 1.0000 | 0.0000 | Are the long-term results of the transanal pull-through equal to those of the transabdominal pull-through? |
| q005_abc0b17f | 5 | claim_eval_bad_case, ragas_cross_metric, ragas_low_score | 0.0000 | 0.0000 | 0.6667 | 0.3333 | Can tailored interventions increase mammography use among HMO women? |
| q006_3fb655ba | 6 | claim_eval_bad_case, ragas_cross_metric, ragas_low_score | 0.0000 | 0.0000 | 0.6667 | 0.0000 | Double balloon enteroscopy: is it efficacious and safe in a community setting? |
| q007_e8d393aa | 7 | claim_eval_bad_case | 0.0000 | 0.0000 | 0.6667 | 0.5000 | 30-Day and 1-year mortality in emergency general surgery laparotomies: an area of concern and need for improvement? |
| q008_c0ade07f | 8 | claim_eval_bad_case, ragas_cross_metric, ragas_low_score | 0.0000 | 0.0000 | 0.6667 | 0.3333 | Is adjustment for reporting heterogeneity necessary in sleep disorders? |
| q010_438d4f68 | 10 | claim_eval_bad_case, ragas_cross_metric, ragas_low_score | 0.0000 | 0.0000 | 0.8571 | 0.0000 | A short stay or 23-hour ward in a general and academic children's hospital: are they effective? |
| q011_f2b3fb95 | 11 | claim_eval_bad_case | 0.0000 | 0.0000 | 0.6667 | 0.5000 | Did Chile's traffic law reform push police enforcement? |
| q012_2166347d | 12 | claim_eval_bad_case, ragas_cross_metric, ragas_low_score | 0.0000 | 0.0000 | 1.0000 | 0.0000 | Therapeutic anticoagulation in the trauma patient: is it safe? |
| q013_1f2e6d52 | 13 | claim_eval_bad_case, ragas_cross_metric, ragas_low_score | 0.0000 | 0.0000 | 1.0000 | 0.0000 | Differentiation of nonalcoholic from alcoholic steatohepatitis: are routine laboratory markers useful? |
| q014_bc2d7cca | 14 | claim_eval_bad_case, ragas_cross_metric, ragas_low_score | 0.0000 | 0.0000 | 1.0000 | 0.3333 | Prompting Primary Care Providers about Increased Patient Risk As a Result of Family History: Does It Work? |
| q016_c010e670 | 16 | claim_eval_bad_case, ragas_cross_metric, ragas_low_score | 0.0000 | 0.0000 | 0.8571 | 0.0000 | Patient-Controlled Therapy of Breathlessness in Palliative Care: A New Therapeutic Concept for Opioid Administration? |
| q017_a9904110 | 17 | claim_eval_bad_case, ragas_cross_metric, ragas_low_score | 0.0000 | 0.0000 | 0.0000 | 0.3333 | Is there still a need for living-related liver transplantation in children? |
| q020_f29c9053 | 20 | claim_eval_bad_case | 0.0000 | 0.0000 | 1.0000 | 1.0000 | Cardiovascular risk in a rural adult West African population: is resting heart rate also relevant? |

## All Traces（全部链路记录）

| trace_id（链路 ID） | q（题号） | retrieval_eval（检索评测） | claim_coverage（断言覆盖率） | evidence_support_rate（证据支撑率） | question（问题） |
| --- | ---: | --- | ---: | ---: | --- |
| q001_b69a5165 | 1 | True | 0.0000 | 1.0000 | Do mitochondria play a role in remodelling lace plant leaves during programmed cell death? |
| q002_3e768d72 | 2 | True | 1.0000 | 1.0000 | Landolt C and snellen e acuity: differences in strabismus amblyopia? |
| q003_8c5d831f | 3 | True | 1.0000 | 1.0000 | Syncope during bathing in infants, a pediatric form of water-induced urticaria? |
| q004_0330666f | 4 | True | 0.0000 | 0.0000 | Are the long-term results of the transanal pull-through equal to those of the transabdominal pull-through? |
| q005_abc0b17f | 5 | True | 0.0000 | 0.0000 | Can tailored interventions increase mammography use among HMO women? |
| q006_3fb655ba | 6 | True | 0.0000 | 0.0000 | Double balloon enteroscopy: is it efficacious and safe in a community setting? |
| q007_e8d393aa | 7 | True | 0.0000 | 0.0000 | 30-Day and 1-year mortality in emergency general surgery laparotomies: an area of concern and need for improvement? |
| q008_c0ade07f | 8 | True | 0.0000 | 0.0000 | Is adjustment for reporting heterogeneity necessary in sleep disorders? |
| q009_47bd7925 | 9 | True | 1.0000 | 1.0000 | Do mutations causing low HDL-C promote increased carotid intima-media thickness? |
| q010_438d4f68 | 10 | True | 0.0000 | 0.0000 | A short stay or 23-hour ward in a general and academic children's hospital: are they effective? |
| q011_f2b3fb95 | 11 | True | 0.0000 | 0.0000 | Did Chile's traffic law reform push police enforcement? |
| q012_2166347d | 12 | True | 0.0000 | 0.0000 | Therapeutic anticoagulation in the trauma patient: is it safe? |
| q013_1f2e6d52 | 13 | True | 0.0000 | 0.0000 | Differentiation of nonalcoholic from alcoholic steatohepatitis: are routine laboratory markers useful? |
| q014_bc2d7cca | 14 | True | 0.0000 | 0.0000 | Prompting Primary Care Providers about Increased Patient Risk As a Result of Family History: Does It Work? |
| q015_53aa0e2a | 15 | True | 1.0000 | 1.0000 | Do emergency ultrasound fellowship programs impact emergency medicine residents' ultrasound education? |
| q016_c010e670 | 16 | True | 0.0000 | 0.0000 | Patient-Controlled Therapy of Breathlessness in Palliative Care: A New Therapeutic Concept for Opioid Administration? |
| q017_a9904110 | 17 | True | 0.0000 | 0.0000 | Is there still a need for living-related liver transplantation in children? |
| q018_27200b94 | 18 | True | 1.0000 | 1.0000 | Do patterns of knowledge and attitudes exist among unvaccinated seniors? |
| q019_b0dbdbbe | 19 | True | 1.0000 | 1.0000 | Is there a model to teach and practice retroperitoneoscopic nephrectomy? |
| q020_f29c9053 | 20 | True | 0.0000 | 0.0000 | Cardiovascular risk in a rural adult West African population: is resting heart rate also relevant? |
