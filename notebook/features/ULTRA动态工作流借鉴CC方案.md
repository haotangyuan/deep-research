# ULTRA 动态工作流借鉴 CC 方案

> 本文档是借鉴 Claude Code Dynamic Workflows 思想强化本项目 ULTRA 动态工作流的技术方案，作为后续实现的依据。采用「质量优先」策略：ULTRA 是高端档位，可接受更高的模型调用成本换取更可信的研究结论。

## 一、背景

### 1.1 CC Dynamic Workflows 的可借鉴思想

Claude Code Dynamic Workflows（v2.1.154+）的本质是「主模型生成 JS 编排脚本，本地 runtime 执行，启动子代理」。其四层架构为：主会话（`Workflow` 工具）→ JS 编排脚本 → 本地 runtime → 子代理（`StructuredOutput`）。

与本项目最相关的不是「JS 脚本」载体（本项目是 Python 业务代码，不应引入 JS），而是其**质量模式**：

- **对抗性审查（Adversarial Verify）**：独立代理互相 refute，默认 refuted，多数同意才采信
- **结构化子代理输出（StructuredOutput）**：`agent({schema})` 强制子代理返回符合 schema 的 JSON，父流程无需解析自然语言
- **多角度起草 + 评委（Judge Panel）**：从 N 个角度并行起草，评委打分选优 + 嫁接落选者最佳创意
- **声明级交叉验证（Cross-check）**：对每个声明投票，未通过交叉检查的过滤或标注
- **可配置编排**：编排逻辑沉淀为可读、可改、可重跑的脚本

### 1.2 本项目 ULTRA 现状

ULTRA 动态工作流已是「质量驱动的多轮闭环」：每轮 plan-do-review，LLM 输出 5 维质量评分决定 continue/report，证据账本落盘，用户可轻干预。但存在三个可强化点：

1. **评审是单 LLM**：`_review_round` 由单个 LLM 评审，可能「自欺」——低质量也判 continue
2. **Researcher 输出非结构化**：返回压缩文本，证据靠 `collect_evidence_entries` 从 `search_results` 提取，来源分类依赖 URL 启发式
3. **报告单次生成**：`ReportAgent` 一次性产出，无多角度对比，关键声明无交叉验证
4. **编排硬编码**：ULTRA 的 while 循环固定在 `pipeline.py`，不同研究类型无法定制流程

### 1.3 借鉴目标

| 借鉴点 | CC 思想 | ULTRA 强化方向 |
|--------|---------|---------------|
| A 对抗性审查 | 独立代理互相 refute | 评审阶段多 reviewer 投票 + 报告声明交叉验证 |
| B 结构化子代理输出 | `agent({schema})` | Researcher 返回结构化证据 schema |
| C 报告多角度起草 + 评委 | judge panel | 报告 3 角度并行起草 + 评委融合 |
| E 可配置编排模板 | 编排沉淀为脚本 | 轮次结构抽象为 JSON 模板，不引入 JS |

## 二、CC 实现要点（参考）

### 2.1 四层架构
```
主会话(Workflow 工具) → JS 编排脚本 → 本地 runtime → 子代理(StructuredOutput)
```
- `Workflow` 工具 schema：`script / name / args / scriptPath / resumeFromRunId`
- 后台任务模型：调用立即返回 `Task ID + Run ID`，完成后 `<task-notification>` 回灌

### 2.2 JS DSL 关键限制（确定性设计）
- `meta` 必须纯字面量（无变量/函数/spread/插值）
- 禁用 `Date.now()` / `Math.random()` / 无参 `new Date()` —— 保证恢复缓存确定性
- 纯 JS（非 TS），无 Node API，无文件系统

### 2.3 DSL 核心原语
| 原语 | 语义 |
|------|------|
| `agent(prompt, {schema, label, phase, model})` | 启动子代理；`schema` 强制返回结构化 JSON |
| `pipeline(items, stage1, stage2, ...)` | 无阶段 barrier，item 流水线推进 |
| `parallel(thunks)` | 屏障式并发 |
| `phase() / log()` | 进度分组与叙事 |

### 2.4 质量模式
- 对抗性审查：N 个独立 skeptic，默认 refuted，多数同意才采信
- 多角度起草：N 个角度并行起草 → 评委打分 → 取冠军 + 嫁接落选者最佳创意
- 声明交叉验证：每个声明投票，未通过过滤

### 2.5 恢复
`resumeFromRunId` 基于 `(prompt, opts)` 哈希复用未变更 agent 的缓存结果。

## 三、详细设计

### 3.1 借鉴点 A：对抗性审查

#### 现状
`ultra_dynamic.py::_review_round` 单次 LLM 调用 `ULTRA_DYNAMIC_REVIEW_PROMPT`，输出一个 decision（含 nextAction）。

