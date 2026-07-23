# Deep Research Eval 单题端到端 MVP — 实现设计

> 本文是 `docs/deep-research-eval-mvp-single-case.md`（规格）的实现设计。规格是事实来源；
> 本文档把规格落实成可执行的文件结构、数据流、evaluator 逻辑、CLI 与测试设计，并记录
> 实现期对规格的若干确认与调整。

## 0. 关键决策（与用户确认）

| # | 决策 | 说明 |
|---|---|---|
| 1 | 完全按规格做 | 全新 `mvp_*.py` 文件，`MvpEvalContext` 用规格字段名，5 个 evaluator，离线 Fixture，`python -m evals.mvp_single_case` CLI，JSON+Markdown 报告。不并入现有 v2 框架的 DB/runner 链路。 |
| 2 | Claim 支持状态判定接真实 LLM | 5 个 evaluator 里只有 Claim 一个调 LLM。复用现有 `ChatFn` 类型别名签名 `Callable[[str, str], Awaitable[str]]`。 |
| 3 | 模型配置从 DB model 表读，CLI 传 `--model-id` | 连 MySQL 查 `model` 表那条记录的 `base_url/api_key/model`，构造 OpenAI 兼容客户端。不碰 agentscope / `model_handler`。 |
| 4 | 取不到 model 记录或 key 为空 → 报错退出 | 不退回 gold。明确报错指引。 |
| 5 | 其余 4 个 evaluator 规则比对、读 Fixture，不调 LLM | Intent / Review / Consistency / ClaimVerifier 全部确定性逻辑。 |
| 6 | Fixture 按 6 个预置问题设计 | gold 标注（`gold_support` 等）仅用于端到端测试断言，**不喂运行时**；运行时 Claim 判定走真模型。 |

**对规格验收第 11 条的有意覆盖（已确认）：**

> 原文：不依赖数据库、Tavily 或真实 LLM。
>
> 调整为：不依赖 Tavily、不重新跑 research pipeline、不依赖 eval 业务表（`eval_score` 等）；
> 但**可以连 DB 的 model 表读模型配置**，**可以调真实 LLM 判 claim**。Fixture 仍是离线预置产物，
> 5 个 evaluator 里只有 Claim 一个调 LLM。

## 1. 文件清单与职责

完全按规格第 11 节的 6 个新增文件：

```
backend-python/evals/
├─ fixtures/mvp_single_case.json   # 离线 Fixture（Task Spec + 6 预置问题 + gold 标注）
├─ mvp_context.py                  # MvpEvalContext + build_context + completeness check
├─ mvp_evaluators.py               # 5 个 evaluator：Intent/Review/Claim/Consistency/ClaimVerifier
├─ mvp_single_case.py              # CLI 入口 (__main__)
├─ mvp_report.py                   # JSON 序列化 + Markdown 渲染
└─ mvp_output/.gitkeep             # 输出目录
```

**与现有 eval 框架的对齐点（结合项目现有 eval 做法，但不改规格形态）：**

- 5 个 evaluator 产出复用现有 `MetricResult`（`evals/schemas.py`）作为分数契约，不发明新结构。
- Claim evaluator 复用现有 `ChatFn` 类型别名签名与 `parse_json_safe` 工具。
- 5 个 evaluator **不继承** `BaseEvaluator` ABC——该 ABC 的 `evaluate(ctx: EvalContext)` 绑定的是现有 `EvalContext`，而规格的 `MvpEvalContext` 字段集不同（多了 `intent/plan/review/rounds/reports/claim_verifier/gold/completeness`）。为让 evaluator 拿到规格字段，它们直接接收 `MvpEvalContext`。这是"完全按规格做"的必然结果。
- evaluator 内部为各自定义 `async def evaluate(ctx: MvpEvalContext, *, chat_fn=None) -> list[MetricResult]`（仅 Claim 用 `chat_fn`）。

## 2. MvpEvalContext 与 completeness check

### 2.1 MvpEvalContext（`mvp_context.py`）

字段完全按规格第 3 节：

```python
@dataclass
class MvpEvalContext:
    case: dict[str, Any]            # Query, Required Points, Critical Facts, constraints
    run: dict[str, Any]             # Run ID, status, tokens, latency, version
    intent: dict[str, Any]          # scope goals/constraints/routing
    plan: dict[str, Any]            # Plan, Work Item, priority, status
    tool_calls: list[dict[str, Any]]
    context_nodes: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    review: dict[str, Any]          # Gap, score, nextAction
    rounds: list[dict[str, Any]]
    reports: dict[str, str]         # consistency/verifier pre/post + Final
    claims: list[dict[str, Any]]
    claim_verifier: list[dict[str, Any]]
    gold: dict[str, Any]
    completeness: dict[str, Any]    # 由 builder 填充
```

