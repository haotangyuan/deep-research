# 可观测性链路 + Eval 评测系统 — 简历素材整理

> 整理时间:2026-07-26
> 用途:写简历的可观测部分和 eval 部分时回溯的详细底稿。简历正文取最后的"精简版"。

---

## 第一部分:可观测性链路(Observability)

### 一、整体工作流:`workflow → stage → model/tool` 四层 span 树

一次研究在 trace 里长成一棵树,从根到叶四层,每层是不同粒度的"一件事":

```
deep_research.workflow                    ← 根:这一次研究(全程)
│
└─ deep_research.stage {ScopeAgent}        ← 阶段1:需求澄清
│   └─ deep_research.model {mimo}          ←      调一次LLM澄清需求
│
└─ deep_research.stage {UltraDynamicReview}← 阶段2:对抗评审(第1轮)
│   ├─ deep_research.model {mimo}          ←      reviewer A 调LLM
│   ├─ deep_research.model {mimo}          ←      reviewer B 调LLM
│   └─ deep_research.tool {tavilySearch}   ←      补一次搜索
│
└─ deep_research.stage {ReportSectionTeam} ← 阶段3:章节报告团队
│   └─ deep_research.model {mimo}          ←      写某一节
│
└─ deep_research.stage {UltraReportGate}   ← 阶段4:质量门判定
```

- **workflow**(根):这一次研究整体——跑完了吗、成功还是降级、总共烧了多少 token。
- **stage**:研究的一个阶段——Scope 澄清、Supervisor 编排、UltraDynamicReview 评审、章节团队写报告、UltraReportGate 质量门。
- **model**:一次 LLM 调用——调了哪个模型、用了多少 token、成功还是失败。
- **tool**:一次工具调用——搜了什么、检索了什么。

**为什么是这个结构**:研究是分阶段、分轮次、有并行的(N 个 reviewer 同时跑、多个 section 同时写)。树状嵌套天然表达"谁在谁之下"。顺着树从根到叶,能精确定位"这一次研究的这个阶段、这一轮、这个 agent、这一次调用"。父子嵌套关系本身就是"链路"。

### 二、OTel Provider:应用 span 和 AgentScope 原生 span 的处理

**问题背景**:AgentScope 框架内部也有埋点(`invoke_agent` / `chat` / `execute_tool`)。若应用层和框架各埋各的,出现两条独立 trace——事后靠手动拼 `trace_id` 串,但**父子关系是断的**:AgentScope 的 `chat` span 不会自动成为应用层 `stage` span 的子节点。

**做法**:
- 应用层启动时(`init_observability`),建**一个全局 `TracerProvider`**,注册给 OTel(`trace.set_tracer_provider`)。`service.name=deep-research`,带 `BatchSpanProcessor` + `OTLPSpanExporter`。
- AgentScope 2.0.3 的 `TracingMiddleware`,在埋框架内部 span 时,**读的是这同一个全局 Provider**(只在 `RESEARCH_OBSERVABILITY_ENABLED=true` 时插入)。

**结果**:因用同一 Provider,OTel 的"当前 span 上下文"全局共享。应用层进入 `async with stage_span("UltraDynamicReview")`,该 stage span 成为"当前 span";AgentScope 内部紧接着埋的 `invoke_agent` / `chat` span,自动挂到当前 span 下当子节点——**框架原生 span 天然成为业务 span 子节点**,不用手动指定 parent。

**和"事后拼 trace_id"的本质区别**:
- 事后拼:两条 trace 用 `trace_id` 相同关联,但 `parent_span_id` 空或错,Langfuse 里看不到嵌套。
- 共享 Provider:从一开始框架 span 的 `parent_span_id` 就指向应用 stage span,四层是**真实父子链**。

**性能/降级**:观测关闭时(`RESEARCH_OBSERVABILITY_ENABLED=false`),不建 Provider、不插 `TracingMiddleware`,全局是 OTel 默认 `NonRecordingSpan`。`async with stage_span(...)` 近乎零开销,新增埋点不用加 `if enabled` 判断——关了是空操作,开了就生效。导出走 OTLP/HTTP,默认 Langfuse 后端。

### 三、业务决策维度的埋点:内容和意义

#### 3.1 对抗评审决策(`UltraDynamicReview` span,每轮一组)

ULTRA 每轮 N 个 reviewer 投票,决定继续研究还是出报告:

| 属性 | 意义 |
|---|---|
| `review.lens.count` | 这轮用了几个 reviewer 视角 |
| `review.continue.threshold` | 继续研究要几票才过阈值 |
| `review.next.action` | 这轮决策:continue / report |
| `review.continue.votes` | 投"继续"的票数 |
| `review.report.votes` | 投"出报告"的票数 |
| `review.total.votes` | 总票数 |
| `review.consensus` | 共识:continue / report / split(分裂) |
| `review.gaps.count` | 识别出的证据缺口数(取前5) |
| `review.score.coverage` | 覆盖度评分(1-5) |
| `review.score.evidence` | 证据充分度评分 |
| `review.score.freshness` | 时效性评分 |
| `review.score.sourceDiversity` | 来源多样性评分 |
| `review.score.consistency` | 一致性评分 |

**意义**:原本只写 MySQL 决策日志和 SSE,trace 里看不到。埋上去后,能在 Langfuse 直接按 `review.next.action=report` 或 `review.consensus=split` 过滤——回答"多少轮是分裂投票才强行继续""哪些研究证据缺口一直没闭合"。**动态决策从黑盒变白盒**。

#### 3.2 报告质量门(`UltraReportGate` span,无轮次)

| 属性 | 意义 |
|---|---|
| `report.quality.status` | ready / needs_disclosure(证据不足需加免责声明) |
| `report.weak.sections.count` | 弱章节数量 |
| `report.blocking.gaps.count` | 阻塞性证据缺口数 |

**意义**:把"报告质量"做成 trace 一等维度。能在 Langfuse 按 `needs_disclosure` 过滤——回答"ULTRA 这个最贵档位,产出的报告有多少比例证据不足"。

#### 3.3 公共属性(所有 span 自动带)

`_set_common` 一处定义,四种 span 全带:`research.id`、`user.id`、`model.id`、`budget.level`(MEDIUM/HIGH/ULTRA)、`workflow.mode`(FIXED/DYNAMIC)、`dynamic.round.no`(第几轮)。

**纪律**:只放低基数枚举(轮次1-5、评分1-5、几个 section_id),绝不放 claim 全文、搜索词、报告正文。高基数数据撑爆 Langfuse 查询和存储成本,那些走 DB 和 SSE。

### 四、落库的表:内容、意义、怎么用到 eval

可观测往 MySQL 落**三张表**(不只 span_attribute 一张)。

#### 4.1 `research_llm_call` —— 每次 LLM 调用一行(Token 单一事实源)

**谁写**:`llm.py` 每次 LLM 调用结束时,`eval_repository.record_llm_call(...)` 落一行。

**表列和内容**:

| 列 | 内容/示例 | 意义 |
|---|---|---|
| `llm_call_id` | PK,稳定 ID | 去重 replay 用 |
| `trace_id` | 32 hex | 这条调用挂在哪条 trace |
| `run_id` / `research_id` | 哪次研究 | 切片主键 |
| `stage_name` | `UltraDynamicReview` / `ReportAgent` | 哪个阶段 |
| `agent_name` | `UltraDynamicReviewer:coverage` | 哪个 agent(M1 加,解开角色塌缩) |
| `round_no` | 1 / 2 / 3 | 哪一轮(M2 加) |
| `report_phase` | `merge` / `section_draft` / `judge` | 报告哪步(llm_attribution 派生) |
| `reviewer_lens` | `coverage` / `evidence` | 哪个 reviewer 视角(派生) |
| `section_id` | `supply-chain-risk` | 哪个章节(派生) |
| `request_model` / `response_model` | `mimo` | 用了哪个模型 |
| `input_tokens` / `output_tokens` | 1250 / 340 | **token 用量** |
| `duration_ms` | 2300 | 耗时 |
| `attempt_no` | 1 / 2 | Layer-C 重试第几次 |
| `outcome` | `success` / `degraded` | 成功/失败/降级 |

