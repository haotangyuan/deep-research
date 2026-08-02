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
| fv1_ec_01 | ULTRA | CANCELLED | hitl_wait | 1796 | 90 | 0 |

## 各 Case Eval 指标

### fv1_fact_02 / MEDIUM

| Group | Metric | Value | Passed | Reason |
|---|---|---:|---:|---|
| analysis | analysis_depth | 1.0000 | 1 | 对RMF四个核心功能和Profile补充机制进行了系统、多层次的解析，并提供了详细的映射表，逻辑严密。 |
| analysis | instruction_following | 1.0000 | 1 | 完全按照指令要求，解释了框架功能、Profile补充机制并给出了直接可用的映射关系表，格式正确。 |
| analysis | multi_source_synthesis | 1.0000 | 1 | 有效整合了NIST官方文档、风险类型分类和落地措施，引用清晰且综合度高。 |
| analysis | uncertainty_calibration | 0.8000 | 1 | 提到了度量方法成熟度和风险识别不确定性等挑战，但未对具体结论标注置信度或范围。 |
| cost | cost_per_pass | - | None | cost=None gate_passed=0 |
| cost | tokens_per_pass_k | - | None | tokens=84625 gate_passed=0 |
| cost | total_cost | - | None | tokens=84625 |
| cost | total_tokens_k | 84.6250 | None | input_tokens=59180 output_tokens=25445 |
| factuality | citation_completeness | 1.0000 | 1 | 报告在关键声明处均附有参考文献标记，引用齐全。 |
| factuality | citation_correctness | 1.0000 | 1 | 引用的参考文献编号与报告末尾的参考文献列表对应，且引用内容与声明逻辑一致。 |
| factuality | citation_parse_rate | 0.0000 | 0 | md_urls=0 numeric_markers=4 |
| factuality | citation_traceability | 0.0000 | 0 | cited=0/20 |
| factuality | claim_factuality | 1.0000 | 1 | 报告中的关键声明与NIST官方文档描述一致，引用内容合理。 |
| factuality | effective_citation_count | 2.0000 | None | md_urls=0 numeric=4 |
| factuality | supported_claim_count | 0.0000 | 0 | supported=0/20 |
| factuality | unsupported_critical_claim_count | 0.0000 | 1 | critical claims without citation_url |
| gate | hard_gate_passed | 0.0000 | 0 | gate_passed=0, failure_codes=['dangling_citation'] |
| gate | report_non_empty | 1 | 1 |  |
| gate | workflow_completed | 1 | 1 | outcome=success |
| intent | clarification_decision_accuracy | 1.0000 | 1 | expected_should_clarify=False actual=False |
| intent | intent_alignment | 1.0000 | 1 | type_accuracy=1.0 clarification_decision_accuracy=1.0 |
| intent | intent_type_accuracy | 1.0000 | 1 | expected=fact_lookup actual=fact_lookup |
| mechanism | best_draft_quality | - | None | 非 HIGH 双 draft 路径（draft_count=0），跳过 |
| mechanism | citation_retention_after_revision | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | claim_retention_after_revision | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | draft_complementarity | - | None | 非 HIGH 双 draft 路径（draft_count=0），跳过 |
| mechanism | merge_information_loss | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | reviewer_consensus_predictiveness | 0.0000 | None | consensus=None outcome=success |
| mechanism | reviewer_token_cost | 0.0000 | None | lenses=0 |
| mechanism | synthesis_uplift | - | None | 非 HIGH 双 draft 路径（draft_count=0），跳过 |
| meta | critical_claim_count | 0.0000 | None | total_claims=20 |
| recall | critical_fact_recall | 1.0000 | 1 | 报告准确复述了两个关键事实：明确指出 AI RMF 包含 Govern、Map、Measure、Manage 四个功能，并强调 Generative AI Profile 是跨行业补充资源，不取代 AI RMF 1.0。 |
| recall | required_point_coverage | 1.0000 | 1 | 报告覆盖了全部三个必须点：完整解析了四个核心功能及其闭环关系，明确说明了 GenAI Profile 是配套资源而非替代框架，并为每个核心功能提供了可直接落地的企业控制活动映射表。 |
| source | source_freshness | 0.9667 | 1 | source_freshness≈0.9667（近似：valid_ratio=1.00, domain_diversity=0.89）。MVP source_snapshot 未落 published_at/fetched_at，此为有效度近似，非真时效。 |
| source | source_quality | 1.0000 | 1 | 综合来源权威（包含NIST官方文档和多个权威AI治理网站）、来源多样性高（不同域名和类型）、与报告声明高度匹配。 |