### 2.2 build_context

执行顺序（规格第 3 节）：

```
读取 Fixture
→ 读取 Task Spec
→ 读取 Run
→ 读取 Intent、Plan、Tool、Round、Review
→ 读取 L0/L1/L2、Source、Evidence
→ 读取 Reports、Claims、Verifier
→ 建立 Claim→Evidence→Source、Gap→Round 关联
→ 执行 Context Completeness Check
```

### 2.3 check_completeness

输出（规格第 3 节）：

```json
{
  "case_available": true,
  "intent_available": true,
  "review_available": true,
  "claims_available": true,
  "evidence_available": true,
  "consistency_pre_post_available": true,
  "verifier_pre_post_available": true,
  "missing": [],
  "evaluable": true
}
```

缺失字段时相关指标标 `not_evaluable`，不默认通过。

## 3. Fixture 结构（`fixtures/mvp_single_case.json`）

顶层结构：

```json
{
  "case":            { /* 规格第2节 Task Spec 原文 */ },
  "run":             { "run_id", "status", "input_tokens", "output_tokens", "duration_ms", "workflow_version" },
  "intent":          { "task_type", "language", "require_citations", "audience", "required_points", "constraints": {"security": false}, "routing" },
  "plan":            { "work_items": [{"id","title","priority","status"}], "priorities", "status" },
  "tool_calls":      [ {tool, params, result, error, retry} x N ],
  "context_nodes":   [ {level:"L0|L1|L2", path, content} x N ],
  "sources":         [ {url, source_type, fetched_at, snapshot} x N ],
  "evidence":        [ {evidence_id, evidence_text, claim, source_id, strength} x N ],
  "review":          { "blocking_gaps": ["security"], "score", "next_action" },
  "rounds":          [ {round_no, new_sources, new_evidence, gaps, tokens} ... 第二轮含新增安全 evidence ],
  "reports":         { "pre_consistency", "consistency_messages", "post_consistency", "pre_verification", "post_verification", "final" },
  "claims":          [ {claim_id, claim_text, importance:"critical|minor", requires_citation, citations:[{citation_id, evidence_id, excerpt}]} x 3 ],
  "claim_verifier":  [ {claim_id, verdict:"verified|unverified", reason, post_action} ... ],
  "gold":            { "gold_support": {claim_id: "supported|unsupported|contradicted|partially_supported|not_verifiable"}, "expected_missing_constraints": ["security"], "expected_unsupported_claim": "claim_xxx" },
  "completeness":    { /* builder 填充，Fixture 可省略 */ }
}
```

### 6 个预置问题在 Fixture 上的落点（规格第 2 节逐条对齐）

1. **Intent 漏掉安全约束** → `intent.constraints.security = false`，而 `case.required_points` 含 `security`。Intent evaluator 对比出 recall 缺失。
2. **Plan 规划了安全任务，但最终报告未使用安全 Evidence** → `plan.work_items` 含 `security`，`evidence` 含安全 evidence（带 source_id），但 `reports.final` 正文不含该 evidence 的 claim/citation。
3. **Reviewer 正确发现安全 Gap，下一轮新增安全 Evidence** → `review.blocking_gaps=["security"]`，`rounds[1].new_evidence` 含安全 evidence。
4. **最终报告包含一个 Unsupported Claim** → `claims` 中一条 `importance: "critical"`，其 `citations` 指向的 evidence 不支持该 claim。gold 标 `unsupported`。
5. **Consistency 前有跨章节矛盾，后报告消除** → `reports.pre_consistency` 含矛盾，`reports.post_consistency` 消除。
6. **ClaimVerifier 正确发现并标记 Unsupported Claim** → `claim_verifier` 对应该条 `verdict = "unverified"`，`post_action = "disclosed|removed|revised"`。

### gold 的定位（规格第 2 节末句）

MVP 校准参照，生产不得把 Agent 自己的判断当真值。运行时 Claim 判定走真模型，`gold.gold_support`
**仅用于端到端测试的断言校验**（验收第 12 条），不参与运行时路径。

## 4. 5 个 evaluator（`mvp_evaluators.py`）