#### 目标
- **评审阶段**：N=3 个独立 reviewer 从不同 lens 评审，投票决定 nextAction
- **报告声明**：报告生成后，独立代理对关键声明做交叉验证，未验证的标注

#### 设计

**评审阶段（替换 `_review_round`）**：
```
_review_round(round, results, evidence):
  reviewers = [
    {lens: "evidence_sufficiency", focus: "证据是否足够支撑结论"},
    {lens: "source_authority",     focus: "来源是否权威、多样"},
    {lens: "coverage_completeness",focus: "章节覆盖是否完整"},
  ]
  # 并行调用 3 个 reviewer，各自输出 {nextAction, scores, gaps}
  votes = parallel(reviewers.map(r => call_reviewer(r, round, evidence)))
  # 聚合：默认 refuted，多数(≥2)同意 continue 才 continue
  continue_votes = votes.count(v => v.nextAction == "continue")
  decision.nextAction = continue_votes >= 2 ? "continue" : "report"
  # 合并评分（取各维度最低，突出短板）
  decision.qualityScoreboard = merge_min(votes.map(v => v.scores))
  decision.votes = votes  # 落盘备查
```

**报告声明交叉验证（ReportAgent 后置）**：
```
verify_report_claims(report, evidence_ledger):
  claims = extract_claims(report)  # 抽取带引用标注的关键声明
  # 每个 claim 独立代理查验是否有来源支撑
  verdicts = parallel(claims.map(c => verify_claim(c, evidence_ledger)))
  # 未验证的标注 [未验证]，无来源的标注 [缺来源]
  return annotate_report(report, verdicts)
```

#### 数据模型变更
- `research_decision_log.payload_json` 增加 `votes` 字段（每个 reviewer 的 lens + nextAction + scores）
- 新增 `research_claim_verification` 表（可选）：`research_id, round_no, claim_text, source_url, verdict(verified|unverified|no_source), reviewer_id`

#### 代码改动点
- `ultra_dynamic.py`：`_review_round` → `_adversarial_review`（并行 N reviewer + 投票聚合）
- `prompts.py`：新增 `ULTRA_REVIEWER_LENS_PROMPT`（按 lens 评审）
- `agents.py::ReportAgent`：报告生成后调用 `verify_report_claims`
- 新增 ` ULTRA_CLAIM_VERIFY_PROMPT`

#### 质量优先参数
- reviewer 数 N=3
- 聚合规则：默认 refuted，≥2 票 continue 才 continue
- 评分合并：取各维度最低分（短板原则）

### 3.2 借鉴点 B：结构化子代理输出

#### 现状
`ResearcherAgent._compress_research` 让 LLM 把研究材料压缩成文本，存入 `state.compressed_research`；证据靠 `collect_evidence_entries` 从 `branch_state.search_results` 提取，来源分类用 `classify_source_type`（URL 启发式）。

#### 目标
Researcher 直接返回结构化证据 schema，证据账本直接消费，来源分类由 LLM 判定（更准）。

#### 设计

**Researcher 输出 schema**：
```json
{
  "findings": "压缩后的研究结论（Markdown）",
  "sources": [
    {
      "url": "https://...",
      "title": "来源标题",
      "type": "official|academic|report|news|company|other",
      "strength": "high|medium|low",
      "snippet": "关键片段",
      "sectionHint": "适用的报告章节"
    }
  ]
}
```

**实现**：
- `_compress_research` 改为调用 LLM 时强制 schema 输出（AgentScope 的 StructuredOutput 机制，或 prompt + JSON 解析 + 重试）
- `state.compressed_research` 仍存 `findings` 文本（兼容 ReportAgent）
- 新增 `state.researcher_sources`（结构化来源列表）
- `collect_evidence_entries` 优先从 `state.researcher_sources` 取（LLM 分类），fallback 到 `search_results`（URL 启发式）

#### 数据模型变更
- `research_evidence_ledger` 增加 `strength_score` 已有；`source_type` 改为优先用 LLM 分类值
- 新增 `researcher_sources` 字段到 `DeepResearchState`（或复用 `search_results` 的扩展）

#### 代码改动点
- `prompts.py`：`COMPRESS_RESEARCH_*_PROMPT` 改为要求 JSON schema 输出
- `agents.py::ResearcherAgent._compress_research`：解析结构化输出
- `domain/state.py`：新增 `researcher_sources` 字段
- `ultra_dynamic.py::collect_evidence_entries`：优先用 `researcher_sources`

#### 收益
- 来源分类由 LLM 判定（比 URL 启发式准，如能识别「这是政府统计」而非靠 .gov 域名）
- 证据账本直接消费结构化来源，无需从 search_results 反推
- review 阶段证据输入更结构化