### fv1_fact_02 / HIGH

| Group | Metric | Value | Passed | Reason |
|---|---|---:|---:|---|
| analysis | analysis_depth | 0.9000 | 1 | 深入解析了AI RMF四个功能与Generative AI Profile的细节，并使用对比表格和映射矩阵，分析全面。 |
| analysis | instruction_following | 0.9500 | 1 | 严格遵循research_brief要求，系统解释了核心功能、Profile补充关系，并提供了具体落地方向。 |
| analysis | multi_source_synthesis | 0.8000 | 1 | 主要依赖NIST两份核心文献，综合了官方内容并清晰对比，但缺乏其他权威或实证来源的补充。 |
| analysis | uncertainty_calibration | 0.6000 | 1 | 未明确标注报告中的假设、局限性或知识缺口，例如未说明行动建议的适用边界。 |
| cost | cost_per_pass | - | None | cost=None gate_passed=0 |
| cost | tokens_per_pass_k | - | None | tokens=118057 gate_passed=0 |
| cost | total_cost | - | None | tokens=118057 |
| cost | total_tokens_k | 118.0570 | None | input_tokens=86416 output_tokens=31641 |
| factuality | citation_completeness | 0.9000 | 1 | 大部分关键数据有引用，但少数具体细节（如子类别数量）未添加引用，略有不足。 |
| factuality | citation_correctness | 0.8000 | 1 | 部分引用不精确，例如用[3]支持Profile的12个风险类别，实际[3]不包含此信息。 |
| factuality | citation_parse_rate | 0.0000 | 0 | md_urls=0 numeric_markers=6 |
| factuality | citation_traceability | 0.0000 | 0 | cited=0/25 |
| factuality | claim_factuality | 1.0000 | 1 | 关键声明（如NIST AI RMF结构、Profile的定位和规模）与官方信息一致，无事实错误。 |
| factuality | effective_citation_count | 3.0000 | None | md_urls=0 numeric=6 |
| factuality | supported_claim_count | 0.0000 | 0 | supported=0/25 |
| factuality | unsupported_critical_claim_count | 3.0000 | 0 | critical claims without citation_url |
| gate | hard_gate_passed | 0.0000 | 0 | gate_passed=0, failure_codes=['dangling_citation', 'unsupported_critical_claim'] |
| gate | report_non_empty | 1 | 1 |  |
| gate | workflow_completed | 1 | 1 | outcome=success |
| intent | clarification_decision_accuracy | 1.0000 | 1 | expected_should_clarify=False actual=False |
| intent | intent_alignment | 1.0000 | 1 | type_accuracy=1.0 clarification_decision_accuracy=1.0 |
| intent | intent_type_accuracy | 1.0000 | 1 | expected=fact_lookup actual=fact_lookup |
| mechanism | best_draft_quality | 84.0000 | 1 | best draft=comparative quality_proxy=84.0（claim+citation 密度代理，非 judge 分） |
| mechanism | citation_retention_after_revision | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | claim_retention_after_revision | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | draft_complementarity | 0.9847 | 1 | 两 draft 互补度=0.9847（only-in-one / union，越高越值得融合） |
| mechanism | merge_information_loss | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | reviewer_consensus_predictiveness | 0.0000 | None | consensus=None outcome=success |
| mechanism | reviewer_token_cost | 0.0000 | None | lenses=0 |
| mechanism | synthesis_uplift | 21.0000 | 1 | uplift=21.0（synth_q=105.0 - best_draft_q=84.0）。MVP draft judge 分未落库，用密度代理；正值表示 synthesis 比最优 draft 更密。 |
| meta | critical_claim_count | 3.0000 | None | total_claims=25 |
| recall | critical_fact_recall | 1.0000 | 1 | 报告准确复述了AI RMF四个功能的存在及其迭代关系，并多次明确Profile是配套资源而非替代框架。 |
| recall | required_point_coverage | 1.0000 | 1 | 报告完整覆盖了三个必点：四个功能的作用与关系、Profile与AI RMF的配套关系、以及每个功能对应的企业活动映射。 |
| source | source_freshness | 0.9250 | 1 | source_freshness≈0.925（近似：valid_ratio=1.00, domain_diversity=0.75）。MVP source_snapshot 未落 published_at/fetched_at，此为有效度近似，非真时效。 |
| source | source_quality | 0.9500 | 1 | 来源包含多个NIST官方文档链接，权威性高；域名类型多样（.gov、.com、组织等）；来源与报告声明的核心文档匹配度极高。 |