**意义**:trace 的"可评估投影"。trace 在 Langfuse 是树状、要进 UI 才能看;本表把 trace 里和成本、切片相关的维度全部拍平成表行。一次 ULTRA 跑几百次调用 = 几百行。

**怎么用到 eval**:
- `CostEffectivenessEvaluator` 读汇总(总 input/output token + `estimated_cost`),算 `total_cost` / `cost_per_pass`。
- 投影 `research_stage_usage` 给 `RoundDeltaEvaluator` 算边际质量分母、给 `ReviewerEffectivenessEvaluator` 算 `reviewer_token_cost`。
- `llm_attribution` 派生六列(`report_phase`/`reviewer_lens`/`round_no`/`section_id` 等)让 eval 按"章节 draft + supply-chain-risk 这一节烧了多少 token"切片——成本归因。

#### 4.2 `research_stage_usage` —— 阶段级 token 聚合(投影)

**谁写**:`record_llm_call` 落 `research_llm_call` 时顺带投影聚合。

**表列和内容**:

| 列 | 内容 | 意义 |
|---|---|---|
| `run_id` | 哪次研究 | 切片主键 |
| `stage_name` | `UltraDynamicReview` | 哪个阶段 |
| `round_no` | 1 / 2 | 哪一轮 |
| `report_phase` | `section_draft` | 报告哪步 |
| `reviewer_lens` | `coverage` | 哪个视角 |
| `section_id` | `supply-chain-risk` | 哪个章节 |
| `request_count` | 12 | 该聚合下调用次数 |
| `retry_count` | 1 | 重试次数 |
| `input_tokens` / `output_tokens` | 5000 / 1200 | 该聚合下 token 合计 |

**意义**:把细碎 per-call token 聚合成 per-stage/per-round/per-section,eval 不用自己 group by。**只是投影,不是另一份事实源**——`research_llm_call` 才是事实源,本表为查询方便建。`record_llm_call` 用显式存在性检查区分 insert/update,仅新插入时累加,避免 replay 重复计费。

**怎么用到 eval**:
- `RoundDeltaEvaluator` 算 `marginal_quality_per_1k_tokens` 的分母 `review.tokens` = 本表 `(run_id, stage_name=UltraDynamicReview, round_no)` token 合计。
- `ReviewerEffectivenessEvaluator` 算 `reviewer_token_cost` = 本表 reviewer 相关 token 合计。

#### 4.3 `research_span_attribute` —— 动态决策标量(一个 attr 一行)

**谁写**:`ultra_dynamic.py` 每轮评审后、`pipeline.py` 质量门判定后,`eval_repository.upsert_span_attributes(...)` 落库。

**表列和内容**:

| 列 | 内容 | 意义 |
|---|---|---|
| `id` | PK | |
| `run_id` / `research_id` | 哪次研究 | 切片主键 |
| `trace_id` | 32 hex | 哪条 trace |
| `span_scope` | `UltraDynamicReview` / `UltraReportGate` | 哪个 span 写的 |
| `round_no` | 1 / 2(质量门为0) | 哪一轮 |
| `attr_key` | `review.consensus` 等 | 属性名 |
| `attr_value_num` | 3.0 | 数值类(票数/评分/缺口数) |
| `attr_value_str` | `split` | 字符串类(consensus/status) |
| `attr_value_json` | `["gap_a","gap_b"]` | JSON 类(缺口列表等) |

**幂等键**:`(run_id, span_scope, round_no, attr_key)`,replay 时 `ON DUPLICATE KEY UPDATE` 覆盖。

**一次两轮研究表里大概的行数**:

`span_scope=UltraDynamicReview, round_no=1`(约10行):
```
review.consensus=split(str)   review.continue.votes=2(num)
review.report.votes=1          review.total.votes=3
review.gaps.count=3            review.score.coverage=3
review.score.evidence=3        review.score.freshness=3
review.score.sourceDiversity=3 review.score.consistency=3
```

`span_scope=UltraDynamicReview, round_no=2`(约10行,值变了):
```
review.consensus=report        review.continue.votes=0
review.gaps.count=1            review.score.coverage=4
review.score.evidence=4        ...
```

`span_scope=UltraReportGate, round_no=0`(约2行):
```
report.quality.status=needs_disclosure(str)
report.weak.sections.count=1(num)
```

**意义**:给那些"只在 span 流过那一刻存在"的决策标量抄一份留库。span 是临时对象,出 `async with` 块就 end,不抄走就只剩 Langfuse 云上那份,应用侧离线查不到。**和 `research_artifact` 严格分工**:artifact 存产出全文(报告正文、claim 清单),本表只存标量,同一份数据不两处重复落库。

**怎么用到 eval**(`runner._load_case_context` 一次查询取回所有行,按 `span_scope` 分流):
- `UltraDynamicReview` 的行 → 装配 `ctx.review_attributes = {round_no: {attr_key: value}}`
- `UltraReportGate` 的行 → 装配 `ctx.report_quality = {attr_key: value}`
- `RoundDeltaEvaluator` 读 `review_attributes`:取每轮五维评分的 **min(短板)** 当该轮质量,两轮相减得 `quality_delta_per_round`,delta/本轮token×1000 得 `marginal_quality_per_1k_tokens`,(上轮gap-本轮gap)/上轮gap 得 `gap_closure_rate`。
- `report_quality` 的 `report.quality.status` 做证据充分性切片(统计多少 ULTRA 报告是 `needs_disclosure`)。
- 最后一轮的 `review.consensus` 喂 `ReviewerEffectivenessEvaluator`,算 `reviewer_consensus_predictiveness`(共识 vs 实际 outcome 对不对)。

### 五、可观测性改造动作(M1–M5)+ 1406 bug

| 改动 | 内容 |
|---|---|
| M1 | model span 加 `agent.name`,解开"所有 LLM 调用都叫 deep_research.model mimo"的塌缩,20+ 角色可区分 |
| M2 | `_set_common` 加 `workflow.mode` + `dynamic.round.no`,一处改全链路带轮次 |
| M3 | `UltraDynamicReview` span + 决策属性,把动态决策从黑盒变白盒 |
| M4 | 章节报告团队五步结构化(Planner→Draft→Consistency→Revise→Merge),解开 N 个并行 section draft 塌在 `stage ReportAgent` 下的塌缩 |
| M5 | `UltraReportGate` span + 质量属性,把"质量"做成一等可观测维度 |
| Bug 1406 | M4 改完第一次跑暴露:6 个 `ReportSectionDraft` 全 1406 ERROR(章节 draft 全文超 `TEXT` 列 64KB 上限),`ReportSectionTeam.run` 整体 `try/except` 静默回退 fallback——卖点功能从没跑通过。治本:列类型 `TEXT→MEDIUMTEXT` + 截断兜底 |

**意义**:埋点暴露被 `try/except` 吞掉的异常——可观测价值不只是看性能,是把隐藏 bug 显性化。

### 六、默认不采 I/O + 零成本降级

- `summarize()`:默认 `capture_io=false` 时返回 `None`,prompt 正文/响应不进 span。开启时也先脱敏(Authorization / api_key / secret / token → `[redacted]`)再截断。原因:高基数撑爆 Langfuse 查询和成本;含密钥/PII 风险;性能(几百个 span 带正文易让 batch 导出超时)。
- 观测关闭时全局是 `NonRecordingSpan`,新增 span 不用加 `if enabled` 门控。

---

## 第二部分:Eval 评测系统

### 一、整体架构:两层解耦链路

```
线上正常研究
→ 可靠记录 Run/版本/Token/Artifact/Source/Evidence(运行事实层 6 表)
→ 研究完成后异步冻结 Eval Candidate Snapshot

版本化 Dataset
→ 同题回放三档或机制 Variant
→ 确定性检查 + LLM Judge(eval 数据层 4 表)
→ 分数、原因、成本和 Trace 关联落库
```

**核心设计哲学**:
1. 一个物理 LLM 调用只能有一个 Token 事实源(禁止重复相加)。
2. 日常三档均值**不能**用于证明档位因果增益(选择偏差);档位结论必须来自**同 Dataset Item 配对回放**。
3. 所有 Eval 结果可反查 `dataset_item_id → case_run_id → run_id → trace_id/artifact_id`。
4. Eval/Snapshot 异步、失败不阻塞用户研究。

