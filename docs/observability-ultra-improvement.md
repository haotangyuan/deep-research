# ULTRA 可观测性改造总结

> 面向面试 / Code Review 场景的技术总结。覆盖：原版基线、本次改动（M1–M5 + bug 修复）、改进对比、可讲的技术点、潜在问题。

## 一、原版的可观测基线

原版有一套**基础设施完整但语义稀薄**的 OTel / Langfuse 链路：

- 全局共享一个 `TracerProvider`（`backend-python/app/infrastructure/observability.py:28-36`），应用自己的 span 和 AgentScope 2.0.3 的 `TracingMiddleware` 读同一个 Provider，因此 AgentScope 原生 span（`invoke_agent` / `chat` / `execute_tool`）能自然成为应用 span 的子节点，不会形成第二条孤立 trace。
- 四层 span 框架已具备：`workflow`（根）→ `stage`（Scope / Supervisor / Report）→ `model`（每次 LLM 调用）→ `tool`（conductResearch / tavilySearch）。
- 公共属性齐全：每个 span 带 `research.id` / `user.id` / `model.id` / `budget.level` / `workflow.status` + token 用量。

**问题不在「有没有 trace」，在「trace 能不能读懂」。** 一次 ULTRA 跑下来产生几百个 span，但有两个塌缩点让人无法从 trace 里读出 ULTRA 在干什么：

1. **model span 不带角色**：所有 LLM 调用都叫 `deep_research.model mimo`，Supervisor 规划、6 个 Reviewer、6 个章节起草、一致性检查、合并——全长得一模一样，点开属性也分不出这是谁。
2. **结构层缺父 span + 缺决策属性**：多轮复用同名 `stage SupervisorAgent` 看不出第几轮；N 个 reviewer 的并行没有「评审轮」这个父节点；动态决策（`nextAction` / 评分 / 缺口）只写 MySQL 和 SSE，trace 里看不到；章节团队五步全塌缩在 `stage ReportAgent` 一个 span 里。

一句话：**性能维度（token、延迟）勉强可观测，但 ULTRA 区别于普通档的核心机制——动态多轮决策、章节报告团队、证据缺口披露——对 trace 完全隐形。** 这是「能导出 trace」和「能读懂 trace」的差距。

## 二、本次改动（M1–M5 + 一个 bug 修复）

共 6 个文件，约 360 行变更（含缩进重排）：

| 文件 | 改动 |
|---|---|
| `app/infrastructure/observability.py` | `model_span` 加 `agent_id` 参数（M1）；`_set_common` 加 `workflow.mode` / `dynamic.round.no`（M2） |
| `app/infrastructure/llm.py` | `run_agent` 调 `model_span` 时透传 `request.stage_name`（M1） |
| `app/application/ultra_dynamic.py` | `_adversarial_review` 包 `UltraDynamicReview` span + 决策属性（M3） |
| `app/application/report_team.py` | `run` + 五个子步骤各包结构 span + section 属性（M4）；`_write_text_node` 加截断兜底 |
| `app/application/pipeline.py` | `_apply_ultra_report_gate` 包 `UltraReportGate` span + 质量属性（M5） |
| `app/domain/models.py` | `research_context_node.content` / `chat_message.content` 由 `Text` → `MEDIUMTEXT`（bug 修复） |

### M1 — model_span 加 `agent.name` 属性（解开塌缩点①）

`observability.py` 的 `model_span` 签名加 `agent_id` 参数，设 `agent.name` span 属性；`llm.py` 调用处透传 `request.stage_name`。

**为什么是最高杠杆的一改**：角色名（SupervisorAgent / `UltraDynamicReviewer:{lens}` / `ReportSectionAgent:{section_id}` / ReportConsistencyAgent / ReportAgent:merge / ClaimVerifier …）**本来就传到了调用栈里**，只是 `model_span` 没接住。一个签名 + 一行透传，让 ReportAgent 下面那一锅同名的 `deep_research.model` 全部可区分。后面所有结构 span（M3 / M4）的叶子层都靠它才可读。

### M2 — `_set_common` 加 `workflow.mode` + `dynamic.round.no`

`_set_common` 是四种 span（workflow / stage / tool / model）共用的公共属性函数，加 2 行，所有 span 自动带上轮次和模式。

