# 正式 Dataset 两题三档试跑

- experiment_id: `7789a71fa21c49daac2729549f6b47bb`
- repeat_no: `0`（每题每档只跑 1 次）

## 真实运行结果

| Item | Variant | Status | Outcome | Tokens | Seconds | Report chars |
|---|---|---|---|---:|---:|---:|
| fv1_fact_02 | MEDIUM | COMPLETED | success | 84625 | 1847 | 8692 |
| fv1_fact_02 | HIGH | COMPLETED | success | 118057 | 1756 | 11128 |
| fv1_fact_02 | ULTRA | COMPLETED | degraded | 215650 | 2099 | 22799 |
| fv1_ec_01 | MEDIUM | COMPLETED | success | 69781 | 1859 | 8453 |
| fv1_ec_01 | HIGH | COMPLETED | success | 186026 | 2015 | 13437 |
| fv1_ec_01 | ULTRA | CANCELLED | - | 0 | 90 | 0 |

## 各 Case Eval 指标

### fv1_fact_02 / MEDIUM

| Group | Metric | Value | Passed | Reason |
|---|---|---:|---:|---|
| analysis | analysis_depth | 1.0000 | 1 | 报告深入解析了四个核心功能及其闭环逻辑，并详细阐述了Generative AI Profile的12类风险和各功能扩展，分析透彻且具有企业落地指导意义。 |
| analysis | instruction_following | 1.0000 | 1 | 完全遵循研究要求，准确解释了四个功能及Profile的补充角色，并提供了清晰的企业落地映射关系表。 |
| analysis | multi_source_synthesis | 0.9000 | 1 | 综合了NIST AI RMF 1.0和Generative AI Profile两份官方文件，并引用了行政令与行业监管背景，但主要依赖单一权威来源，缺乏多源交叉验证。 |
| analysis | uncertainty_calibration | 0.5000 | 0 | 在关键发现部分提及了度量方法成熟度等不确定性，但整体结论缺乏明确的置信度标注或假设说明。 |
| cost | cost_per_pass | 0.0000 | None | cost=0.0 gate_passed=0 |
| cost | total_cost | 0.0000 | None | tokens=84625 |
| factuality | citation_completeness | 0.9000 | 1 | 报告摘录中几乎每个关键声明都附有[1][2][3]等引用标记，覆盖核心功能和风险分类，完整性高。 |
| factuality | citation_correctness | 0.7000 | 1 | 引用标记位置合理，但提供的claim_citations中urls字段为空，无法验证引用是否实际支持对应声明，因此评分有所保留。 |
| factuality | citation_parse_rate | 0.0000 | 0 | md_urls=0 numeric_markers=4 |
| factuality | citation_traceability | 0.0000 | 0 | cited=0/20 |
| factuality | claim_factuality | 0.8000 | 1 | 声明基于NIST AI RMF框架，描述合理且逻辑清晰，但部分引文内容未直接展示，需依赖用户对外部文档的信任。 |
| factuality | effective_citation_count | 2.0000 | None | md_urls=0 numeric=4 |
| factuality | supported_claim_count | 0.0000 | 0 | supported=0/20 |
| factuality | unsupported_critical_claim_count | 0.0000 | 1 | critical claims without citation_url |
| gate | hard_gate_passed | 0.0000 | 0 | gate_passed=0, failure_codes=['dangling_citation'] |
| gate | report_non_empty | 1 | 1 |  |
| gate | workflow_completed | 1 | 1 | outcome=success |
| mechanism | best_draft_quality | - | None | 非 HIGH 双 draft 路径（draft_count=0），跳过 |
| mechanism | citation_retention_after_revision | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | claim_retention_after_revision | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | draft_complementarity | - | None | 非 HIGH 双 draft 路径（draft_count=0），跳过 |
| mechanism | merge_information_loss | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | reviewer_consensus_predictiveness | 0.0000 | None | consensus=None outcome=success |
| mechanism | reviewer_token_cost | 0.0000 | None | lenses=0 |
| mechanism | synthesis_uplift | - | None | 非 HIGH 双 draft 路径（draft_count=0），跳过 |
| meta | critical_claim_count | 0.0000 | None | total_claims=20 |
| recall | critical_fact_recall | 1.0000 | 1 | 报告准确复述了AI RMF包含Govern、Map、Measure、Manage四个功能，并明确指出Generative AI Profile是跨行业配套资源，不取代AI RMF 1.0。 |
| recall | required_point_coverage | 1.0000 | 1 | 报告完整覆盖了四个核心功能的解释、GenAI Profile与RMF的关系说明以及企业控制活动映射，每个必考点均得到充分阐述。 |
| source | source_freshness | 0.9667 | 1 | source_freshness≈0.9667（近似：valid_ratio=1.00, domain_diversity=0.89）。MVP source_snapshot 未落 published_at/fetched_at，此为有效度近似，非真时效。 |
| source | source_quality | 1.0000 | 1 | 来源包含NIST官方文档及多个权威研究机构，来源多样且与报告声明高度匹配。 |