### 二、落库 10 张表(6 运行事实层 + 4 eval 数据层)

**运行事实层(6 张)**:
- `research_run`:一次连续后台执行,含 `trace_id`/`workflow_commit_sha`/`prompt_version_json`/`template_sha256`/token。
- `research_artifact`:所有可复现产物,按 `(run_id, artifact_type, round_no, section_id, angle, content_sha256)` 幂等。
- `research_llm_call`:**Token 唯一事实源**,PK 去重 replay,带六列归因。
- `research_stage_usage`:阶段级 token 投影。
- `research_claim_manifest`:claim-citation 清单。
- `research_span_attribute`:trace 标量本地落地(observability 桥接)。

**Eval 数据层(4 张)**:
- `eval_dataset_item`:脱敏版本化题目,按 `query_sha256` 去重。
- `eval_experiment`:6 种实验类型(tier_comparison/high_report_ablation/reviewer_ablation/multi_round_ablation/section_team_ablation/claim_verifier_ablation)。
- `eval_case_run`:单次回放,唯一键 `(experiment_id, dataset_item_id, variant_name, repeat_no)`。
- `eval_score`:通用分数,唯一键 `(case_run_id, metric_name, evaluator_version)`,带 `trace_id`+`report_artifact_id` 直链。

### 三、9 个 Evaluator 详解(核心必要 5 + 支撑必要 4)

> 选型依据:按"删掉这个 evaluator,eval 体系会缺什么不可替代的能力"分两档。核心 5 个是 eval 站不住的(工程必需 3 + 可观测桥接必需 2),支撑 4 个是评测系统标配(需 `chat_fn`,全量评测启用、离线可选)。这 9 个覆盖 eval 的两个核心卖点:档位决策(成本指标链)+ 可观测桥接(过程效率)。

#### A. 核心必要(5 个)

这 5 个里 3 个是**工程必需**(门 + 成本决策链),2 个是**可观测桥接必需**(过程效率)——正好对应 eval 的两个卖点:删前者 eval 没有档位决策,删后者可观测存的标量没人用。

##### A1. DeterministicEvaluator — 确定性硬门 + 引用可追溯(无 LLM)

`name="deterministic"`,无 LLM 纯正则规则。**评 Hard Gate 机器可判部分 + 引用指标的可计算项**,给 HardGate 提供确定性输入。读 `ctx.report` + `ctx.claim_manifest` + `ctx.run.outcome`。6 个指标:

| 指标 | 怎么评 | 评什么 |
|---|---|---|
| `workflow_completed` | `outcome in ("success","degraded")` → passed=1 | 研究跑完了没(failed/cancelled 不算) |
| `report_non_empty` | `len(report.strip())>0` → passed=1 | 报告非空,最基础完备性 |
| `citation_parse_rate` | 扫 md 链接 `[text](url)` 和 `[n]` 标记;有 `[n]` 但无 md 链接 → 0,否则 1 | 引用标记能不能解析,裸 `[1]` 没对应链接是悬空 |
| `effective_citation_count` | 去重 URL 数 + 0.5×悬空 `[n]` 标记数 | 有效引用数(悬空标记打折算半个) |
| `citation_traceability` | manifest 中有 citation_url 的 claim 比例,≥0.95 过 | claim 级引用可追溯 |
| `unsupported_critical_claim_count` | critical 且无任何 URL 的 claim 数,==0 过 | 关键声明却无引用支撑,有一个就挂 |

**意义**:机器可判的硬指标,不用 LLM。给 HardGate 提供 `workflow_completed`/`report_non_empty`/`citation_traceability`/`unsupported_critical_claim_count` 四个 gate 输入。

##### A2. HardGateEvaluator — 后置聚合门(无 LLM,读 prior_results)

`name="hard_gate"`,无 LLM。**唯一不在装配阶段取数的 evaluator**——读 `ctx.prior_results`(其他 evaluator 已产出的结果)做组合判定。这是"两阶段执行"的具象:runner 阶段1跑完普通 evaluator 把结果塞进 `prior_results`,阶段2 HardGate 再读。

1 个指标 + 失败码:`hard_gate_passed` + `failure_reason_codes`。三类规则:
- **passed==0 触发**:`workflow_failed`(←workflow_completed)/`report_empty`(←report_non_empty)/`dangling_citation`(←citation_traceability)
- **score>0 触发**:`unsupported_critical_claim`(←unsupported_critical_claim_count)
- **judge 的 passed==0 触发,但 None 跳过**:`missing_required_points`(←required_point_coverage)/`critical_fact_error`(←claim_factuality)

`gate_passed = 0 if failures else 1`。回填 `eval_case_run.gate_passed` + `failure_reasons_json`。

**意义**:eval 的"通过/不通过"总判定。删了 `case_run.gate_passed` 列没意义,`cost_per_pass` 分母没了,§17 验收核心能力没了。**口径诚实度**:judge 未运行时(离线无 chat_fn)passed=None 不参与判定,reason 标注"仅基于确定性指标,judge 未运行,离线判定可能偏宽"——不默认通过,明确告诉你这是偏宽判定。

##### A3. CostEffectivenessEvaluator — 成本效率(无 LLM)

`name="cost_effectiveness"`,无 LLM。读 `ctx.run`(research_run + eval_case_run 直链)。2 个指标:

| 指标 | 怎么评 | 评什么 |
|---|---|---|
| `cost_per_pass` | `cost if gate_passed else 0.0`(单 case 视角:gate 通过才算成本) | 通过的成本——gate 没过的研究成本不算"有效产出" |
| `total_cost` | `run.estimated_cost`(eval_case_run 直链) | 本次回放总成本,配对比较的增量成本由 runner 聚合算 |

**意义**:§19 Tier Routing 决策链的"Cost"那一环。没有成本指标,档位决策没法算"边际质量/成本"——eval 存在的工程理由就是回答"升级值不值",这必须有。

##### A4. RoundDeltaEvaluator — 跨轮增量(无 LLM,读可观测标量)

`name="round_delta"`,无 LLM。**唯一真正依赖可观测 `research_span_attribute` 的过程 evaluator**。读 `ctx.review_attributes`(`{round_no:{attr_key:value}}`,来自 span_attribute)+ `review.tokens`(runner 从 `research_stage_usage` 回填)。3 个指标:

| 指标 | 怎么评 | 评什么 |
|---|---|---|
| `quality_delta_per_round` | 取最后两轮,每轮 `_round_quality`=五维评分(`review.score.{coverage,evidence,freshness,sourceDiversity,consistency}`)的**min(短板)**;`delta = cur_q - prev_q` | 多跑一轮质量涨多少(短板木桶原理) |
| `marginal_quality_per_1k_tokens` | `delta / cur_tokens × 1000`(`cur_tokens` 来自 `review.tokens`) | 每千 token 边际质量,效率指标 |
| `gap_closure_rate` | `(prev_gaps - cur_gaps) / prev_gaps`(缺口数减少量占比) | 缺口闭合率 |

**意义**:**可观测桥接的核心卖点**。跨轮增量是 eval 体系最独特的能力——评"多轮动态工作流的边际价值",别家评测系统没有。删了,observability 存的 `review.*` 标量就没用武之地,桥接是空的。单轮直接返回空(至少 2 轮才算),任一轮缺维度分记 None+reason。

##### A5. ReviewerEffectivenessEvaluator — 评审有效性(无 LLM)

`name="reviewer_effectiveness"`,无 LLM。读 `ctx.run`(`reviewer_tokens` + `review_consensus` + `outcome`,均来自可观测投影 + run 行)。2 个指标:

| 指标 | 怎么评 | 评什么 |
|---|---|---|
| `reviewer_token_cost` | `run.reviewer_tokens`(runner 从 `research_stage_usage` 聚合 reviewer stage token) | reviewer 花了多少 token——机制开销 |
| `reviewer_consensus_predictiveness` | `consensus=="report" and outcome in ("success","degraded")` → 1,否则 0 | 评审共识预测准不准(评审说该出报告,最后确实成功收敛) |