**设计好处**：不逐个点位改，一处生效全链路。多轮场景下，`stage SupervisorAgent` 在 round 1 / 2 / 3 不再同名混淆，可按 `dynamic.round.no` 切片分析任何一轮。`workflow.mode` 还顺带把「ULTRA 动态 vs FIXED 单轮」做成可过滤属性。

### M3 — UltraDynamicReview span + 决策属性（ULTRA 核心决策白盒化）

`ultra_dynamic._adversarial_review` 的 `asyncio.gather`（N 个 reviewer 并行）外包一层 `stage_span("UltraDynamicReview")`，聚合后设：`review.next.action` / `review.continue.votes` / `review.report.votes` / `review.consensus` / `review.continue.threshold` / `review.lens.count` / `review.gaps.count` / `review.score.{coverage, evidence, freshness, sourceDiversity, consistency}`。

**这是把「动态决策」从黑盒变白盒的关键点**。决策结果原本只写 `research_decision_log` 表 + SSE 事件——要看就得查库或回放 SSE。现在 trace 里直接有 `nextAction=continue` + `evidence=1` + `gaps=5`，能跨多条 trace 做「证据质量分析」而非仅性能分析。决策结果首次成为一等可观测维度。

### M4 — 章节报告团队五步结构化（解开塌缩点②的报告侧）

`report_team.py` 的 `run` 包 `ReportSectionTeam` 父 span；五个子步骤各包一层：`ReportSectionPlanner` / `ReportSectionDraft`（带 `report.section.id`）/ `ReportConsistency` / `ReportSectionRevise`（带 `report.section.id`）/ `ReportMerge`。

**设计好处**：`asyncio.gather` 并行的 N 个 section，以前全塌在 `stage ReportAgent` 下分不清；现在 plan → draft×N → consistency → revise×N → merge 树形可读。配合 M1 的 `agent.name`，每个 section 的 draft / revise LLM 调用都能定位到具体 section（如 `ReportSectionAgent:supply-chain-risk`）。这是 ULTRA 报告卖点（章节并行 + claim mailbox + 一致性修订）目前唯一的可见性来源。

### M5 — UltraReportGate span + 质量属性（质量维度可观测）

`pipeline._apply_ultra_report_gate` 包 `stage_span("UltraReportGate")`，设 `report.quality.status`（ready / needs_disclosure）/ `report.weak.sections.count` / `report.blocking.gaps.count`。

**这是把「质量」做成一等可观测维度的点**。性能（token / 延迟）原版就够，但 ULTRA 真正卖的是「诚实披露证据边界」——`needs_disclosure` 这个状态是这套机制的核心产物，原本对 trace 隐形。改完可在 Langfuse 直接按 `report.quality.status=needs_disclosure` 过滤，回答「多少 ULTRA 研究最终证据不足」。

### Bug 修复（顺带挖出的）— 章节团队 1406 全军覆没

改 M4 时埋的 span 第一次跑 ULTRA 就暴露：6 个 `ReportSectionDraft` 全部 ERROR，`statusMessage` 是 `DataError (1406) Data too long for column 'content'`。

根因：`research_context_node.content` 是 `TEXT`（64KB），章节 draft 全文直接写没截断，必超。更糟的是 `ReportSectionTeam.run` 整体 `try/except` 把这个异常吞掉，默默回退到 fallback 多角度起草——**ULTRA 章节团队卖点从没跑通过，每次都静默回退，一直没人发现**。

修复：
- **治本**：`models.py` 把 `research_context_node.content` 和 `chat_message.content` 从 `Text` → `MEDIUMTEXT`（16MB），`ALTER TABLE` 跟上。
- **兜底**：`report_team._write_text_node` 加 `truncate(content, 3_000_000)`（MEDIUMTEXT 极限 16MB / utf8mb4 最坏 4 字节，留 4MB 余量），只在病态超长触发，正常 draft 一字不丢。

验证：第二次跑同题，`ReportConsistency` / `ReportSectionRevise` / `ReportMerge` 三个 span 全部出现，根 span level=DEFAULT 无 error——章节团队真正跑通。

### 设计哲学（贯穿全部改动）

三句话：