### fv1_fact_02 / ULTRA

| Group | Metric | Value | Passed | Reason |
|---|---|---:|---:|---|
| analysis | analysis_depth | 0.9000 | 1 | 对核心功能定义、子类别、相互关系及生成式AI特有风险的深入分析到位，但稍显重复。 |
| analysis | instruction_following | 0.8000 | 1 | 基本遵循研究简报要求，解释了核心功能和Profile补充，但企业落地对应表未在节选中完整呈现。 |
| analysis | multi_source_synthesis | 0.9000 | 1 | 综合了NIST官方、第三方解读等多源信息，引用详实，但部分段落略显堆砌。 |
| analysis | uncertainty_calibration | 0.7000 | 1 | 引用了明确出处，但未对自身解读的不确定性进行标注或讨论不同资料的置信度。 |
| cost | cost_per_pass | - | None | cost=None gate_passed=1 |
| cost | tokens_per_pass_k | 215.6500 | None | tokens=215650 gate_passed=1 |
| cost | total_cost | - | None | tokens=215650 |
| cost | total_tokens_k | 215.6500 | None | input_tokens=150498 output_tokens=65152 |
| factuality | citation_completeness | 1.0000 | 1 | 关键声明均附有官方来源或权威解读的引用，覆盖全面。 |
| factuality | citation_correctness | 1.0000 | 1 | 每个引用均直接支持对应声明，来源可靠且指向正确。 |
| factuality | citation_parse_rate | 1.0000 | 1 | md_urls=11 numeric_markers=0 |
| factuality | citation_traceability | 1.0000 | 1 | cited=46/46 |
| factuality | claim_factuality | 1.0000 | 1 | 报告对NIST AI RMF核心功能、Generative AI Profile及其关系的描述准确，与官方文档一致。 |
| factuality | effective_citation_count | 11.0000 | None | md_urls=11 numeric=0 |
| factuality | supported_claim_count | 46.0000 | 1 | supported=46/46 |
| factuality | unsupported_critical_claim_count | 0.0000 | 1 | critical claims without citation_url |
| gate | hard_gate_passed | 1.0000 | 1 | gate_passed=1, failure_codes=[] |
| gate | report_non_empty | 1 | 1 |  |
| gate | workflow_completed | 1 | 1 | outcome=degraded |
| intent | clarification_decision_accuracy | 1.0000 | 1 | expected_should_clarify=False actual=False |
| intent | intent_alignment | 1.0000 | 1 | type_accuracy=1.0 clarification_decision_accuracy=1.0 |
| intent | intent_type_accuracy | 1.0000 | 1 | expected=fact_lookup actual=fact_lookup |
| mechanism | best_draft_quality | - | None | 非 HIGH 双 draft 路径（draft_count=0），跳过 |
| mechanism | citation_retention_after_revision | 1.0000 | 1 | revision 相对 draft 平均 citation 保留率=1.0 |
| mechanism | claim_retention_after_revision | 0.6587 | 0 | revision 相对 draft 平均 claim 保留率=0.6587 |
| mechanism | draft_complementarity | - | None | 非 HIGH 双 draft 路径（draft_count=0），跳过 |
| mechanism | merge_information_loss | 0.1875 | 1 | merged 相对 section draft 信息丢失=0.1875（claim_retain=0.62, cite_retain=1.00） |
| mechanism | reviewer_consensus_predictiveness | 0.0000 | None | consensus=split outcome=degraded |
| mechanism | reviewer_token_cost | 6726.0000 | None | lenses=2 |
| mechanism | synthesis_uplift | - | None | 非 HIGH 双 draft 路径（draft_count=0），跳过 |
| meta | critical_claim_count | 46.0000 | None | total_claims=46 |
| recall | critical_fact_recall | 1.0000 | 1 | 报告准确复述了两个关键事实：AI RMF四个核心功能（第2节），以及Generative AI Profile是配套资源不替代RMF（第2.6节和第3节）。 |
| recall | required_point_coverage | 1.0000 | 1 | 报告完整覆盖了所有三个必须点：Govern/Map/Measure/Manage解释、Profile与RMF关系、企业控制活动映射。 |
| source | source_freshness | 0.9471 | 1 | source_freshness≈0.9471（近似：valid_ratio=1.00, domain_diversity=0.82）。MVP source_snapshot 未落 published_at/fetched_at，此为有效度近似，非真时效。 |
| source | source_quality | 0.9500 | 1 | 报告引用多个NIST官方文档及权威第三方解读，来源权威且多样，与报告内容高度匹配。 |