### fv1_fact_02 / HIGH

| Group | Metric | Value | Passed | Reason |
|---|---|---:|---:|---|
| analysis | analysis_depth | 1.0000 | 1 | 深度剖析了核心功能、补充关系及企业落地映射。 |
| analysis | instruction_following | 1.0000 | 1 | 完全按照指令输出JSON，且报告内容紧密围绕brief问题。 |
| analysis | multi_source_synthesis | 1.0000 | 1 | 有效综合两份官方文件及额外参考文献，形成系统对比。 |
| analysis | uncertainty_calibration | 0.0000 | 0 | 未对引用数据或结论标注不确定性或置信区间。 |
| cost | cost_per_pass | 0.0000 | None | cost=0.0 gate_passed=0 |
| cost | total_cost | 0.0000 | None | tokens=118057 |
| factuality | citation_completeness | 0.7000 | 1 | 多数声明有引用，但引用[2]在参考列表中缺失，导致部分数据来源未完整列出。 |
| factuality | citation_correctness | 0.8000 | 1 | 现有引用基本支持对应声明，但无法验证缺失引用[2]的真实性，存在轻微不确定性。 |
| factuality | citation_parse_rate | 0.0000 | 0 | md_urls=0 numeric_markers=6 |
| factuality | citation_traceability | 0.0000 | 0 | cited=0/25 |
| factuality | claim_factuality | 1.0000 | 1 | 关键声明如发布日期、框架关系、功能定义等与NIST官方文档一致，无虚假信息。 |
| factuality | effective_citation_count | 3.0000 | None | md_urls=0 numeric=6 |
| factuality | supported_claim_count | 0.0000 | 0 | supported=0/25 |
| factuality | unsupported_critical_claim_count | 3.0000 | 0 | critical claims without citation_url |
| gate | hard_gate_passed | 0.0000 | 0 | gate_passed=0, failure_codes=['dangling_citation', 'unsupported_critical_claim'] |
| gate | report_non_empty | 1 | 1 |  |
| gate | workflow_completed | 1 | 1 | outcome=success |
| mechanism | best_draft_quality | 84.0000 | 1 | best draft=comparative quality_proxy=84.0（claim+citation 密度代理，非 judge 分） |
| mechanism | citation_retention_after_revision | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | claim_retention_after_revision | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | draft_complementarity | 0.9847 | 1 | 两 draft 互补度=0.9847（only-in-one / union，越高越值得融合） |
| mechanism | merge_information_loss | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | reviewer_consensus_predictiveness | 0.0000 | None | consensus=None outcome=success |
| mechanism | reviewer_token_cost | 0.0000 | None | lenses=0 |
| mechanism | synthesis_uplift | 21.0000 | 1 | uplift=21.0（synth_q=105.0 - best_draft_q=84.0）。MVP draft judge 分未落库，用密度代理；正值表示 synthesis 比最优 draft 更密。 |
| meta | critical_claim_count | 3.0000 | None | total_claims=25 |
| recall | critical_fact_recall | 1.0000 | 1 | 报告准确复述了两个关键事实：第3节明确指出AI RMF Core包含四个功能；第1节和第2节明确说明Generative AI Profile是配套资源且不取代原框架。 |
| recall | required_point_coverage | 1.0000 | 1 | 报告完整覆盖了三个关键点：第3节详细解释了Govern、Map、Measure、Manage的定义与关系；第2节明确Profile是配套资源非替代；第5节提供了每个功能对应的企业控制活动映射。 |
| source | source_freshness | 0.9250 | 1 | source_freshness≈0.925（近似：valid_ratio=1.00, domain_diversity=0.75）。MVP source_snapshot 未落 published_at/fetched_at，此为有效度近似，非真时效。 |
| source | source_quality | 0.9500 | 1 | 来源包含多个NIST官方文档（AI 100-1, AI 600-1），权威性高；域名多样，覆盖官方、商业、社区等；来源与报告核心声明高度匹配。 |