均产出 `list[MetricResult]`，按规格固定顺序执行。只 Claim 调 LLM。

| # | evaluator | 输入（来自 ctx） | 逻辑（规格对应节） | 输出指标 |
|---|---|---|---|---|
| 1 | **Intent** | `case.required_points`、`case.explicit_constraints`、`intent` | 比对任务类型/语言/受众/引用要求、required_points 遗漏、错误增加限制、路由 | `constraint_precision`、`constraint_recall`、`missing_constraints`、`routing_accuracy`、`passed` |
| 2 | **Review** | `review.blocking_gaps`、`review.next_action`、`rounds`、`case.required_points`、`reports.final` | gap 是否等于外部缺失项、下一轮是否建 work item、是否产生 evidence、最终是否关闭 gap、token 后质量提升 | `gap_precision`、`gap_recall`、`gap_closure_rate`、`new_evidence_count`、`quality_delta`、`reviewer_token_cost`、`finding` |
| 3 | **Claim** | `claims`、`evidence`、`sources`、`reports.final` | 逐 claim：需不需要引用、有无 citation、citation↔evidence 映射（确定性规则）、evidence 是否支持 claim（**LLM 判**）、是否 critical | `total_claims`、`supported/partially/unsupported/contradicted_claims`、`citation_completeness`、`citation_correctness`、`unsupported_critical_claim_count` |
| 4 | **Consistency** | `reports.pre_consistency`、`reports.consistency_messages`、`reports.post_consistency` | before/after 矛盾数、解决数、claim/citation 保留率、新回归 | `issues_reported`、`issues_resolved`、`contradictions_before/after`、`claim_retention`、`citation_retention`、`new_regressions` |
| 5 | **ClaimVerifier** | `claims`、`claim_verifier`、`reports.pre/post_verification` | 是否发现预置 unsupported claim、verdict 是否正确、后报告是否披露/删除/修正、是否误删正确 claim | `checked_claims`、`unsupported_detection_precision/recall`、`claim_correction_rate`、`false_warning_count`、`coverage_regression` |

### Claim evaluator 的 LLM 调用细节

- 对每个 claim，构造 system+user prompt（含 claim_text、对应 evidence 文本、source 摘要、context），让 LLM 输出 JSON `{verdict: "supported|partially_supported|unsupported|contradicted|not_verifiable", reason}`，用现有 `parse_json_safe` 解析。
- `citation↔evidence` 映射是确定性规则（不调 LLM）：claim.citations[].evidence_id → evidence.evidence_id。
- LLM 调用容错分两阶段，勿混淆：
  - **启动期**（决策 4）：`--model-id` 取不到 model 记录或 `api_key` 为空 → 直接报错退出，不进入 evaluator。
  - **运行期**：已拿到有效配置、进入 Claim evaluator 后，单个 claim 的 LLM 调用失败或输出无法解析 → 该 claim 标 `not_verifiable`，在 details 记录原因，不影响其他 claim，不中断整体流程。

### 各 evaluator 输出形态示例

见规格第 5–9 节，本实现严格对齐这些字段名。

## 5. CLI 与 chat_fn 构造（`mvp_single_case.py`）

```
python -m evals.mvp_single_case \
  --fixture evals/fixtures/mvp_single_case.json \
  --output evals/mvp_output \
  --model-id <DB model 表主键>
```

- 读 `--model-id` → 连 MySQL（复用项目现有 DB 配置 `DB_URL/DB_USERNAME/DB_PASSWORD`）查 `model` 表那一条 → 拿 `base_url/api_key/model`。
- 用 `openai` 兼容客户端构造 `chat_fn(system, user) -> str`（async）。
- 取不到 model 记录或 `api_key` 为空 → 报错退出，提示需提供有效 `--model-id`。
- 主流程：

```python
raw = load_fixture(path)
ctx = build_context(raw)
check_completeness(ctx)

intent = await evaluate_intent(ctx)
review = await evaluate_review(ctx)
claims = await evaluate_claims(ctx, chat_fn=chat_fn)
consistency = await evaluate_consistency(ctx)
verifier = await evaluate_claim_verifier(ctx)

result = aggregate(ctx, intent, review, claims, consistency, verifier)
write_json(result)
write_markdown(render_report(result))
```

固定顺序（规格第 4 节）：

```
Context Completeness → Intent → Review → Claim → Consistency → ClaimVerifier → Aggregate
```

## 6. 聚合与报告（`mvp_report.py`）

### 6.1 JSON 输出（规格第 10 节）

