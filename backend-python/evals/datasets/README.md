# Deep Research Eval Datasets

## 数据集

### `mvp_v1_6questions.json`

6 题 Smoke Dataset，只用于验证 Dataset 契约、落库和 Eval 流程是否能正常运行。

### `formal_v1_40questions.json`

正式端到端 Dataset，共 40 题：

| Task Type | 数量 |
|---|---:|
| `fact_lookup` | 6 |
| `tech_comparison` | 8 |
| `market_analysis` | 7 |
| `academic_review` | 7 |
| `trend_forecast` | 6 |
| `evidence_conflict` | 6 |

其中 10 题属于 `calibration`，用于校准 Evaluator Prompt、Judge 和阈值；30 题属于
`test`，用于正式比较 MEDIUM/HIGH/ULTRA。不要根据 Test 结果反复修改 Evaluator。
难度分布为 Easy 8 题、Medium 18 题、Hard 14 题，保证既能观察 MEDIUM 的基础完成
能力，也有足够复杂题区分 HIGH 和 ULTRA。

## 三档实验

每个 Item 使用相同的 Query、As-of Date、Criterion、Reference Facts、Source Policy
和 Forbidden Claims 运行：

```text
MEDIUM × 1 repeat
HIGH   × 1 repeat
ULTRA  × 1 repeat
```

第一版主实验共 `40 × 3 × 1 = 120` 次 Agent Run。比较时以 Item 为配对单位，至少同时输出：

- Task Type 宏平均；
- Difficulty 宏平均；
- `HIGH - MEDIUM` 配对差值；
- `ULTRA - HIGH` 配对差值；
- Bootstrap 置信区间；
- 任务完成率和 Hard Gate 失败率；
- 质量、Token、时延及边际质量/成本。

## 机制实验抽样

机制实验直接复用 40 道端到端题目，不建立另一套问题分布。权威抽样清单位于
`mechanism_suites`：

| Suite | 数量 | 选择原则 |
|---|---:|---|
| `high_report_ablation` | 8 | 需要多视角比较和综合报告 |
| `reviewer_ablation` | 10 | 第一轮容易出现可识别缺口或证据冲突 |
| `multi_round_ablation` | 10 | 单轮检索不容易充分完成 |
| `section_team_ablation` | 6 | 报告结构复杂、章节之间需要协调 |
| `claim_verifier_ablation` | 8 | 关键数字、监管状态或冲突 Claim 较多 |

不同 Suite 可以重叠。这是有意设计：同一道高难题可以同时适合 Reviewer、多轮和
ClaimVerifier 实验，但每个实验仍需独立运行，不能用一次 Run 同时声称多个机制的因果效果。

加载并抽取：

```python
from evals.runner import load_dataset_json, select_mechanism_item_ids

dataset = load_dataset_json("formal_v1_40questions.json")
reviewer_items = select_mechanism_item_ids(dataset, "reviewer_ablation")
```

Loader 会展开 `defaults`，并把 `mechanism_suites` 自动同步到每个 Item 的
`evaluation_contract.mechanism_tags`，避免两份标签漂移。

## 标注规则

每个正式 Item 至少包含：

- 三个结构化 Criterion；
- 两个关键 Reference Fact；
- Forbidden Claims；
- Source Policy；
- Expected Intent；
- Difficulty 和 Domain；
- 固定 As-of Date。

Criterion ID 在单个 Item 内必须唯一。同一 Criterion 用于连接 Intent、Plan、
Evidence 和 Final Report 的评价结果。

当前 Reference Facts 是可判定的事实锚点，不是唯一标准答案。正式上线前应由对应领域
标注者抽查全部关键事实；法规、医疗和快速变化技术题应优先复核，并在事实或来源过期时
发布新的 Dataset Version，不能原地修改已经产生基线结果的版本。