### fv1_fact_02 / ULTRA

| Group | Metric | Value | Passed | Reason |
|---|---|---:|---:|---|
| analysis | analysis_depth | 1.0000 | 1 | 详细解读NIST AI RMF核心功能及生成式AI风险，有具体示例和引用。 |
| analysis | instruction_following | 1.0000 | 1 | 报告按研究要求解释核心功能和风险，结构完整，格式规范。 |
| analysis | multi_source_synthesis | 1.0000 | 1 | 综合引用多个权威来源，包括NIST官方文档、第三方解读，并标注来源。 |
| analysis | uncertainty_calibration | 0.5000 | 0 | 未对信息来源或结论的不确定性进行标注，但内容明确、基于权威。 |
| cost | cost_per_pass | 0.0000 | None | cost=0.0 gate_passed=0 |
| cost | total_cost | 0.0000 | None | tokens=215650 |
| factuality | citation_completeness | 0.8000 | 1 | 大部分关键声明有引用，但部分细节（如具体控制措施编号）引用略模糊，可更完整。 |
| factuality | citation_correctness | 0.9000 | 1 | 引用的官方来源和第三方分析均合理支持对应声明，未发现明显错引。 |
| factuality | citation_parse_rate | 1.0000 | 1 | md_urls=11 numeric_markers=0 |
| factuality | citation_traceability | 1.0000 | 1 | cited=46/46 |
| factuality | claim_factuality | 0.9500 | 1 | 关键声明与NIST官方文件内容一致，无事实性错误。 |
| factuality | effective_citation_count | 11.0000 | None | md_urls=11 numeric=0 |
| factuality | supported_claim_count | 46.0000 | 1 | supported=46/46 |
| factuality | unsupported_critical_claim_count | 0.0000 | 1 | critical claims without citation_url |
| gate | hard_gate_passed | 1.0000 | 1 | gate_passed=1, failure_codes=[] |
| gate | report_non_empty | 1 | 1 |  |
| gate | workflow_completed | 1 | 1 | outcome=degraded |
| mechanism | best_draft_quality | - | None | 非 HIGH 双 draft 路径（draft_count=0），跳过 |
| mechanism | citation_retention_after_revision | 1.0000 | 1 | revision 相对 draft 平均 citation 保留率=1.0 |
| mechanism | claim_retention_after_revision | 0.6587 | 0 | revision 相对 draft 平均 claim 保留率=0.6587 |
| mechanism | draft_complementarity | - | None | 非 HIGH 双 draft 路径（draft_count=0），跳过 |
| mechanism | merge_information_loss | 0.1875 | 1 | merged 相对 section draft 信息丢失=0.1875（claim_retain=0.62, cite_retain=1.00） |
| mechanism | reviewer_consensus_predictiveness | 0.0000 | None | consensus=split outcome=degraded |
| mechanism | reviewer_token_cost | 6726.0000 | None | lenses=2 |
| mechanism | synthesis_uplift | - | None | 非 HIGH 双 draft 路径（draft_count=0），跳过 |
| meta | critical_claim_count | 46.0000 | None | total_claims=46 |
| recall | critical_fact_recall | 1.0000 | 1 | 两个关键参考事实（核心功能包含四个、Profile不取代）均被准确引用。 |
| recall | required_point_coverage | 1.0000 | 1 | 三个必须点全部覆盖，覆盖率达100%。 |
| source | source_freshness | 0.9471 | 1 | source_freshness≈0.9471（近似：valid_ratio=1.00, domain_diversity=0.82）。MVP source_snapshot 未落 published_at/fetched_at，此为有效度近似，非真时效。 |
| source | source_quality | 1.0000 | 1 | 来源以NIST官方文档为主，辅以多个权威分析网站，权威性高、多样性好，与报告声明高度匹配。 |