**意义**:ULTRA 对抗评审是核心机制,机制消融(reviewer_ablation)靠它判"评审值不值得开"。删了,ULTRA 最独特的机制没法评价。`consensus` 取最后一轮(源头 span_attribute),`outcome` 来自 run 行。注:`reviewer_gap_precision/recall` 需 Reviewer Gap 标注 + 外部 Eval Gap 比对,留作校准期(§17 Phase 6)。

#### B. 支撑必要(4 个,需 chat_fn)

这 4 个都是评测系统的标配维度,但需要 LLM(`chat_fn`),离线跑不了——全量评测启用、离线可选。前 3 个(Citation/Coverage)是 HardGate 的 judge 输入,第 4 个(ReportQuality)是报告"好不好"的语义判断。

##### B1. ClaimExtractorEvaluator — claim 结构化(无 LLM,meta)

`name="claim_extractor"`,无 LLM。本身不产"质量分数",产 manifest 给后面 CitationJudge 用。读 `ctx.report` + `ctx.claim_manifest`(若已有则复用,否则现场 `extract_claims_from_report`)。2 个指标:

| 指标 | 怎么评 | 评什么 |
|---|---|---|
| `critical_claim_count` | manifest 中 `importance=="critical"` 的 claim 数 | 关键声明数量(meta,不判好坏) |
| `supported_claim_count` | 有 citation_url 的 claim 数,`supported==total` 才过 | 有引用支撑的 claim 数 |

**意义**:不产分数但产 manifest 给 CitationJudge 用;离线 replay 路径(report 有但表没 manifest)需要现场抽。**特殊处**:它**会写回 `ctx.claim_manifest`**(`if not manifest: ... ctx.claim_manifest = manifest`),让后面 CitationJudge 复用同一份清单,避免重复抽取。

##### B2. CitationJudgeEvaluator — 引用质量(LLM 语义)

`name="citation_judge"`,LLM-as-judge。把 `claim_manifest`(claim-citation 对,每 claim 取 `claim_text[:200]`+URLs)+ `report[:6000]` 喂 LLM,`temperature=0`,按 instruction 输出 JSON。3 个指标:

| 指标 | 评什么 |
|---|---|
| `claim_factuality` | 关键声明是否属实 |
| `citation_completeness` | 需引用处是否齐全 |
| `citation_correctness` | 引用是否真正支持对应声明 |

**意义**:`claim_factuality` 是 HardGate 的 `critical_fact_error` 输入。引用质量是评测报告的核心维度。Deterministic 只能判"有没有 URL",这个判"URL 支不支持声明""claim 真不真"。judge 失败/不完整时**不默认通过**,标 `not_evaluable`。离线无 chat_fn 时 passed=None 不参与 gate。

##### B3. CoverageJudgeEvaluator — 信息召回(LLM)

`name="coverage_judge"`,LLM-as-judge。把 `report[:8000]` + `dataset_item.required_points_json` + `reference_facts_json` 喂 LLM。2 个指标:

| 指标 | 评什么 |
|---|---|
| `required_point_coverage` | 报告覆盖必须点的比例 |
| `critical_fact_recall` | 关键参考事实是否被准确复述 |

**意义**:`required_point_coverage` 是 HardGate 的 `missing_required_points` 输入。信息召回是评测标配——`required_points` 来自 `eval_dataset_item`(ground truth),是配对回放可比的锚。回答"题目要求的点答到没"。

##### B4. ReportQualityJudgeEvaluator — 报告质量(LLM)

`name="report_quality_judge"`,LLM-as-judge。把 `report[:8000]` + `dataset_item.query_snapshot`(研究 brief)喂 LLM。4 个指标:

| 指标 | 评什么 |
|---|---|
| `analysis_depth` | 分析深度 |
| `multi_source_synthesis` | 多源综合质量 |
| `uncertainty_calibration` | 不确定性是否标注得当 |
| `instruction_following` | 是否遵循题目/格式要求 |

**意义**:报告"好不好"的语义判断。不是 gate 输入,但删了报告质量只剩"引用对不对",缺了"深不深"这一维。覆盖 §7.5(Analysis)+ §7.6(Presentation)分组。

#### 9 个 evaluator 汇总

| 必要性 | evaluator | 指标数 | LLM? | 评价角度 |
|---|---|---|---|---|
| 核心-工程 | Deterministic | 6 | ❌ | 通过性 + 引用可追溯(给 HardGate 确定性输入) |
| 核心-工程 | HardGate | 1+失败码 | ❌ | 总门聚合(读 prior_results) |
| 核心-工程 | CostEffectiveness | 2 | ❌ | 成本效率(§19 Tier Routing 的 Cost 环) |
| 核心-桥接 | RoundDelta | 3 | ❌ | 跨轮增量(读可观测 span_attribute) |
| 核心-桥接 | ReviewerEffectiveness | 2 | ❌ | 评审有效性(读可观测投影) |
| 支撑 | ClaimExtractor | 2 | ❌ | claim 结构化 meta(给 CitationJudge) |
| 支撑 | CitationJudge | 3 | ✅ | 引用质量语义(给 HardGate judge 输入) |
| 支撑 | CoverageJudge | 2 | ✅ | 信息召回(给 HardGate judge 输入) |
| 支撑 | ReportQualityJudge | 4 | ✅ | 报告质量语义 |

**两类评价角度**:① 通过性 + 结果质量(Deterministic/ClaimExtractor/Citation/Coverage/ReportQuality,看产物文本);② 过程效率 + 成本(RoundDelta/ReviewerEffectiveness/CostEffectiveness,看可观测标量+token+成本);HardGate 是总门聚合。**这 9 个覆盖了 eval 的两个核心卖点**:档位决策(成本指标链)+ 可观测桥接(过程效率)。

### 四、LLM-as-judge 实现

`LLMJudgeEvaluator` 基类统一 prompt 模板,LLM 按 metric 列表输出 JSON。`chat_fn` 以 `(system_prompt, user_prompt) -> str` 异步契约注入,**绝不直接 import pipeline**,保持离线可测;`temperature=0`,从 DB `model` 表读 base_url/api_key 构造 OpenAI 兼容调用;judge 失败/不完整时**不默认通过**,标注 `not_evaluable`。

### 五、claim_manifest / ClaimVerifier

`claim_manifest.py` 从最终报告抽"原子 Claim + 引用"对——句切分前先把 URL 屏蔽为占位符(避免 `https://x.com` 里的 `.` 被当句末),识别 Markdown 链接 + 数字标记两类引用,含数值/百分比/URL 的判 `critical`,无引用的句子不进 manifest。`ReportAgent.verify_report_claims` 为每个被验证 claim 落 `claim_verification` artifact。

### 六、6 题 Dataset + 变体

6 题(`evals/datasets/mvp_v1_6questions.json`)覆盖 6 类任务:fact_lookup / tech_comparison / market_analysis / academic_review / trend_forecast / evidence_conflict,每题含 `required_points` + `forbidden_claims` + `original_budget_level`,按 `query_sha256` 幂等灌库。

变体:
- `tier_variants`(MEDIUM/HIGH/ULTRA 三档整体对比)。
- `mechanism_variants` 消融:多轮 Gap-directed、ClaimVerifier、Reviewer Lens 数与多样性等。冻结同一 Evidence/Pre-Verification Report 后对比"开/关某机制",回答 RoundDelta/ReviewerEffectiveness 对应的过程效率问题。

### 七、eval_snapshot

`freeze_candidate_snapshot`:研究完成后**异步**冻结不可变 Candidate Snapshot(指向本次 run 全部可评估产物的索引)。不重复写已落库 artifact、失败绝不阻塞、自引用规避保证幂等——"日常研究 → 可复现 Dataset"的桥梁。

### 八、真实跑通案例

一次真实 ULTRA run(RAG vs Fine-tuning 题),725K input tokens、7 个 claim(4 supported / 3 not_verifiable)、139 个来源;HardGate `failed`(`citation_correctness`=0,CitationJudge 判引用未真正支持声明);RoundDelta 的 `gap_closure_rate`=0 → 诊断"Reviewer 找对问题但报告未用"。研究侧机制指标(非 9 evaluator 产出,为研究流程自身的诊断):Reviewer `gap_recall`=1.0、ClaimVerifier detection precision/recall=1.0、correction_rate=1.0 但 false_warning=6。

### 九、评价方法论:怎么评价 deepresearch agent 的效果