### fv1_ec_01 / MEDIUM

| Group | Metric | Value | Passed | Reason |
|---|---|---:|---:|---|
| analysis | analysis_depth | 0.9500 | 1 | 量化分析五个关键因素及方法学差异，深入揭示变量对排放的影响机制。 |
| analysis | instruction_following | 0.9500 | 1 | 完全遵循题目要求，对比三类研究、统一功能单位、分析五个因素并给出适用条件，格式规范。 |
| analysis | multi_source_synthesis | 0.9000 | 1 | 综合ICCT、JRC、MIT等权威研究，但极少数来源权威性稍弱，整体综合质量高。 |
| analysis | uncertainty_calibration | 0.8500 | 1 | 设有专门的不确定性声明，提及数据缺口，但缺少对核心数值的置信区间描述。 |
| cost | cost_per_pass | - | None | cost=None gate_passed=0 |
| cost | tokens_per_pass_k | - | None | tokens=69781 gate_passed=0 |
| cost | total_cost | - | None | tokens=69781 |
| cost | total_tokens_k | 69.7810 | None | input_tokens=51632 output_tokens=18149 |
| factuality | citation_completeness | 0.4000 | 0 | 正文中约30处引用标注仅有部分在claim_citations中提供URL，且多个urls为空，说明引用来源记录不完整。 |
| factuality | citation_correctness | 0.3000 | 0 | claim_citations中url与对应声明匹配度低，例如MIT工具URL出现在ICCT声明下，且无证据表明URL直接支持对应数值。 |
| factuality | citation_parse_rate | 1.0000 | 1 | md_urls=14 numeric_markers=16 |
| factuality | citation_traceability | 0.0976 | 0 | cited=8/82 |
| factuality | claim_factuality | 0.8000 | 1 | 报告整体基于权威研究，逻辑严谨，但存在一处笔误（'IDCT'应为'ICCT'），且部分量化数值依赖假设，缺乏独立验证。 |
| factuality | effective_citation_count | 22.0000 | None | md_urls=14 numeric=16 |
| factuality | supported_claim_count | 8.0000 | 0 | supported=8/82 |
| factuality | unsupported_critical_claim_count | 51.0000 | 0 | critical claims without citation_url |
| gate | hard_gate_passed | 0.0000 | 0 | gate_passed=0, failure_codes=['dangling_citation', 'unsupported_critical_claim'] |
| gate | report_non_empty | 1 | 1 |  |
| gate | workflow_completed | 1 | 1 | outcome=success |
| intent | clarification_decision_accuracy | 1.0000 | 1 | expected_should_clarify=False actual=False |
| intent | intent_alignment | 1.0000 | 1 | type_accuracy=1.0 clarification_decision_accuracy=1.0 |
| intent | intent_type_accuracy | 1.0000 | 1 | expected=academic_review actual=academic_review |
| mechanism | best_draft_quality | - | None | 非 HIGH 双 draft 路径（draft_count=0），跳过 |
| mechanism | citation_retention_after_revision | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | claim_retention_after_revision | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | draft_complementarity | - | None | 非 HIGH 双 draft 路径（draft_count=0），跳过 |
| mechanism | merge_information_loss | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | reviewer_consensus_predictiveness | 0.0000 | None | consensus=None outcome=success |
| mechanism | reviewer_token_cost | 0.0000 | None | lenses=0 |
| mechanism | synthesis_uplift | - | None | 非 HIGH 双 draft 路径（draft_count=0），跳过 |
| meta | critical_claim_count | 59.0000 | None | total_claims=82 |
| recall | critical_fact_recall | 0.7000 | 1 | 报告通过全生命周期分析隐含了制造阶段排放高不等于总排放高的逻辑，但未直接复述该关键事实，因此有所不足。 |
| recall | required_point_coverage | 1.0000 | 1 | 报告统一了功能单位并交代了系统边界，详细分析了电网、电池、寿命、车型和回收五个关键参数，并给出了条件化适用情景，全面覆盖要求。 |
| source | source_freshness | 0.9700 | 1 | source_freshness≈0.97（近似：valid_ratio=1.00, domain_diversity=0.90）。MVP source_snapshot 未落 published_at/fetched_at，此为有效度近似，非真时效。 |
| source | source_quality | 0.7000 | 1 | 来源包括ICCT、JRC、NIH、Nature等权威机构，但部分来源（如substack、企业网站）权威性不足，多样性一般。 |