### fv1_ec_01 / MEDIUM

| Group | Metric | Value | Passed | Reason |
|---|---|---:|---:|---|
| analysis | analysis_depth | 1.0000 | 1 | 系统量化各因素影响并给出临界阈值，分析深度充分。 |
| analysis | instruction_following | 1.0000 | 1 | 完整回应所有要求，包括比较、因素分析、适用条件，格式规范。 |
| analysis | multi_source_synthesis | 1.0000 | 1 | 有效对比三类权威研究并整合补充文献，多源综合质量高。 |
| analysis | uncertainty_calibration | 1.0000 | 1 | 明确列出数据缺口和局限性，不确定性标注恰当。 |
| cost | cost_per_pass | 0.0000 | None | cost=0.0 gate_passed=0 |
| cost | total_cost | 0.0000 | None | tokens=69781 |
| factuality | citation_completeness | 0.9000 | 1 | 主要数据点和观点均有明确引用，涵盖所有关键因素，但少数解释性陈述未直接标注来源。 |
| factuality | citation_correctness | 0.9000 | 1 | 引用与研究机构对应，引用内容与声明匹配，支持结论。 |
| factuality | citation_parse_rate | 1.0000 | 1 | md_urls=14 numeric_markers=16 |
| factuality | citation_traceability | 0.0976 | 0 | cited=8/82 |
| factuality | claim_factuality | 0.9000 | 1 | 报告基于权威研究，关键声明与文献一致，逻辑清晰，无明显事实错误。 |
| factuality | effective_citation_count | 22.0000 | None | md_urls=14 numeric=16 |
| factuality | supported_claim_count | 8.0000 | 0 | supported=8/82 |
| factuality | unsupported_critical_claim_count | 51.0000 | 0 | critical claims without citation_url |
| gate | hard_gate_passed | 0.0000 | 0 | gate_passed=0（仅基于确定性指标；judge 未运行: missing_required_points，离线判定可能偏宽，全量判定需注入 chat_fn） |
| gate | report_non_empty | 1 | 1 |  |
| gate | workflow_completed | 1 | 1 | outcome=success |
| mechanism | best_draft_quality | - | None | 非 HIGH 双 draft 路径（draft_count=0），跳过 |
| mechanism | citation_retention_after_revision | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | claim_retention_after_revision | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | draft_complementarity | - | None | 非 HIGH 双 draft 路径（draft_count=0），跳过 |
| mechanism | merge_information_loss | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | reviewer_consensus_predictiveness | 0.0000 | None | consensus=None outcome=success |
| mechanism | reviewer_token_cost | 0.0000 | None | lenses=0 |
| mechanism | synthesis_uplift | - | None | 非 HIGH 双 draft 路径（draft_count=0），跳过 |
| meta | critical_claim_count | 59.0000 | None | total_claims=82 |
| recall | critical_fact_recall | 1.0000 | 1 | 报告准确复述了生命周期结论依赖功能和边界等参数（f1），并指出仅关注制造阶段会高估BEV优势（f2）。 |
| recall | required_point_coverage | - | None |  |
| source | source_freshness | 0.9700 | 1 | source_freshness≈0.97（近似：valid_ratio=1.00, domain_diversity=0.90）。MVP source_snapshot 未落 published_at/fetched_at，此为有效度近似，非真时效。 |
| source | source_quality | 0.9500 | 1 | 来源多为权威学术机构（如ICCT、JRC、MIT）和官方数据库（NIH、JRC Publications），域名多样且与报告内容高度匹配，质量高。 |

### fv1_ec_01 / HIGH