> **核心判断**:agent 效果不是一个分数,是一个**多维 profile**。单看"报告好不好"会被骗(可能花 10 倍 token 才好一点),单看"成本"也会被骗(便宜但漏关键 claim)。所以 9 个 evaluator 实际归到 4 个正交评价角度,每个角度问不同的问题。

#### 9.1 四个评价角度

| 评价角度 | 问什么 | 谁来评 | "好"的标准 |
|---|---|---|---|
| **通过性**(底线) | 这次研究有没有犯不可接受的错 | HardGate + Deterministic | `gate_passed=true`、`outcome=success` |
| **结果质量**(产物) | 报告答没答到、claim 有没有出处、写得好不好 | CoverageJudge / CitationJudge / ReportQualityJudge | required_point 覆盖全、无 dangling citation、结构完整 |
| **过程效率**(花得值不值) | 多轮有没有收敛、reviewer 有没有用、升档值不值 | RoundDelta / ReviewerEffectiveness / CostEffectiveness | `gap_closure` 高、reviewer 预测准、边际质量/token 为正 |
| **机制诊断**(哪个机制有效) | 章节团队/ClaimVerifier/多轮/reviewer 各自贡献多少 | `mechanism_variants` 配对 | 冻结其他条件单关一个机制,看 uplift |

**"好"不是一句 85 分**,是这个 profile:**底线过了没 → 产物质量多高 → 过程效率值不值 → 哪个机制在贡献**。四个角度正交,各自读 EvalContext 里完全不重叠的字段(见第三部分 5.1 表:结果维度读产物表,过程维度读可观测投影 + run 行)。

#### 9.2 三个方法论支柱(缺一评不准)

1. **配对回放,不比均值**——同一题跑 MEDIUM/HIGH/ULTRA,比的是"同题升档差值",不是"日常三档均值"。后者有选择偏差(ULTRA 题本就难),会得出"档位越高越差"的假象。`tier_variants.py` 注释明说:三档回放回答"升级档位是否整体更好",不回答"哪个机制有效"(后者是 `mechanism_variants` 职责)。
2. **ground truth 让结果质量客观**——每题带 `required_points`/`reference_facts`/`forbidden_claims`,CoverageJudge 判"答到没"靠比对 ground truth,不是靠 LLM 主观打分。没有 ground truth,结果类指标没法判——数据集不只是"题目",是"题目 + 标准答案"。
3. **`as_of_date` 时间快照让回放可比**——检索结果随时间变,不冻结时间,今天和下周跑同一题,差异是信息变了不是 agent 变了。`as_of_date` 把信息边界钉死,差异才能归因到 agent。

### 十、迭代闭环:用 eval 结果找 agent 问题并迭代设计

> **eval 的真正价值不是打分,是诊断漏斗**——每层分数能下钻定位到一个具体设计区域。闭环链路:
> **分数差 → `failure_reason_code` → 根因定位 → 改设计 → 冻结数据集重跑配对 → 验证修复**

#### 10.1 第 1 层:HardGate 6 个失败码直接指到 6 个设计区域

HardGate 不止 pass/fail,吐 `failure_reason_codes`——每个码就是一个诊断信号,直接指到该改哪个 agent:

| `failure_reason_code` | 含义 | 根因在哪个 agent 设计 | 怎么改 |
|---|---|---|---|
| `workflow_failed` | `outcome`≠success | pipeline 稳定性 | 超时/重试/降级路径 |
| `report_empty` | 报告为空 | ReportAgent | 报告 fallback 兜底 |
| `dangling_citation` | claim 没出处 | SearchAgent 召回不足 或 claim_manifest 提取断裂 | 加召回 / 修 `claim_manifest` 提取 |
| `unsupported_critical_claim` | 关键 claim 缺证据 | Researcher 对 critical claim 补证不足 | critical claim 强制补证 |
| `missing_required_points` | 必答点没覆盖 | ScopeAgent/Researcher 规划漏维度 | 扩 query、改 scope 澄清 |
| `critical_fact_error` | 关键事实被推翻 | source 质量差 / ULTRA 冲突 reconcile 没触发 | source 过滤 / 冲突 reconcile |

**最直接的闭环**:gate 挂了 → 看码 → 改对应模块。不用猜。

#### 10.2 第 2 层:过程效率分诊断"看不见的浪费"

gate 过了不代表没问题——可能多跑两轮没收敛、reviewer 烧 token 没起作用、升档花 3 倍钱只涨 0.1 质量。这三个 evaluator 专门抓"看不见的浪费":

| evaluator | 异常信号 | 根因 | 怎么改 |
|---|---|---|---|
| RoundDelta | `gap_closure_rate` 低、`quality_delta_per_round`≈0 | 多轮空转:gap 检测没找到真 gap,或 reviewer 一直 continue 不 report | 改 gap 检测逻辑,或对简单题 cap `maxRounds` |
| ReviewerEffectiveness | `reviewer_consensus_predictiveness` 低 | reviewer 委员会没有效转向(该 report 时 split) | 跑 `reviewer_ablation`(single/三同 lens/三不同 lens)找最优配置 |
| CostEffectiveness | `marginal_quality_per_1k_tokens` 在 HIGH→ULTRA 为负 | 该 task_type 升档不值 | 路由到低档 |

#### 10.3 第 3 层:配对差值驱动架构决策

不只修 bug,还要决定"要不要这个机制/档位":

- **tier uplift → 档位路由**:`build_paired_diff_report` 算相邻档位 MEDIUM→HIGH→ULTRA 的质量 uplift + 增量成本。fact_lookup 在 MEDIUM→HIGH uplift≈0 → 永远走 MEDIUM;academic_review 在 HIGH→ULTRA 有正 uplift 且边际划算 → 走 ULTRA。**eval 结果直接做成成本路由表**。
- **mechanism ablation → 机制开关**:`section_team_ablation` 显示章节团队 > 单 ReportAgent → 留;`claim_verifier_ablation` 显示 ClaimVerifier 涨质量少但卡 gate → 调阈值或关掉。**冻结其他条件单关一个机制,uplift 归因干净**。

#### 10.4 第 4 层:score→trace→artifact 下钻到具体那行

光知道"分差"不够,要知道**哪次 agent 调用造成的**。这就是 §18 那条直链(`eval_score.trace_id` + `report_artifact_id`)的价值:`dangling_citation` 失败 → 点 `trace_id` → OTel trace 里看哪个 SearchAgent 调用返回空 → 看 `report_final` artifact 里哪个 claim 没绑 citation。**从"分差"一路下钻到"具体那次调用的那段文本"**。三个 ID(`research_id`/`run_id`/`trace_id`,见 5.2)不是账本,是诊断面包屑。

#### 10.5 第 5 层:冻结数据集重跑 = A/B 验证修复

改完 agent 怎么知道真修好了?**同一份冻结数据集 + 同一个 `as_of_date` 重跑,新旧 agent 做配对差值**。这跟 tier 配对是同一方法论,横轴从"档位"换成"agent 版本"。eval 的"反选择偏差"设计让它**既是评分工具又是迭代工具**——永远比"新 agent 跑冻结题" vs "旧 agent 跑同样的冻结题",不比"今天的 run" vs "昨天的 run"。

#### 10.6 一个完整闭环的例子

拿 dataset 里的 `evidence_conflict`(ULTRA)题跑:

1. **eval 跑完** → HardGate `gate_passed=false`,码=`critical_fact_error`;CoverageJudge `critical_fact_recall` 低。
2. **诊断** → 关键事实被推翻,冲突没 reconcile。`trace_id` 下钻 → 看到 Researcher 取了两个口径冲突的来源,ULTRA 冲突 reconcile 没触发。
3. **改设计** → 修冲突 reconcile 触发条件(或加 source 质量过滤先挡掉一边)。
4. **验证** → 冻结数据集 + `as_of_date` 重跑 → `critical_fact_error` 消失、`critical_fact_recall` 升 → 配对差值确认 uplift,修复有效。

整个过程每一步都有 eval 信号在指路,不靠人猜。**eval 存在的意义:把"agent 好不好"从主观印象,变成"分数 → 失败码 → 根因 → 改 → 配对验证"的可复现闭环。**

---

## 第三部分:Eval 数据来源与 EvalContext 字段速查