1. **可观测的价值 = 定向性 × 低噪声**。三档不是按「能埋就埋」，而是按「少了就看不懂链路 → 能诊断 ULTRA 独有瓶颈 → 深度调试」分层。M1 / M2 是「加属性」（便宜、收益最大），M3 / M4 / M5 是「加结构 span」（更准、动业务文件）。
2. **span 是观测面，不是执行面**。全部 `async with stage_span(...)` 包裹现有调用 + `set_attribute`，不改控制流、不改 `asyncio.gather` / `Semaphore`、不改 DB 写入顺序。并发 / 预算 / 缓存 / 超时这些性能红线一字未动。
3. **观测未初始化时自动失活**。`stage_span` / `model_span` 在 `RESEARCH_OBSERVABILITY_ENABLED=false` 时返回 `NonRecordingSpan`，contextmanager 近乎零成本。新增 span 不需要加 `if enabled` 门控，关掉观测不破性能。

两条工程纪律：
- **低基数属性**：`round_no`（1–5）、`lens_key`（固定枚举）、`section_id`（3–6 个）、`status`（ready / needs_disclosure）、`score`（1–5）——全是枚举 / 小集合。**不**把 claim 全文、search query、report 正文塞进 span 属性（那些留 DB / SSE），避免高基数拖垮 Langfuse 查询和成本。
- **默认不采 I/O**：新 span 不自作主张塞 prompt / 响应正文，复用 `summarize()`（已有 Authorization / key / secret / token 脱敏），仍受 `RESEARCH_OBSERVABILITY_CAPTURE_IO` 总开关管。

## 三、改进对比

| 维度 | 原版 | 改后 |
|---|---|---|
| model span 区分角色 | 全叫 `deep_research.model mimo`，一锅粥 | `agent.name` 区分 20+ 角色（SupervisorAgent / Reviewer:{lens} / Section:{id} / Merger …） |
| 多轮可定位 | `stage SupervisorAgent` 多轮同名 | 全 span 带 `dynamic.round.no`，按轮次切片 |
| ULTRA vs FIXED | 得从 `budget.level` 反推 | `workflow.mode` 直接可过滤 |
| 动态决策可见性 | 查 MySQL `research_decision_log` | trace 里 `review.next.action` / `review.score.*` / `review.gaps.count` |
| 评审轮结构 | N 个 reviewer model span 无父节点 | `UltraDynamicReview` 父 span + 聚合决策属性 |
| 章节团队结构 | 塌缩在 `stage ReportAgent` 一片 | 五步树：Plan → Draft×N → Consistency → Revise×N → Merge |
| section 可定位 | 不分 | `report.section.id` 属性，定位到具体章节 |
| 质量可观测 | 性能可见，质量不可见 | `report.quality.status` 可按 `needs_disclosure` 过滤 |
| 隐藏 bug | 章节团队 1406 静默回退 fallback，从没跑通 | 埋点暴露 → 列改 MEDIUMTEXT + 截断兜底 → 跑通 |

## 四、可讲的技术点

1. **OTel Provider 共享设计**：应用层 `TracerProvider` 和 AgentScope `TracingMiddleware` 共用一个全局 Provider，原生 AgentScope span 自然成为应用 span 的子节点。这是这套可观测能「四层贯通」的底层原因——不是事后拼接的。
2. **属性透传的杠杆**：M1 不是「给 model span 加角色字段」，是「把已经在调用栈里流动的 `stage_name` 接进 span」。识别「信息已经在那儿，只是没被观测面接住」是一类高 ROI 改动。
3. **公共属性函数的复用**：M2 改 `_set_common` 一处，四种 span 全带——用复用代替逐个点位改，降低漏埋和一致性风险。
4. **决策结果进 span 属性而非只进 DB**：M3 把动态决策从「持久层 / SSE 层可观测」提升到「trace 层可观测」，这才支持按决策结果（而非仅按性能）切片分析。设计上区分「什么该进 DB（完整 payload，供事后复盘）、什么该进 span 属性（低基数摘要，供实时过滤）」。
5. **埋点暴露隐藏 bug 的正反馈**：章节团队 `try/except` 静默回退是反模式——失败被吞掉，卖点功能默默失效。埋点把 ERROR span 打出来，1406 才浮出水面。**埋点的价值不只是看性能，是把吞掉的异常显性化**。
6. **列类型 vs 截断的取舍**：章节 draft 是「审计快照」，完整性有价值，所以治本走改列类型（MEDIUMTEXT），截断只在病态超长兜底——不为了省事只加截断让审计节点变残缺。区分「该完整存的（draft）vs 本就该截断的（L2 raw）」。