### 3.3 借鉴点 C：报告多角度起草 + 评委

#### 现状
`ReportAgent.run` 单次 LLM 调用生成报告。

#### 目标
3 个角度并行起草 → 评委打分 → 融合出最终报告。

#### 设计

**角度定义**（可配置，默认 3 个）：
- `data-driven`：数据驱动，突出数值、对比表格、来源引用
- `narrative`：叙事驱动，突出趋势、因果、演进
- `comparative`：对比驱动，突出多维度横向对比

**流程**：
```
ReportAgent.run(state):
  # 阶段1：3 角度并行起草
  drafts = parallel(angles.map(a => draft_report(a, state)))
  # 阶段2：评委打分（独立代理，按 5 维评分）
  scores = parallel(drafts.map(d => judge_report(d, state)))
  # 阶段3：融合——取冠军 draft，嫁接其他 draft 的最佳段落
  final = synthesize_report(drafts, scores, state)
  # 声明交叉验证（借鉴点 A 的报告声明验证）
  final = verify_report_claims(final, state)
  return final
```

#### 代码改动点
- `agents.py::ReportAgent`：`run` 重构为三阶段
- `prompts.py`：新增 `REPORT_DRAFT_ANGLE_PROMPT`、`REPORT_JUDGE_PROMPT`、`REPORT_SYNTHESIS_PROMPT`
- 失败降级：若多角度起草失败，fallback 到单次生成（保留现有 `_fallback_report`）

#### 质量优先参数
- 起草角度数 = 3
- 评委维度：覆盖度、证据、结构、可读性、来源引用
- 融合策略：冠军 draft 为底 + 嫁接落选者最佳段落

### 3.4 借鉴点 E：可配置编排模板 + 意图识别

#### 现状
ULTRA 的 while 循环、轮次上限、评审机制硬编码在 `pipeline.py::_execute_ultra_dynamic_phase_and_3`。所有 ULTRA 研究用同一套流程，不区分研究类型。

#### 目标
1. 把轮次结构抽象为 JSON 模板，不同研究类型用不同模板
2. 引入**意图识别**：ScopeAgent 在理解需求时顺带判断研究类型，自动选择最匹配的模板
3. **不引入 JS**，保持 Python 业务代码掌控持久化与状态机

#### 设计

**意图识别（与 Scope 合并，零额外 LLM 调用）**：
ScopeAgent 本就在理解研究需求、生成 research_brief。扩展其输出，让 LLM 同时产出 `researchType` + `typeConfidence`：

```json
{
  "researchBrief": "...",
  "researchType": "tech_comparison",
  "typeConfidence": 0.9
}
```

**研究类型枚举**（初期 6 类，可扩展）：

| 类型 | 适用场景 | 模板侧重 |
|------|---------|---------|
| `tech_comparison` | 技术选型/对比 | 报告侧重 comparative 角度 |
| `market_analysis` | 市场/行业分析 | 来源侧重 official/report |
| `academic_review` | 学术综述 | 来源侧重 academic，reviewer 侧重证据 |
| `fact_lookup` | 事实查询/定义 | 单轮即可，maxRounds=1 |
| `trend_forecast` | 趋势预测 | 来源侧重 news/latest，时效性评分加权 |
| `general` | 通用/不确定 | 默认模板 |

**模板选择逻辑**：
```
select_template(research_type, confidence):
  if confidence >= 0.7 and exists(f"templates/ultra_{research_type}.json"):
    return load(f"templates/ultra_{research_type}.json")
  return load("templates/ultra_default.json")  # fallback
```

**模板 schema**（`backend-python/templates/ultra_default.json`，含 type 字段）：
```json
{
  "type": "general",
  "mode": "ultra_dynamic",
  "maxRounds": 5,
  "reviewer": {
    "count": 3,
    "lenses": ["evidence_sufficiency", "source_authority", "coverage_completeness"],
    "continueThreshold": 2
  },
  "report": {
    "draftAngles": ["data-driven", "narrative", "comparative"],
    "judgeEnabled": true,
    "claimVerification": true
  },
  "intervention": {
    "enabled": true,
    "applyMode": "next_round_planner_bias"
  },
  "budget": {
    "maxConductCount": 6,
    "maxSearchCount": 4,
    "maxConcurrentUnits": 3
  }
}
```

**类型化模板示例**（`ultra_tech_comparison.json`，对比类研究侧重 comparative 角度）：
```json
{
  "type": "tech_comparison",
  "mode": "ultra_dynamic",
  "maxRounds": 4,
  "report": {
    "draftAngles": ["comparative", "data-driven", "narrative"],
    "judgeEnabled": true,
    "claimVerification": true
  },
  "reviewer": { "count": 3, "lenses": ["evidence_sufficiency", "source_authority", "coverage_completeness"], "continueThreshold": 2 },
  "intervention": { "enabled": true, "applyMode": "next_round_planner_bias" },
  "budget": { "maxConductCount": 6, "maxSearchCount": 4, "maxConcurrentUnits": 3 }
}
```