> 整理时间:2026-07-27
> 源码基准:`base.py:22-56`(EvalContext 字段)、`runner.py:117-298`(`_load_case_context` 装配)、`models.py`(10 张表 ORM)、`eval_repository.py:350-507`(llm_call/stage_usage 投影与对账)。

### 一、可观测存的表(表名 + 列 + 作用)

可观测往 MySQL 落 **2 张表**,判定标准是"写入入口在 observability 层 / 落库逻辑是『从 trace 抄下来』"。

#### 1. `research_span_attribute` —— 动态决策标量(observability 双写)

**作用**:把"只在 span 流过那一刻存在"的决策标量抄一份留库。span 是临时对象,出 `async with` 块就 end,不抄走就只剩 Langfuse 云上那份,应用侧离线查不到。observability 在导出 Langfuse 的同时 `upsert_span_attributes` 双写本表。和 `research_artifact` 严格分工:artifact 存产出全文,本表只存标量,同一份数据不两处重复落库。

**列**(ORM `ResearchSpanAttribute`,`models.py:298`):

| 列 | 类型 | 描述 |
|---|---|---|
| `id` | String(32) PK | 主键 |
| `run_id` | String(32), index | 哪次执行(切片主键) |
| `research_id` | String(32), index | 哪个研究(跨 attempt 聚合用) |
| `trace_id` | String(64), index | 哪条 trace(可观测给) |
| `span_scope` | String(64) | 哪个 span 写的:`UltraDynamicReview` / `UltraReportGate` |
| `round_no` | Integer | 哪一轮(质量门为 0) |
| `attr_key` | String(96) | 属性名,如 `review.consensus` |
| `attr_value_num` | Numeric(20,4) | 数值类值(票数/评分/缺口数) |
| `attr_value_str` | String(512) | 字符串类值(consensus/status) |
| `attr_value_json` | Text | JSON 类值(缺口列表等) |
| `create_time` | DateTime | |

**幂等键** `(run_id, span_scope, round_no, attr_key)`,replay 时 `ON DUPLICATE KEY UPDATE` 覆盖。nullable 的 `round_no` 在 UNIQUE 里会破坏去重,落库前归一为 0(否则 no-round artifact 如 report_gate 的 replay 会插重复行)。

#### 2. `research_stage_usage` —— 阶段级 token 聚合(observability 投影)

**作用**:把细碎 per-call token 按 7 维切片聚合成 per-stage/per-round/per-section,eval 不用自己 group by。**只是投影,不是另一份事实源**——`research_llm_call` 才是事实源,本表为查询方便建。`record_llm_call` 用显式存在性检查区分 insert/update,**仅新插入时累加**本表,避免 replay 重复计费。

**列**(ORM `ResearchStageUsage`,`models.py:363`):

| 列 | 类型 | 描述 |
|---|---|---|
| `id` | BigInt PK 自增 | 主键 |
| `run_id` | String(32), index | 哪次执行 |
| `stage_name` | String(128) | 哪个阶段,如 `UltraDynamicReviewer:coverage` |
| `agent_name` | String(128) | 哪个 agent |
| `round_no` | Integer | 哪一轮 |
| `report_phase` | String(32) | 报告哪步:`merge`/`section_draft`/`judge` |
| `reviewer_lens` | String(64) | 哪个 reviewer 视角:`coverage`/`freshness` |
| `section_id` | String(128) | 哪个章节 |
| `request_count` | Integer | 该聚合下调用次数 |
| `retry_count` | Integer | 重试次数 |
| `input_tokens` / `output_tokens` | BigInt | 该聚合下 token 合计 |
| `duration_ms` | BigInt | 该聚合下耗时合计 |
| `outcome` | String(32) | 成功/失败/降级 |
| `create_time` / `update_time` | DateTime | |

**幂等键** `(run_id, stage_name, agent_name, round_no, report_phase, reviewer_lens, section_id)`,nullable 文本列归一为空串避免 MySQL UNIQUE 多 NULL 不去重的问题。

### 二、非可观测存的表(eval 也读)

eval 数据来源里其余 8 张表**不来自可观测**,分两类:

#### A. 业务产物(4 张,研究在线写,eval 离线读)

| 表 | 关键列 | 作用 |
|---|---|---|
| `research_run` | `id`(PK)/ `research_id` / `attempt_no` / `trace_id` / `outcome` / `workflow_mode` / `budget_level` / `input_tokens` / `output_tokens` / `active_duration_ms` / 各 version sha | 一次连续后台执行的总账(一维):结局、总 token、耗时、trace_id、版本。pipeline `_close_run` 写。eval 读 outcome/总量/trace_id |
| `research_artifact` | `id`(PK)/ `run_id` / `artifact_type` / `round_no` / `section_id` / `angle` / `content`(MEDIUMTEXT) / `content_sha256` / `metadata_json` | 所有可复现产物全文(报告/证据/来源/draft/section_draft/revision/merged/synthesis),按 6 列幂等。eval 分类装配 report/draft/section/sources |
| `research_claim_manifest` | `id`(PK)/ `run_id` / `report_artifact_id` / `claim_id` / `claim_text` / `importance` / `citation_id` / `citation_url` / `citation_excerpt` | claim-citation 清单,一行一对。`ReportAgent.run` 收口调 `write_claim_manifest` 写 |
| `research_llm_call` | `id`(PK)/ `run_id` / `stage_name` / `agent_name` / `round_no` / `report_phase` / `reviewer_lens` / `section_id` / `input_tokens` / `output_tokens` / `outcome` | **Token 单一事实源**,PK 去重 replay。**eval 不直接读**——它供 `research_stage_usage` reconcile 对账用 |

#### B. eval 数据层(4 张,eval 自己写自己读)

| 表 | 关键列 | 作用 |
|---|---|---|
| `eval_dataset_item` | `id`(PK)/ `dataset_name`+`dataset_version` / `query_snapshot` / `query_sha256` / `task_type` / `required_points_json` / `reference_facts_json` / `forbidden_claims_json` / `original_budget_level` | 脱敏版本化题目,"必须答到哪些点"的 ground truth。`seed_dataset` 灌库,按 `query_sha256` 去重 |
| `eval_experiment` | `id`(PK)/ `name` / `dataset_name`+`dataset_version` / `experiment_type` / `evaluator_version` / `judge_model` / `status` | 实验定义(tier_comparison / *_ablation) |
| `eval_case_run` | `id`(PK)/ `experiment_id` / `dataset_item_id` / `run_id` / `variant_name` / `repeat_no` / `gate_passed` / `estimated_cost` | 单次回放:experiment × dataset_item × variant × repeat,关联回真实 `run_id`。唯一键 4 列 |
| `eval_score` | `id`(PK)/ `case_run_id` / `metric_name` / `metric_group` / `score_value` / `passed` / `evaluator_name`+`evaluator_version` / `judge_model` / `reason` / `trace_id` / `report_artifact_id` | 通用分数,唯一键 `(case_run_id, metric_name, evaluator_version)`。带 `trace_id`+`report_artifact_id` §18 直链 |

**关键澄清**:
- `research_llm_call` 是"每次 LLM 调用"的事实源,但 **eval 不直接读它**——eval 读 token 只走 `research_stage_usage`(投影)+ `research_run`(总量)。
- `research_run.trace_id` 这一列**是可观测写的**(observability 开 trace 时生成),但 `research_run` 这张表整体是业务产物。所以"某列来自可观测"≠"这张表来自可观测"。
- eval 与可观测的**唯一直连字段是 `trace_id`**:`research_run.trace_id`(可观测写)→ `eval_score.trace_id`(§18 直链回填),从分数一跳直达 trace。

### 三、EvalContext 的内容(字段 + 来源)

`EvalContext`(`base.py:22-56`)16 个字段,由 `_load_case_context`(`runner.py:117-298`)装配,evaluator 只读不改。分 5 类:

#### ① 结果产物类(8 字段,业务产物)