### fv1_ec_01 / HIGH

| Group | Metric | Value | Passed | Reason |
|---|---|---:|---:|---|
| analysis | analysis_depth | 1.0000 | 1 | 报告从电网碳强度到回收假设逐一展开定量分析，结合公式和敏感性排序，深度剖析了差异根源。 |
| analysis | instruction_following | 1.0000 | 1 | 严格按指令比较三类权威研究、统一功能单位、分析五大因素，并强调适用条件而非单一结论。 |
| analysis | multi_source_synthesis | 1.0000 | 1 | 有效整合ICCT、IEA、IPCC、Ecoinvent及多篇学术文献，形成跨类型对比表格，综合质量高。 |
| analysis | uncertainty_calibration | 1.0000 | 1 | 明确给出各因素影响范围及排放区间，强调结论依赖假设条件，不确定性标注充分。 |
| cost | cost_per_pass | - | None | cost=None gate_passed=0 |
| cost | tokens_per_pass_k | - | None | tokens=186026 gate_passed=0 |
| cost | total_cost | - | None | tokens=186026 |
| cost | total_tokens_k | 186.0260 | None | input_tokens=132096 output_tokens=53930 |
| factuality | citation_completeness | 0.9000 | 1 | 报告在多数关键结论处提供了引用标记，但部分概括性声明（如电网范围描述）未明确标注来源。 |
| factuality | citation_correctness | 0.9000 | 1 | 引用来源与研究假设匹配，但部分间接推断（如Ellingsen数据对近期的影响）依赖假设，需更直接支持。 |
| factuality | citation_parse_rate | 0.0000 | 0 | md_urls=0 numeric_markers=16 |
| factuality | citation_traceability | 0.0000 | 0 | cited=0/112 |
| factuality | claim_factuality | 1.0000 | 1 | 报告中的关键声明均有可靠数据支撑，未发现不实陈述。 |
| factuality | effective_citation_count | 8.0000 | None | md_urls=0 numeric=16 |
| factuality | supported_claim_count | 0.0000 | 0 | supported=0/112 |
| factuality | unsupported_critical_claim_count | 84.0000 | 0 | critical claims without citation_url |
| gate | hard_gate_passed | 0.0000 | 0 | gate_passed=0, failure_codes=['dangling_citation', 'unsupported_critical_claim'] |
| gate | report_non_empty | 1 | 1 |  |
| gate | workflow_completed | 1 | 1 | outcome=success |
| intent | clarification_decision_accuracy | 1.0000 | 1 | expected_should_clarify=False actual=False |
| intent | intent_alignment | 1.0000 | 1 | type_accuracy=1.0 clarification_decision_accuracy=1.0 |
| intent | intent_type_accuracy | 1.0000 | 1 | expected=academic_review actual=academic_review |
| mechanism | best_draft_quality | 82.0000 | 1 | best draft=comparative quality_proxy=82.0（claim+citation 密度代理，非 judge 分） |
| mechanism | citation_retention_after_revision | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | claim_retention_after_revision | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | draft_complementarity | 0.9554 | 1 | 两 draft 互补度=0.9554（only-in-one / union，越高越值得融合） |
| mechanism | merge_information_loss | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | reviewer_consensus_predictiveness | 0.0000 | None | consensus=None outcome=success |
| mechanism | reviewer_token_cost | 0.0000 | None | lenses=0 |
| mechanism | synthesis_uplift | 25.0000 | 1 | uplift=25.0（synth_q=107.0 - best_draft_q=82.0）。MVP draft judge 分未落库，用密度代理；正值表示 synthesis 比最优 draft 更密。 |
| meta | critical_claim_count | 84.0000 | None | total_claims=112 |
| recall | critical_fact_recall | 1.0000 | 1 | 准确复述生命周期结论依赖假设和地理背景，隐含支持制造阶段高排放不自动决定全生命周期。 |
| recall | required_point_coverage | 1.0000 | 1 | 报告覆盖了全部三个必须点：功能单位统一、关键参数解释、条件化结论与敏感性。 |
| source | source_freshness | 0.9571 | 1 | source_freshness≈0.9571（近似：valid_ratio=1.00, domain_diversity=0.86）。MVP source_snapshot 未落 published_at/fetched_at，此为有效度近似，非真时效。 |
| source | source_quality | 0.9500 | 1 | 来源涵盖ICCT、IEA、IPCC等权威机构及多篇高引学术论文，域名和类型多样，与报告声明高度匹配。 |