| Group | Metric | Value | Passed | Reason |
|---|---|---:|---:|---|
| analysis | analysis_depth | 1.0000 | 1 | 深入剖析五大因素并给出量化范围与排序，分析深度高。 |
| analysis | instruction_following | 1.0000 | 1 | 完全遵循题目要求：比较三类权威研究、统一功能单位、分析五因素、给出适用条件。 |
| analysis | multi_source_synthesis | 1.0000 | 1 | 综合三类权威来源共9项研究，统一功能单位并对比假设，多源综合质量高。 |
| analysis | uncertainty_calibration | 0.9000 | 1 | 明确给出排放范围及因素影响区间，强调结论条件依赖性，不确定性标注恰当，但未进行统计误差传播分析。 |
| cost | cost_per_pass | 0.0000 | None | cost=0.0 gate_passed=0 |
| cost | total_cost | 0.0000 | None | tokens=186026 |
| factuality | citation_completeness | 1.0000 | 1 | 报告内所有重要数据点均附有引用编号，引用基本齐全。 |
| factuality | citation_correctness | 1.0000 | 1 | 引用编号与声明内容匹配，支持性强。 |
| factuality | citation_parse_rate | 0.0000 | 0 | md_urls=0 numeric_markers=16 |
| factuality | citation_traceability | 0.0000 | 0 | cited=0/112 |
| factuality | claim_factuality | 1.0000 | 1 | 关键声明均基于合理假设和数据，逻辑一致。 |
| factuality | effective_citation_count | 8.0000 | None | md_urls=0 numeric=16 |
| factuality | supported_claim_count | 0.0000 | 0 | supported=0/112 |
| factuality | unsupported_critical_claim_count | 84.0000 | 0 | critical claims without citation_url |
| gate | hard_gate_passed | 0.0000 | 0 | gate_passed=0, failure_codes=['dangling_citation', 'unsupported_critical_claim'] |
| gate | report_non_empty | 1 | 1 |  |
| gate | workflow_completed | 1 | 1 | outcome=success |
| mechanism | best_draft_quality | 82.0000 | 1 | best draft=comparative quality_proxy=82.0（claim+citation 密度代理，非 judge 分） |
| mechanism | citation_retention_after_revision | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | claim_retention_after_revision | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | draft_complementarity | 0.9554 | 1 | 两 draft 互补度=0.9554（only-in-one / union，越高越值得融合） |
| mechanism | merge_information_loss | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | reviewer_consensus_predictiveness | 0.0000 | None | consensus=None outcome=success |
| mechanism | reviewer_token_cost | 0.0000 | None | lenses=0 |
| mechanism | synthesis_uplift | 25.0000 | 1 | uplift=25.0（synth_q=107.0 - best_draft_q=82.0）。MVP draft judge 分未落库，用密度代理；正值表示 synthesis 比最优 draft 更密。 |
| meta | critical_claim_count | 84.0000 | None | total_claims=112 |
| recall | critical_fact_recall | 1.0000 | 1 | 准确复述结论依赖功能单位、系统边界等事实，并体现制造阶段高排放需结合使用阶段评估。 |
| recall | required_point_coverage | 1.0000 | 1 | 100%覆盖 normalization、drivers、conditional 三个必须点。 |
| source | source_freshness | 0.9571 | 1 | source_freshness≈0.9571（近似：valid_ratio=1.00, domain_diversity=0.86）。MVP source_snapshot 未落 published_at/fetched_at，此为有效度近似，非真时效。 |
| source | source_quality | 1.0000 | 1 | 来源均为国际权威机构（ICCT、IEA、IPCC）及学术期刊，多样性高，与报告内容紧密匹配。 |


# Eval 配对差异报告