**实现**：
- `core/config.py` 新增 `research_ultra_template_dir` 配置（模板目录）
- 新增 `application/workflow_template.py`：加载/校验/选择模板
- `agents.py::ScopeAgent`：扩展输出 `researchType` + `typeConfidence`
- `pipeline.py::_execute_ultra_dynamic_phase_and_3` 改为模板驱动：scope 后按类型选模板，while 读 `maxRounds`，评审调 `reviewer.count` 个，报告读 `report.draftAngles`
- `domain/state.py`：新增 `research_type` / `workflow_template` 字段

#### 代码改动点
- 新增 `application/workflow_template.py`
- 新增 `backend-python/templates/ultra_default.json` + 各类型模板（初期 default + 5 类）
- `agents.py::ScopeAgent`：输出 researchType
- `pipeline.py`：scope 后选模板，参数化 while 循环
- `ultra_dynamic.py`：reviewer 数和 lens 从模板读
- `agents.py::ReportAgent`：角度从模板读
- `domain/state.py`：新增 research_type 字段

#### 取舍
- **不引入 JS 脚本**：保持 Python 业务代码对持久化、状态机、HITL 的掌控；模板只描述参数，不描述控制流
- **意图识别与 Scope 合并**：复用 ScopeAgent 的理解能力，零额外 LLM 调用，比单独意图识别步骤更优雅
- **控制流仍在 Python**：与 CC「脚本持有控制流」不同，本项目「模板参数化控制流 + 意图识别选模板」
- **类型枚举初期保守**：先 6 类，置信度 < 0.7 或无匹配模板时 fallback 到 default，避免误分类导致流程不匹配

## 四、实施路线

| 阶段 | 内容 | 依赖 | 工作量 |
|------|------|------|--------|
| 阶段 1 | 借鉴点 B：结构化子代理输出 | 无 | 中 |
| 阶段 2 | 借鉴点 A：对抗性审查（评审 + 报告声明验证） | B（结构化证据喂给 reviewer） | 中 |
| 阶段 3 | 借鉴点 C：报告多角度起草 + 评委 | 无（可与 A 并行） | 中 |
| 阶段 4 | 借鉴点 E：可配置编排模板 + 意图识别 | A/B/C 落地后抽象 | 大 |

**建议顺序**：B → A → C → E。B 是基础（结构化证据让 A 的对抗审查和 C 的报告起草都有更好输入）；E 最后做，等 A/B/C 参数稳定后再抽象成模板，并引入意图识别按研究类型选模板。

## 五、风险与取舍

| 风险 | 应对 |
|------|------|
| Token 成本上升（N=3 审查 + 3 角度起草） | ULTRA 是高端档位，质量优先可接受；可配 `researcher_count` / `draft_angles` 调节 |
| 延迟增加 | 并行调用（reviewer、draft 角度都并行），wall-clock 不线性增长 |
| 评审僵局（reviewer 投票分歧） | 默认 refuted 倾向 report，避免低质量继续 |
| 结构化输出 LLM 不遵守 schema | prompt 强约束 + JSON 解析重试 + fallback 到文本提取 |
| 模板过度抽象增加复杂度 | E 阶段控制范围，模板只参数化不写控制流 |

## 六、借鉴后与 CC 的对比

| 维度 | 本项目 ULTRA（借鉴后） | CC Dynamic Workflows |
|------|----------------------|----------------------|
| 编排载体 | Python 业务代码 + JSON 模板参数化 | LLM 生成 JS 脚本 |
| 评审 | N=3 对抗审查 + 投票 | 对抗性审查 + 多角度起草 |
| 子代理输出 | 结构化 schema（findings + sources） | StructuredOutput schema |
| 报告 | 3 角度起草 + 评委融合 + 声明验证 | 多角度起草 + 评委 |
| 持久化 | MySQL/Redis 全程落盘 | 脚本变量 + journal |
| 可恢复 | checkpoint 续跑（业务状态机） | resumeFromRunId 缓存复用 |
| 领域 | 研究专用 | 通用 |

**核心差异保持**：本项目仍以「质量驱动的结构化研究闭环 + 业务持久化」为内核，借鉴的是 CC 的「质量模式」而非「脚本编排载体」。

## 七、参考资料

- [使用动态工作流大规模编排子代理 - Claude Code Docs](https://code.claude.com/docs/zh-CN/workflows)
- [Claude Code Workflow 实现原理：从抓包看动态多代理编排](https://github.com/TokenRollAI/claude-code-workflow-research)