### fv1_ec_01 / ULTRA

| Group | Metric | Value | Passed | Reason |
|---|---|---:|---:|---|
| analysis | analysis_depth | 0.0000 | 0 | 报告摘要为空，无法评估分析深度。 |
| analysis | instruction_following | 0.0000 | 0 | 报告摘要为空，未遵循提供内容的要求。 |
| analysis | multi_source_synthesis | 0.0000 | 0 | 报告摘要为空，无法评估多源综合质量。 |
| analysis | uncertainty_calibration | 0.0000 | 0 | 报告摘要为空，无法评估不确定性标注。 |
| cost | cost_per_pass | - | None | cost=None gate_passed=0 |
| cost | tokens_per_pass_k | - | None | tokens=1796 gate_passed=0 |
| cost | total_cost | - | None | tokens=1796 |
| cost | total_tokens_k | 1.7960 | None | input_tokens=924 output_tokens=872 |
| factuality | citation_completeness | 0.0000 | 0 | 无引用内容，无法判断完整性。 |
| factuality | citation_correctness | 0.0000 | 0 | 无引用内容，无法判断正确性。 |
| factuality | citation_parse_rate | 1.0000 | 1 | md_urls=0 numeric_markers=0 |
| factuality | citation_traceability | - | None | claim_manifest 为空，citation_traceability 不可评估 |
| factuality | claim_factuality | 0.0000 | 0 | 报告摘录为空，无声明可评估。 |
| factuality | effective_citation_count | 0.0000 | None | md_urls=0 numeric=0 |
| factuality | supported_claim_count | 0.0000 | 1 | supported=0/0 |
| factuality | unsupported_critical_claim_count | 0.0000 | 1 | critical claims without citation_url |
| gate | hard_gate_passed | 0.0000 | 0 | gate_passed=0, failure_codes=['workflow_failed', 'report_empty', 'missing_required_points', 'critical_fact_error'] |
| gate | report_non_empty | 0 | 0 |  |
| gate | workflow_completed | 0 | 0 | outcome=hitl_wait |
| intent | clarification_decision_accuracy | 0.0000 | 0 | expected_should_clarify=False actual=True |
| intent | intent_alignment | 0.0000 | 0 | type_accuracy=None clarification_decision_accuracy=0.0 |
| intent | intent_type_accuracy | - | None | expected=academic_review actual=None |
| mechanism | best_draft_quality | - | None | 非 HIGH 双 draft 路径（draft_count=0），跳过 |
| mechanism | citation_retention_after_revision | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | claim_retention_after_revision | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | draft_complementarity | - | None | 非 HIGH 双 draft 路径（draft_count=0），跳过 |
| mechanism | merge_information_loss | - | None | 无 section artifact（非 Section Team 路径），跳过 |
| mechanism | reviewer_consensus_predictiveness | 0.0000 | None | consensus=None outcome=hitl_wait |
| mechanism | reviewer_token_cost | 0.0000 | None | lenses=0 |
| mechanism | synthesis_uplift | - | None | 非 HIGH 双 draft 路径（draft_count=0），跳过 |
| meta | critical_claim_count | 0.0000 | None | total_claims=0 |
| recall | critical_fact_recall | 0.0000 | 0 | 报告摘录为空，未复述任何关键参考事实。 |
| recall | required_point_coverage | 0.0000 | 0 | 报告摘录为空，未覆盖任何必须点。 |
| source | source_freshness | 0.0000 | 0 | 无来源快照，source_freshness=0 |
| source | source_quality | 0.0000 | 0 | 没有提供任何来源，无法评估来源质量。 |