## 五、潜在问题

1. **BatchSpanProcessor 超时丢 span**：实测日志有 `Failed to export span batch ... cloud.langfuse.com Read timed out (read timeout=9.99s)`。大批量 span（一次 ULTRA 几百个）导出偶发超时，可能导致部分 span 在 Langfuse 丢失。**span 本身没丢，只是这次 batch 导出失败**——可考虑调大 `BatchSpanProcessor` 的 export timeout，或加 `SimpleSpanProcessor`（每 span 单独导出，代价是吞吐降）。
2. **多轮决策 bug 暴露后未修（已知问题）**：M3 / M2 埋点暴露了 `max_conduct_count=6` 与一轮规划上限撞车——一轮规划满 6 个 conduct 任务，`conduct_count >= max_conduct_count` 立刻触发预算耗尽 break，reviewer 全票 continue 也进不了第 2 轮。**ULTRA 动态多轮补强实际只在「第 1 轮规划不满 6 个」的题上生效**，否则永远只 1 轮。这是预算配比设计问题，改 budget 会动性能红线，需单独决策。
3. **trace_id 与 research.id 易混淆**：Langfuse trace_id 是 OTel 随机生成的 128 位（显示成 32 hex），`research.id`（session id）是设在每个 span 的 `research.id` 属性上。要按研究查 trace 得按属性过滤，不能直接用 research.id 当 trace_id 查。可考虑设 Langfuse `session.id` 属性 = research.id，让 UI 的 Sessions 页也能聚合。
4. **章节团队 `try/except` 静默回退是反模式**：即使修了 1406，`report_team.run` 整体 except 的设计仍在——任何子步骤抛异常都会静默回退 fallback，trace 上只表现为「少了 Consistency / Revise / Merge span + 多了多角度起草 span」，不显眼。建议：失败时在根 span 打显式 `report.fallback=true` 属性或 ERROR event，让「走了 fallback」一眼可见。
5. **SearchAgent 网页摘要偶发 ERROR**：trace 里偶有 `invoke_agent SearchAgent-researcher-N:page` ERROR（Tavily / 网页超时），被 Researcher 容错吞掉。不影响研究 COMPLETED，但可观测上应把「这一轮有几个网页摘要失败」聚合成 span 属性（如 `search.failures.count`），否则要手动数 ERROR span。
6. **MEDIUMTEXT 迁移没覆盖所有长文本列**：`metadata_json`、`payload_json`（decision log 完整 decision）等仍是 `TEXT`，如果将来 decision payload 或 claim metadata 暴涨，可能在别处再现 1406。本次只改了确定会超的 content 列，没做全表扫描。可补一个「所有存大文本的列统一 MEDIUMTEXT」的清理任务。
7. **观测本身没有采样**：原版 `TracerProvider` 用默认 `ParentBased / AlwaysOn`，不采样。一次 ULTRA 几百个 span 全量导出，量大且贵。生产环境应加采样率（如 `TraceIdRatioBased(0.1)`），但开发期全量是合理的。这是「默认配置合理但生产前要调」的点。

## 六、验证 trace

- 第一次 ULTRA（旧代码基线 + M1–M5 新代码）：trace `0c4d3407a4ee963dee476178a21334f9`，session `5e94fe80cd154c89ad2de18cb8735825`。章节团队 6 个 draft 全 1406 ERROR，回退 fallback。新 span 框架在，属性全设上。
- 第二次 ULTRA（bug 修复后）：trace `1637ec18bb2fc28033c4354aa32de785`，session `9590a24c89c94c72b240d98ff001f769`。章节团队 Plan → Draft×6 → Consistency → Revise×6 → Merge 全跑通，根 span level=DEFAULT 无 error。`UltraDynamicReview` 决策属性（next.action=continue / votes=3 / score.evidence=1 / gaps=5）、`UltraReportGate`（quality.status=needs_disclosure / gaps=6）均可见。