| # | 字段 | 类型 | 存什么 | 来源(表·列) | 来自可观测? |
|---|---|---|---|---|---|
| 1 | `case_run_id` | str | 本次评估标识 | `eval_case_run.id`(参数传入) | ❌ |
| 2 | `report` | str | 最终报告 Markdown | `research_artifact`(type=report_final).content | ❌ |
| 3 | `merged_report` | str | merged 正文(区别于 report_final) | `research_artifact`(type=report_merged).content | ❌ |
| 4 | `report_drafts` | list | HIGH 双 draft [{angle,content,round_no}] | `research_artifact`(type=report_draft) | ❌ |
| 5 | `report_synthesis` | str | HIGH synthesis | `research_artifact`(type=report_synthesis).content | ❌ |
| 6 | `section_artifacts` | dict | 章节团队 {section_id:{draft,revision}} | `research_artifact`(type=report_section_draft/revision) | ❌ |
| 7 | `claim_manifest` | list | claim-citation 清单 [{claim_id,claim_text,importance,citations}] | `research_claim_manifest` | ❌ |
| 8 | `sources` | list | 来源快照 [{url,title,score,round_no}] | `research_artifact`(type=source_snapshot).metadata_json | ❌ |

#### ② 任务基准类(1 字段,eval 数据层)

| # | 字段 | 类型 | 存什么 | 来源 | 来自可观测? |
|---|---|---|---|---|---|
| 9 | `dataset_item` | dict | "必须答到哪些点" ground truth {query_snapshot,required_points_json,reference_facts_json} | `eval_dataset_item` | ❌ |

#### ③ 过程决策标量类(3 字段,✅ 来自可观测)

| # | 字段 | 类型 | 存什么 | 来源 | 来自可观测? |
|---|---|---|---|---|---|
| 10 | `review_attributes` | dict{round_no:{key:value}} | 每轮评审标量:consensus/votes/五维分/gaps/tokens | `research_span_attribute`(span_scope=UltraDynamicReview)+ `review.tokens` 从 `research_stage_usage` 回填 | ✅ |
| 11 | `report_quality` | dict | 报告质量门摘要 {status,weak_sections,...} | `research_span_attribute`(span_scope=UltraReportGate) | ✅ |
| 12 | `reviewer_lenses` | list | 去重排序的 lens(coverage/freshness...) | `research_stage_usage`(stage_name like 'UltraDynamicReviewer%')lens 聚合 | ✅ |
| — | `round_no` | int\|None | 机制维度(可选) | **不装配**,默认 None | — |

#### ④ 运行级聚合类(2 字段,混合来源)

`run` 是杂烩 dict,单独拆:

| run 内的 key | 存什么 | 来源 | 来自可观测? |
|---|---|---|---|
| `outcome` / `budget_level` | run 结局/预算档 | `research_run` | ❌ |
| `input_tokens` / `output_tokens` | run 级总 token | `research_run` | ❌ |
| `duration_ms` | 活跃耗时 | `research_run.active_duration_ms` | ❌ |
| `trace_id` | OTel trace 全链路标识 | `research_run.trace_id`(observability 写) | ✅ |
| `estimated_cost` | 本次回放成本 | `eval_case_run.estimated_cost` | ❌ |
| `gate_passed` | HardGate 结论 | `eval_case_run.gate_passed` | ❌ |
| `reviewer_tokens` | reviewer 总 token | 装配聚合(从 `research_stage_usage` 算) | ✅ |
| `reviewer_lenses` | lens 列表(也存顶层 #12) | 装配聚合 | ✅ |
| `review_consensus` | 最后一轮共识 | 取 `review_attributes` 最后一轮的 `review.consensus`(源头 span_attribute) | ✅ |
| `report_artifact_id` | report_final artifact id | `research_artifact`(type=report_final).id | ❌ |

| # | 字段 | 类型 | 存什么 | 来源 | 来自可观测? |
|---|---|---|---|---|---|
| 13 | `run` | dict(见上表) | run 级聚合 + §18 直链 | `research_run` + `eval_case_run` + 可观测投影 + 装配派生 | 部分✅ |
| 14 | `artifact_counts` | dict{type→count} | 产物类型计数 | `research_artifact` 全量统计 | ❌ |

#### ⑤ 跨 evaluator 通信类(1 字段,eval 运行时)

| # | 字段 | 类型 | 存什么 | 来源 | 来自可观测? |
|---|---|---|---|---|---|
| 15 | `prior_results` | dict{metric_name→MetricResult} | 其他 evaluator 已产出结果 | **不在装配阶段填**,runner 阶段1跑完后填充(`runner.py:346`),HardGate 后置只读 | ❌ |

**两个特殊字段说明**:
- `round_no`(③ 类尾):`_load_case_context` 返回的 `EvalContext(...)` 调用里没传这个参数(`runner.py:283-298`),恒为 None。evaluator 实际都从 `review_attributes` 的 key 取 round_no。
- `prior_results`(⑤ 类):唯一不在装配阶段填的字段。runner 在 `evaluate_case_run` 阶段1跑每个普通 evaluator 时 `ctx.prior_results[r.metric_name] = r` 逐步塞,阶段2 HardGate 再读它做组合判定——这是"两阶段执行"设计的具象。

### 四、文字概括性总结

EvalContext 是 eval 的数据消费接口,本质是**一次 case_run 的多路反查装配**:从 5 张 runtime 表(`research_run` / `research_artifact` / `research_claim_manifest` / `research_span_attribute` / `research_stage_usage`,外加 eval 不读的 `research_llm_call`)和 2 张 eval 表(`eval_case_run` / `eval_dataset_item`)反查,把分散的行拼成 evaluator 能直接读的单一上下文对象。16 个字段按来源分 5 类:8 个结果产物(报告/claim/draft/来源)、1 个任务基准(必须点)、3 个过程标量(评审投票/质量门/lens)、1 个运行聚合 dict + 1 个产物计数、1 个跨 evaluator 通信槽。

这其中**真正来自可观测的只有 3 个顶层字段**(`review_attributes` / `report_quality` / `reviewer_lenses`)+ `run` dict 内部 3 个 key(`trace_id` / `reviewer_tokens` / `review_consensus`)。这印证了 eval 与可观测的桥接本质:**eval 不直接评估 trace,而是评估可观测从 trace 里抄下来、被 runner 拼装好的切片维度**。可观测埋什么,eval 才能评估什么过程指标——埋了 `review.consensus`/`votes`/`scores`/`gaps`,才有跨轮增量;埋了 `UltraDynamicReviewer` stage 的 token,才有 `reviewer_token_cost`;没埋的维度,eval 评不了。

这也解释了为什么 `research_llm_call` 是 token 单一事实源却**不被 eval 直接读**:eval 要的不是"每次调用"的明细,而是"按维度切片聚合好"的投影——那正是 `research_stage_usage` 的职责。eval 读聚合投影、读 run 行总量、读决策标量,三者分工不重叠:结果类指标读产物表,过程类指标读可观测投影表,成本类指标读 run 行 + case_run 直链。装配器 `_load_case_context` 把这几类数据按 `run_id` 主枢纽反查 JOIN,拼出 EvalContext,evaluator 各取所需——这就是 eval 数据流的全部。

### 五、Eval 从结果上、过程上评价什么 + 三 ID 关系

#### 5.1 结果维度 vs 过程维度(评价什么、思路是什么)

eval 对一条 case_run 同时从两个**正交维度**打分,它们读的 EvalContext 字段完全不重叠:

| 维度 | 评价什么 | 读哪些 EvalContext 字段(来源表) | 典型指标 |
|---|---|---|---|
| **结果** | 报告好不好(产物质量) | `report` / `merged_report` / `claim_manifest` / `sources` / `section_artifacts` / `report_drafts` / `dataset_item`(均来自 `research_artifact` + `research_claim_manifest` + `eval_dataset_item`) | 引用可追溯性、有效引用数、未支持 critical claim 数、必须点覆盖、关键事实召回、报告质量(分析深度/多源综合/不确定性校准) |
| **过程** | 这次研究跑得值不值(决策与成本效率) | `review_attributes` / `report_quality` / `reviewer_lenses` + `run` 内 `reviewer_tokens`/`review_consensus`/`estimated_cost`/`gate_passed`/`trace_id`(均来自可观测投影 + `research_run` + `eval_case_run`) | 跨轮质量增量、每千 token 边际质量、缺口闭合率、Reviewer token 成本、Reviewer 共识预测性、成本/通过 |

**思路**:
- **结果类**只看"最终产物"——报告正文、claim-citation 清单、来源、draft/merge 文本。它回答"报告引用可追溯吗、必须点覆盖了吗、关键 claim 有 URL 吗"。输入只来自产物表,不看 trace。
- **过程类**只看"trace 里抄下来的决策标量 + token"——评审投票/共识/五维分/缺口数、报告质量门、reviewer per-round token。它回答"多跑一轮值吗、评审 token 花得有效吗、成本/gate 比如何"。输入只来自可观测投影表 + run 行,不看报告正文。
- **两者协同**:配对差值时,结果指标看"升档质量涨多少",过程指标看"升档边际质量/成本是多少",拼出 Task Complexity → Quality Uplift → Cost → Tier Routing 决策链——比如"复杂题在升档上有正 uplift 且边际划算所以路由高档,简单题被低档支配所以路由低档"。

#### 5.2 `run_id` / `research_id` / `trace_id` 三者关系

这三个字段名字像、都在多表冗余,但**语义、生命周期、粒度完全不同**:

| 字段 | 是什么 | 谁生成 | 生命周期 | 粒度 |
|---|---|---|---|---|
| `research_id` | 一个**用户研究问题**的标识 | 用户发起新研究时生成 | 跨多次 attempt/retry/resume 恒定 | 1 研究 = 1 个 |
| `run_id` | 一次**连续后台执行**的标识 | 每次 `_run_now` 新建 | 每次 attempt/retry/HITL 恢复都新建 | 1 research_id = N 个 run_id |
| `trace_id` | 这次 run 的 **OTel trace 全链路标识** | observability 开 trace 时生成 | 跟 run_id 一对一 | 1 run_id = 1 个 trace_id |

**层级关系**:`research_id (1) → run_id (N) → trace_id (1:1)`。一个研究多个 run,一个 run 一个 trace。

**为什么三者在多表冗余存**(查询模式不同):
- 按 `run_id` JOIN——查"这次回放的产物"(产物都钉在具体那次执行上)。
- 按 `research_id` JOIN——查"这个研究的所有产物(跨 attempt)"(HITL 重试后 report_final 可能在 attempt2、user_query 在 attempt1,要跨 run 取)。
- 按 `trace_id` JOIN——从 eval_score 一跳直达 trace(§18 直链,避免 score→case_run→run→trace 多跳)。

**eval 流程里怎么串**:`eval_case_run.run_id` → `research_run`(拿 research_id + trace_id + outcome + 总 token)→ 按 run_id 反查 4 张产物/标量表;`eval_score.trace_id` 直接回链 trace,`eval_score.report_artifact_id` 直接回链 report_final artifact。`run_id` 是连在线研究产物的总枢纽,`trace_id` 是连可观测的唯一直连字段,`research_id` 是跨 run 聚合的伞。

**一个易错点**:HITL 批准会 mint 新 run,所以同一 research_id 下 COMPLETED 的那个 run 不是第一个 run(第一个停在 hitl_wait)。eval 配对回放钉的是**最后那个 COMPLETED 的 run**,跨 run 查产物时必须按 `attempt_no` 排序取终态行。

---

## 第四部分:可观测 ↔ Eval 的桥接实质

eval 不直接评估 trace 本身(trace 长什么样归 Langfuse 管),而是评估"可观测从 trace 里抄下来的、和成本/质量相关的切片维度":

1. **trace_id 作反查锚点**:每个 `eval_score` 带 `trace_id` + `report_artifact_id`,分数能一键跳到 trace 看执行过程。
2. **token 切片做成本评估**:eval 直接读可观测存的 token(`research_llm_call` + `research_stage_usage`),算成本收益(`total_cost`/`cost_per_pass`)和边际质量(`marginal_quality_per_1k_tokens` 分母)、机制开销(`reviewer_token_cost`)。
3. **决策标量做机制评估**:读 `research_span_attribute` 算跨轮增量、证据充分性切片、Reviewer 预测准确性。

**因果链**:
1. 工作流是棵四层树(`workflow→stage→model/tool`),表达阶段、轮次、并行结构。
2. 共享 OTel Provider 让框架内部 span 自动成为业务 span 子节点,四层是真父子链不是事后拼。
3. 业务决策维度(评审投票/五维评分/质量门)埋进 span,把动态决策从黑盒变 trace 一等可观测维度。
4. 落三张表(`research_llm_call` 存 token+trace 切片、`research_stage_usage` 存聚合投影、`research_span_attribute` 存决策标量),eval 直接读现成的。

---

## 第五部分:简历精简版

### 可观测性链路(简历用)

**段落版**:
> 基于 OpenTelemetry 设计 `workflow→stage→model/tool` 四层 span 链路,让应用层与 AgentScope `TracingMiddleware` 共享全局 `TracerProvider`,实现框架原生 span 与业务 span 的真父子贯通(而非事后拼 trace_id),经 OTLP 导出 Langfuse。对 ULTRA 动态工作流做 M1–M5 改造,把对抗评审决策(投票/共识/五维评分)与报告质量门从黑盒变 trace 一等维度,并设计 observability↔eval 桥接,埋点还暴露并修复了章节团队 1406 静默回退 bug。

**Bullet 版(挑 3-4 条)**:
- 基于 OpenTelemetry 设计 `workflow→stage→model/tool` 四层 span 链路,应用层与 AgentScope `TracingMiddleware` 共享全局 `TracerProvider` 实现四层贯通,OTLP/HTTP 导出 Langfuse
- 对 ULTRA 动态工作流做 M1–M5 可观测改造:解开 LLM 角色/轮次塌缩、把对抗评审决策(投票/共识/五维评分)和报告质量门从黑盒变 trace 一等维度
- 设计 observability↔eval 桥接:决策标量双写 Langfuse + DB,`llm_attribution` 把每次 LLM 调用归因到 `report_phase`/`reviewer_lens`/`round_no`/`section_id`,支持按章节/轮次切片做成本与质量增量分析
- 埋点暴露并修复章节报告团队因 `TEXT` 列 64KB 上限导致的 1406 静默回退 bug;坚持低基数属性 + 默认不采 I/O(脱敏截断 + `NonRecordingSpan` 零成本降级)

### Eval 评测系统(简历用)

**段落版**:
> 从 0 设计实现 LLM 评测系统:运行事实落库→异步 Snapshot 冻结→版本化 Dataset 配对回放→9 个 evaluator 打分→配对差异决策,10 张 MySQL 表实现 Token 单一事实源去重对账与 score→trace→artifact 全链路反查。9 个 evaluator(6 确定性 + 3 LLM-as-judge)以同题配对回放解决选择偏差,输出 Task Complexity→Quality Uplift→Cost→Tier Routing 决策链,把 eval 做成「分数→失败码→根因→改→验证」迭代漏斗。

**Bullet 版(挑 3-4 条)**:
- 从 0 设计 LLM 评测系统:运行事实落库 → 异步 Snapshot 冻结 → 版化 Dataset 配对回放 → 9 个 evaluator 打分 → 配对差异决策报告,10 张 MySQL 表实现 Token 单一事实源去重对账 + score→trace→artifact 全链路反查
- 6 个确定性 evaluator + 3 个 LLM-as-judge evaluator,用真实 LLM(temperature=0、不 mock)判 claim-citation 对;机制消融变体(多轮 / ClaimVerifier / Reviewer Lens)+ 6 题分层 Dataset 支持三档配对回放
- 把 eval 当成 agent 迭代漏斗而非打分器:HardGate 6 个 `failure_reason_code` 直接定位到 6 个 agent 设计区域,过程效率分(RoundDelta/ReviewerEffectiveness/CostEffectiveness)诊断多轮空转、reviewer 无效转向、升档负边际,配对差值驱动档位路由与机制开关,冻结数据集重跑做 A/B 验证——形成「分数→失败码→根因→改→配对验证」可复现闭环
- 解决选择偏差问题:档位结论必须来自同 Dataset Item 配对回放而非日常均值,输出 Task Complexity → Quality Uplift → Incremental Cost → Tier Routing 决策链路;工程亮点含两阶段 evaluator 编排(HardGate 后置聚合)、MySQL UNIQUE NULL 幂等归一化、judge 缺失标注「离线偏宽」不默认通过