# Eval 配对差异报告

## 各 Variant 指标均值
| Metric | MEDIUM | HIGH | ULTRA |
|---|---|---|---|
| analysis_depth | 0.9750 | 0.9500 | 0.4500 |
| best_draft_quality | - | 83.0000 | - |
| citation_completeness | 0.7000 | 0.9000 | 0.5000 |
| citation_correctness | 0.6500 | 0.8500 | 0.5000 |
| citation_parse_rate | 0.5000 | 0.0000 | 1.0000 |
| citation_retention_after_revision | - | - | 1.0000 |
| citation_traceability | 0.0488 | 0.0000 | 1.0000 |
| claim_factuality | 0.9000 | 1.0000 | 0.5000 |
| claim_retention_after_revision | - | - | 0.6587 |
| clarification_decision_accuracy | 1.0000 | 1.0000 | 0.5000 |
| critical_claim_count | 29.5000 | 43.5000 | 23.0000 |
| critical_fact_recall | 0.8500 | 1.0000 | 0.5000 |
| draft_complementarity | - | 0.9701 | - |
| effective_citation_count | 12.0000 | 5.5000 | 5.5000 |
| hard_gate_passed | 0.0000 | 0.0000 | 0.5000 |
| instruction_following | 0.9750 | 0.9750 | 0.4000 |
| intent_alignment | 1.0000 | 1.0000 | 0.5000 |
| intent_type_accuracy | 1.0000 | 1.0000 | 1.0000 |
| merge_information_loss | - | - | 0.1875 |
| multi_source_synthesis | 0.9500 | 0.9000 | 0.4500 |
| required_point_coverage | 1.0000 | 1.0000 | 0.5000 |
| reviewer_consensus_predictiveness | 0.0000 | 0.0000 | 0.0000 |
| reviewer_token_cost | 0.0000 | 0.0000 | 3363.0000 |
| source_freshness | 0.9684 | 0.9410 | 0.4736 |
| source_quality | 0.8500 | 0.9500 | 0.4750 |
| supported_claim_count | 4.0000 | 0.0000 | 23.0000 |
| synthesis_uplift | - | 23.0000 | - |
| tokens_per_pass_k | - | - | 215.6500 |
| total_tokens_k | 77.2030 | 152.0415 | 108.7230 |
| uncertainty_calibration | 0.8250 | 0.8000 | 0.3500 |
| unsupported_critical_claim_count | 25.5000 | 43.5000 | 0.0000 |