## 各 Variant 指标均值
| Metric | MEDIUM | HIGH | ULTRA |
|---|---|---|---|
| analysis_depth | 1.0000 | 1.0000 | 1.0000 |
| best_draft_quality | - | 83.0000 | - |
| citation_completeness | 0.9000 | 0.8500 | 0.8000 |
| citation_correctness | 0.8000 | 0.9000 | 0.9000 |
| citation_parse_rate | 0.5000 | 0.0000 | 1.0000 |
| citation_retention_after_revision | - | - | 1.0000 |
| citation_traceability | 0.0488 | 0.0000 | 1.0000 |
| claim_factuality | 0.8500 | 1.0000 | 0.9500 |
| claim_retention_after_revision | - | - | 0.6587 |
| cost_per_pass | 0.0000 | 0.0000 | 0.0000 |
| critical_claim_count | 29.5000 | 43.5000 | 46.0000 |
| critical_fact_recall | 1.0000 | 1.0000 | 1.0000 |
| draft_complementarity | - | 0.9701 | - |
| effective_citation_count | 12.0000 | 5.5000 | 11.0000 |
| hard_gate_passed | 0.0000 | 0.0000 | 1.0000 |
| instruction_following | 1.0000 | 1.0000 | 1.0000 |
| merge_information_loss | - | - | 0.1875 |
| multi_source_synthesis | 0.9500 | 1.0000 | 1.0000 |
| required_point_coverage | 1.0000 | 1.0000 | 1.0000 |
| reviewer_consensus_predictiveness | 0.0000 | 0.0000 | 0.0000 |
| reviewer_token_cost | 0.0000 | 0.0000 | 6726.0000 |
| source_freshness | 0.9684 | 0.9410 | 0.9471 |
| source_quality | 0.9750 | 0.9750 | 1.0000 |
| supported_claim_count | 4.0000 | 0.0000 | 46.0000 |
| synthesis_uplift | - | 23.0000 | - |
| total_cost | 0.0000 | 0.0000 | 0.0000 |
| uncertainty_calibration | 0.7500 | 0.4500 | 0.5000 |
| unsupported_critical_claim_count | 25.5000 | 43.5000 | 0.0000 |

## 相邻档位差值（uplift）
| Metric | MEDIUM→HIGH | HIGH→ULTRA |
|---|---|---|
| analysis_depth | +0.0000 | +0.0000 |
| best_draft_quality | - | - |
| citation_completeness | -0.0500 | +0.1000 |
| citation_correctness | +0.1000 | +0.1000 |
| citation_parse_rate | -0.5000 | +1.0000 |
| citation_retention_after_revision | - | - |
| citation_traceability | -0.0488 | +1.0000 |
| claim_factuality | +0.1500 | -0.0500 |
| claim_retention_after_revision | - | - |
| cost_per_pass | +0.0000 | +0.0000 |
| critical_claim_count | +14.0000 | +43.0000 |
| critical_fact_recall | +0.0000 | +0.0000 |
| draft_complementarity | - | - |
| effective_citation_count | -6.5000 | +8.0000 |
| hard_gate_passed | +0.0000 | +1.0000 |
| instruction_following | +0.0000 | +0.0000 |
| merge_information_loss | - | - |
| multi_source_synthesis | +0.0500 | +0.0000 |
| required_point_coverage | +0.0000 | +0.0000 |
| reviewer_consensus_predictiveness | +0.0000 | +0.0000 |
| reviewer_token_cost | +0.0000 | +6726.0000 |
| source_freshness | -0.0273 | +0.0221 |
| source_quality | +0.0000 | +0.0500 |
| supported_claim_count | -4.0000 | +46.0000 |
| synthesis_uplift | - | - |
| total_cost | +0.0000 | +0.0000 |
| uncertainty_calibration | -0.3000 | +0.5000 |
| unsupported_critical_claim_count | +18.0000 | -3.0000 |

## 决策输出（§19）
- 质量代理 `effective_citation_count`：MEDIUM=12.0000 → ULTRA=11.0000，配对差值 +9.0000
- 哪些 Task Type 在 HIGH/ULTRA 上有正 Uplift？见 `synthesis_uplift` / `quality_delta_per_round`。
- 哪个机制被更轻量 Variant 支配？比较 `marginal_quality_per_1k_tokens`。
- Reviewer 哪个 Lens 有效？见 `reviewer_consensus_predictiveness`。
- ClaimVerifier 是否值得全量跑？见 `unsupported_claim_detection_recall` vs `verification_token_cost`。