```json
{
  "case_id": "tech_comparison_demo_001",
  "context_complete": true,
  "result_eval": {
    "hard_gate": "failed",
    "required_point_coverage": 0.75,
    "citation_correctness": 0.33,
    "unsupported_critical_claim_count": 1
  },
  "process_eval": {
    "intent": {},
    "review": {},
    "consistency": {},
    "claim_verifier": {}
  },
  "diagnosis": [
    "Intent 漏掉安全约束",
    "Reviewer 正确发现安全 Gap",
    "第二轮产生了安全 Evidence，但最终报告未使用",
    "最终报告存在 Unsupported Critical Claim"
  ],
  "cost": {
    "input_tokens": 12000,
    "output_tokens": 3000,
    "reviewer_tokens": 1800
  }
}
```

### 6.2 Hard Gate 聚合逻辑

- `required_point_coverage`：来自 Intent（required_points 覆盖）+ Review（gap 是否关闭）综合。
- `citation_correctness`：来自 Claim。
- `unsupported_critical_claim_count`：来自 Claim。
- 任一 critical 项不达标 → `hard_gate: "failed"`，并给出 failure codes（参考现有 `HardGateEvaluator` 的 failure code 命名约定：`missing_required_points` / `unsupported_critical_claim` 等，但本 MVP 自有聚合，不强制复用）。

### 6.3 Markdown 报告（规格第 10 节，8 段）

```
Case / Task Spec
EvalContext 完整性
Intent
Review
Claims/Citations/Evidence
Consistency 前后
ClaimVerifier
Hard Gate
最终诊断
```

每个结论可回溯到 claim_id / evidence_id / review gap / artifact id。

`diagnosis` 列表对应规格第 2 节 6 个预置问题，由各 evaluator 的 finding 汇总生成。

## 7. 测试

- **端到端测试 1 个**（验收第 12 条）：加载 Fixture → build_context → 跑 5 evaluator（Claim 用 `fake_chat` 注入，不连真 DB/真模型）→ 断言关键结论：
  - Intent 漏安全约束（`missing_constraints` 含 `security`）
  - Reviewer 发现 gap（`gap_recall = 1.0`），最终报告未关闭（`gap_closure_rate = 0.0`）
  - Consistency 矛盾消除（`contradictions_before=1, after=0`）
  - ClaimVerifier 标记 unsupported（`unsupported_detection_recall = 1.0`）
  - `hard_gate = "failed"`，失败原因含 unsupported critical claim
- 遵循现有测试模式：`tests/` 下 pytest + `asyncio_mode="auto"`，evaluator 纯逻辑测试用本地 `_ctx()` 工厂 + `fake_chat`（对应 `test_eval_commit6d_evaluators.py` 的做法）。
- e2e 测试不连真 MySQL、不调真模型，保证 CI 能跑。真模型路径由 `--model-id` 手动触发，不在 CI 覆盖。

## 8. 验收对照（规格第 11 节 12 条）

| # | 验收项 | 本设计如何满足 |
|---|---|---|
| 1 | 一条命令可运行单题 Eval | `python -m evals.mvp_single_case --fixture ... --output ... --model-id ...` |
| 2 | 输出完整 EvalContext 摘要和缺失字段 | `check_completeness` + JSON `context_complete` |
| 3 | 指出 Intent 遗漏的安全约束 | Intent evaluator `missing_constraints` |
| 4 | 说明 Reviewer Gap 是否准确、下一轮是否关闭 | Review evaluator `gap_precision/recall/closure_rate` |
| 5 | 逐条输出至少 3 个 Claim 的支持状态 | Claim evaluator（3 个 claim，LLM 判） |
| 6 | 输出 Consistency 前后矛盾和保留率 | Consistency evaluator |
| 7 | 输出 ClaimVerifier 检测、修正和误报 | ClaimVerifier evaluator |
| 8 | 输出最终 Hard Gate 和失败原因 | aggregate + `result_eval.hard_gate` |
| 9 | 结果包含 Token/成本字段 | `cost`（input/output/reviewer tokens） |
| 10 | 能回溯到 Claim、Evidence、Gap 或 Artifact | 各 MetricResult `details` 携带 id |
| 11 | 不依赖 DB / Tavily / 真实 LLM | **有意覆盖**：不依赖 Tavily / eval 业务表；可连 model 表读配置、可调真模型判 claim（见第 0 节） |
| 12 | 至少一个端到端测试验证关键结论 | 第 7 节 e2e 测试 |