## 相邻档位差值（uplift）
| Metric | MEDIUM→HIGH | HIGH→ULTRA |
|---|---|---|
| analysis_depth | -0.0250 | -0.5000 |
| best_draft_quality | - | - |
| citation_completeness | +0.2000 | -0.4000 |
| citation_correctness | +0.2000 | -0.3500 |
| citation_parse_rate | -0.5000 | +1.0000 |
| citation_retention_after_revision | - | - |
| citation_traceability | -0.0488 | +1.0000 |
| claim_factuality | +0.1000 | -0.5000 |
| claim_retention_after_revision | - | - |
| clarification_decision_accuracy | +0.0000 | -0.5000 |
| critical_claim_count | +14.0000 | -20.5000 |
| critical_fact_recall | +0.1500 | -0.5000 |
| draft_complementarity | - | - |
| effective_citation_count | -6.5000 | +0.0000 |
| hard_gate_passed | +0.0000 | +0.5000 |
| instruction_following | +0.0000 | -0.5750 |
| intent_alignment | +0.0000 | -0.5000 |
| intent_type_accuracy | +0.0000 | +0.0000 |
| merge_information_loss | - | - |
| multi_source_synthesis | -0.0500 | -0.4500 |
| required_point_coverage | +0.0000 | -0.5000 |
| reviewer_consensus_predictiveness | +0.0000 | +0.0000 |
| reviewer_token_cost | +0.0000 | +3363.0000 |
| source_freshness | -0.0273 | -0.4675 |
| source_quality | +0.1000 | -0.4750 |
| supported_claim_count | -4.0000 | +23.0000 |
| synthesis_uplift | - | - |
| tokens_per_pass_k | - | - |
| total_tokens_k | +74.8385 | -43.3185 |
| uncertainty_calibration | -0.0250 | -0.4500 |
| unsupported_critical_claim_count | +18.0000 | -43.5000 |

## 决策输出（§19）
- 质量代理 `effective_citation_count`：MEDIUM=12.0000 → ULTRA=5.5000，配对差值 -6.5000
- 哪些 Task Type 在 HIGH/ULTRA 上有正 Uplift？见 `synthesis_uplift` / `quality_delta_per_round`。
- 哪个机制被更轻量 Variant 支配？比较 `marginal_quality_per_1k_tokens`。
- Reviewer 哪个 Lens 有效？见 `reviewer_consensus_predictiveness`。
- ClaimVerifier 是否值得全量跑？见 `unsupported_claim_detection_recall` vs `verification_token_cost`。
