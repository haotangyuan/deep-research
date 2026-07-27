# 简历逐行拷打讲义（面试官视角）

> 目标：让你**完完全全懂**这个项目，扛住面试官对简历每一行的追问。
> 标靶：README:105-114「简历项目描述（协作维护）」五条 bullet，外加 README:45-63 三档对照表、README:69-73 冷启动实测。
> 每条结构：原文 → 在卖什么 → 面试官会问 → 参考答案 → 代码/数字支撑 → 反向风险。
> 所有 file:line 均已对照代码核验。**最硬的拷打点在第2条（max_conduct_count bug）和第4条（CAS 真相 + resume 字符串匹配）**——这两条决定面试成败。

---

## 简历第1条：分层架构设计

**原文**（README:110）：
> 将系统拆分为外层业务状态机与内层 Agent 运行时；`AgentPipeline` 负责 MySQL/Redis 状态一致性、HITL 和断点恢复，AgentScope 负责 Agent 生命周期、任务上下文、工具调用与认知执行，避免将业务事务和前端协议耦合进 Agent 框架。

### 这一条在卖什么
一句话：**业务状态机和 AI 认知执行分层**。外层 `AgentPipeline` 只管"研究进行到哪一步了"这种产品状态（MySQL 存、可恢复、可 HITL 暂停）；内层 AgentScope 只管"怎么思考、调什么工具"这种认知执行。两层各管各的，不让数据库事务和前端 SSE 协议被塞进 Agent 框架里。

### 面试官会问

**Q1：为什么要这么分？直接用一个框架（比如 LangGraph）管状态不香吗？**
- 业务状态（QUEUE→SCOPE→HITL→IN_RESEARCH→IN_REPORT→COMPLETED）是**产品语义**，要进 MySQL、要断点恢复、要给前端 SSE 回放。这些是**强一致性需求**，属于业务事实来源。
- Agent 框架的会话状态是**运行时临时态**，崩了可以重算。
- 如果让框架管业务状态，等于把"MySQL 事务、SSE 协议、前端字段命名"全耦合进框架内部——换框架就全崩，且框架的会话模型不适合做持久化事实来源。
- 所以刻意分：框架不做业务事实来源，业务状态机不碰认知执行。

**Q2：AgentScope 在你这到底干了什么？别只说"管理 Agent 生命周期"。**
- 长生命周期 Agent（按研究会话复用 Scope/Supervisor/Researcher/Search/Report，不是每次调用临时起一个）。
- 隔离 `AgentState`（每个 Worker/每个网页摘要独立状态，防并发互相污染）。
- `ContextConfig` 上下文压缩（trigger_ratio=0.8, reserve_ratio=0.1，自动裁上下文窗口）。
- 原生 `TaskContext`/`Task` 承载任务状态（Leader 把任务写进 tasks_context，Worker 读）。
- Leader/Worker 团队 + Middleware（计数 reply/reasoning/acting/model_call、强制单次工具预算）+ Toolkit（ReAct 循环、权限）+ 原生 tracing。

**Q3：你说"不调框架黑盒"，具体怎么证明你没把状态全丢给 AgentScope？**
- 项目自己写了 `AgentScopeResearchTeam`（`app/application/research_team.py:17`，单例 L152）——这是**项目自研的 Team 协调器**，不是直接调 AgentScope 私有 Team。
- 调度：L47 `asyncio.Semaphore(concurrency)` + L85 `asyncio.gather(*(run_task(task) for task in tasks))`，concurrency 就是 budget 的 max_concurrent_units（MEDIUM/HIGH/ULTRA = 1/2/3）。
- 稳定 Worker ID 来自 AgentScope 原生 `Task.worker_id`（L26/29/138 `"workerId": task.worker_id`）——用框架原生的，不自造。
- 这正支撑 backend README:36 那句"只使用 AgentScope 公共 API，不依赖 `agentscope.app._*` 私有 Team 实现"。

**Q4：状态机具体长什么样？状态枚举背一下。**
- 13 个状态（`app/core/constants.py:1-13`）：NEW、QUEUE、START、IN_SCOPE、NEED_CLARIFICATION、AWAITING_DIRECTION_CONFIRM、IN_RESEARCH、IN_REPORT、COMPLETED、FAILED、CANCELLED、ARCHIVED。
- WorkflowMode（constants:16-18）：`fixed` | `ultra_dynamic`。
- 骨架（README:48）：QUEUE → SCOPE → HITL（可选）→ IN_RESEARCH → IN_REPORT → COMPLETED。

### 参考答案要点 + 别踩的坑
- ✅ 答"分层"时要给出**两层的职责清单**，而不是泛泛"解耦"。
- ✅ 被问 AgentScope 干什么，要能说出 6 件事（生命周期/隔离状态/压缩/TaskContext/团队/Middleware-Toolkit-tracing）。
- ⚠️ **坑**：别说"AgentScope 管所有状态"——它只管运行时态，业务状态在 MySQL。这点说错就穿。
- ⚠️ **坑**：别说"我们没用框架的 Team"——是**自研 Team 协调器包了框架原生 Task**，不是不用。措辞要准。

### 代码/数字支撑
- 状态机：`app/application/pipeline.py`（`AgentPipeline` 类）+ `app/core/constants.py:1-13`（状态枚举）。
- 自研 Team 协调器：`app/application/research_team.py:17`（`AgentScopeResearchTeam`），L47 Semaphore、L85 gather、L26/29/138 worker_id。
- AgentScope 集成：`app/infrastructure/agentscope_runtime.py`（`AgentScopeRuntimeSession` L101 team_state、L106-112 ContextConfig、L134-159 Task、L46-88 ResearchRuntimeMiddleware）。
- 边界声明：backend README:36「只使用 AgentScope 公共 API，不依赖 `agentscope.app._*` 私有 Team 实现」。

### 反向风险（被问到极限怎么诚实答）
**Q：你这分层，AgentPipeline 和 AgentScope 之间没有 race 吗？**
- **诚实答**：有窗口。pipeline 内部状态写 `update_research_session`（pipeline.py:651）是**无状态守卫的普通 UPDATE**，它依赖"一旦任务出队，pipeline 是唯一写者"这个假设。但用户 `cancel_research`（services.py:548）能在这窗口期并发写——cancel 是带守卫的（`WHERE status NOT IN('COMPLETED','FAILED','CANCELLED')`），pipeline 侧无守卫。最终靠 pipeline 的 `is_cancelled`（agents.py:1509，读 DB 状态）兜底观测到取消。所以**有短暂 race，但收敛**。这不是 bug 是已知取舍——为了 pipeline 内部迁移不每次都带守卫（性能）。

**Q：那为什么 pipeline 内部不也加 CAS？**
- 因为单写者。出队后只有一个 worker 在跑这个 research，内部状态迁移不需要乐观锁，加守卫是浪费。CAS 只放在**用户能并发触发**的入口（启动研究、确认方向、取消）。

---

## 简历第2条：动态工作流设计 ⚠️ 最危险的一条

**原文**（README:111）：
> 实现 MEDIUM、HIGH、ULTRA 三档研究策略；ULTRA 在需求澄清阶段识别研究类型并选择 JSON 编排模板，由模板控制研究轮次、任务预算、Reviewer 视角和报告策略。每轮由 Supervisor 根据上一轮证据缺口重新规划任务，多 Reviewer 从覆盖度、证据质量、时效性、来源多样性和一致性进行对抗评审，投票决定继续补强或进入报告，最后通过章节 Agent、一致性 Agent、修订 Agent 和 ClaimVerifier 完成协作式报告生成。

### 这一条在卖什么
一句话：**ULTRA 档会"多轮动态研究 + 对抗评审 + 章节团队协作报告"**，不是固定流程。研究类型识别→选模板→每轮 Supervisor 按证据缺口重新规划→多个 Reviewer 从 5 个维度对抗投票（continue/report）→章节团队出报告。这是简历最高光也**最危险**的一条——因为有个已知 bug。

### 面试官会问

**Q1：三档到底差在哪？别只说"强度不同"。**
- MEDIUM：单轮规划，Supervisor 最多 2 任务，Worker 并发 1，每分支 2 次搜索，报告单 ReportAgent。
- HIGH：单轮规划，最多 4 任务，Worker 并发 2，每分支 3 次搜索，报告 comparative+data-driven 双视角并行起草→high-synthesis 单次融合（不带 Judge）。
- ULTRA：每轮动态规划，模板最多 6 任务，Worker 并发 3，每分支 4 次搜索，报告走章节团队。
- 数字全在 `app/core/config.py:82-90`。

**Q2：ULTRA 怎么"识别研究类型选模板"的？**
- ScopeAgent 在写 research brief 的同一个 LLM 调用里顺带做意图识别（`agents.py:189-234`，解析 researchType/typeConfidence/typeReason/typeCandidates，clamp 到 RESEARCH_TYPES 集合 `workflow_template.py:13-20`：tech_comparison/market_analysis/academic_review/fact_lookup/trend_forecast/general）——**不额外花一次 LLM 调用**，这是"借鉴点 E"。
- 选模板 `select_template`（`workflow_template.py:227`）：仅当 research_type≠general **且 confidence≥0.7 且文件存在**才用 type-specific 模板，否则 `ultra_default.json`。
- 模板 override `dynamic_max_rounds`（默认 5）和 budget。

**Q3：多 Reviewer 对抗评审具体怎么投票？**
- `UltraDynamicRoundCoordinator._adversarial_review`（`ultra_dynamic.py:442-573`），借鉴 CC Adversarial Verify 思路：**default-toward-refute**（默认偏向"停止"），需要 ≥ threshold 的 continue 票才继续。
- lenses 默认 `["evidence_sufficiency","source_authority","coverage_completeness"]`（L37-53），count=3，continue_threshold=2（`workflow_template.py:119 min(2,count)`）。
- 并行跑（`asyncio.gather`，L516），LLM 不返回则默认 nextAction="report"（L489）。
- 聚合：`continue_count`，`next_action="continue" if continue_count>=threshold else "report"`（L522）。
- 分数跨 reviewer 取 **min（短板原则）**（L531-538）——一个 reviewer 给低分就拉低整体，防短板被平均掩盖。
- 决策结果三处落盘：MySQL `research_decision_log` + SSE 事件 + trace span 属性（review.next.action/votes/score.*）。

**Q4：章节报告团队那条链背一下。**
- `ReportSectionPlanner`（3-6 章节）→ 并行 `ReportSectionAgent:{section_id}`（每个独立 L0 召回→L1 精排→L2 按 parent_path 下钻→起草→发共享 claim）→ `ReportConsistencyAgent`（读全部草稿+共享 claim+请求，生成定向 mailbox 消息）→ 并行 `ReportSectionReviser:{section_id}`（读自己 mailbox+他人共享 claim）→ `ReportAgent:merge`（只合并/消重/统一术语，**不研究、不引新事实**）。
- mailbox 有界单轮（消息类型 evidence_request/response/conflict_detected/terminology_update/section_dependency/review_request）——**刻意反死循环**，不是无限制 Agent 自由聊天。

**Q5（杀手锏）：你 ULTRA 实际跑了几轮？**
- **必须诚实答**：默认配置下，**ULTRA 实际只跑了 1 轮**，动态多轮退化成单轮。这是已知 bug（记忆 `ultra-budget-multi-round-bug`，文档 `observability-ultra-improvement.md §五.2` 原文确认）。

### 参考答案要点 + 别踩的坑
- ✅ 三档差异要背数字（任务 2/4/6、并发 1/2/3、搜索 2/3/4）。
- ✅ 对抗评审要说出"default-toward-refute + threshold + 短板原则 min"。
- ⚠️ **最大坑**：别说"ULTRA 会多轮补强"——默认配置下不会。这条简历措辞（"每轮由 Supervisor 根据上一轮证据缺口重新规划"）在默认配置下是**理想态，非现实**。面试官懂行一问就穿。
- ⚠️ 章节团队默认 **不开**（`report_section_team_enabled` 默认 False，`workflow_template.py:203`），要模板 `report.sectionTeamEnabled=true` 才开。README:73 那行"5 章节 Agent+Consistency+5 Reviser+merge+ClaimVerifier"是开了之后的产物。

### 代码/数字支撑
- 三档预算：`app/core/config.py:82-90`（conduct 2/4/6、search 2/3/4、concurrent 1/2/3）。
- 意图识别：`app/application/agents.py:189-234`；模板选择 `app/application/workflow_template.py:227`。
- 对抗评审：`app/application/ultra_dynamic.py:442-573`，lenses L37-53，gather L516，聚合 L522，短板 min L531-538。
- 章节团队：`app/application/report_team.py:210 ReportSectionTeam`（单例 L741）；特性门 `workflow_template.py:197-203`。
- ClaimVerifier：`app/application/agents.py:1400 verify_report_claims`，cap 8 claims（L1416），evidence 8000 chars（L1412-1413），标 `[未验证]`/`[缺来源]`。

### 反向风险（命门中的命门，必须能讲清）

**Q：max_conduct_count=6 这数字有什么问题？**
- **完整机制要能讲**：`budget.max_conduct_count` 被**三重使用**：
  1. Supervisor 单轮规划任务上限：`agents.py:361 max_count=max(1,max_conduct_count)`，`if len(tasks)>=max_count: break`（L369）。
  2. per-branch 执行 slot 计数：`_reserve_conduct_slot`（agents.py:519-523）`if conduct_count>=max_conduct_count: return False; conduct_count+=1`，每个任务执行调一次（L450）。
  3. 跨轮预算门：`pipeline.py:536 if conduct_count>=max_conduct_count: break`。
- **致命点**：`state.conduct_count` 在 **parent state 递增**（agents.py:522），**轮间从不重置**（全仓库 grep 找不到 `conduct_count=0` 的赋值），而且 `fork_for_research`（state.py:148-190）根本不带 conduct_count 进子状态。
- **后果**（默认 ULTRA conduct=6 并发=3 max_rounds=5）：轮 1 规划满 6 任务→每个执行时 `_reserve_conduct_slot` 把 conduct_count 从 0 涨到 6→轮 1 末 reviewer 全票 continue→轮 2 循环顶部 pipeline.py:536 `6>=6` 为真→**直接 break，轮 2 都不规划**。`dynamic_max_rounds=5` 永远到不了。
- **ULTRA 动态多轮补强实际只在"第 1 轮规划不满 6 个"的题上生效**，否则永远单轮。

**Q：这怎么修？**
- 两个方向：① 每个动态轮**开头重置** `state.conduct_count=0`；② 把预算**拆成 per-round max_tasks** 和 **max_total_conducts** 两个独立值（现在代码混用）。
- 注意 `ultra_dynamic.py:238-241` 那个 `can_continue = dynamic_round_no < max_rounds and conduct_count < max_conduct_count` 只在 **fallback 启发式**决策里用，**不在真 reviewer 路径里**，救不了。

**Q：那 README:73 那个"5 章节 Agent+Consistency+5 Reviser+merge+ClaimVerifier"是怎么来的？**
- 那是冷启动实测（README:69-73）一次**开了章节团队**的 ULTRA 跑出来的报告阶段产物，跟"多轮"是两码事。报告阶段的章节团队是能跑的（1406 bug 已修，见下面），但"研究阶段多轮补强"在默认配置下是 1 轮。**两者别混**。

**面试策略**：主动说"这里有个我后来用可观测性 span 发现的 bug"——把弱点变成亮点（你懂埋点、懂根因、懂取舍），比藏着等被问穿强 10 倍。

---

## 简历第3条：上下文与证据治理

**原文**（README:112）：
> 设计 Research Context FS，将网页材料拆分为 L0 摘要、L1 概览、L2 原文，并沉淀分支结论和结构化 evidence；报告阶段按章节和预算检索证据，解决长任务上下文膨胀、来源难追溯和一次性 Prompt 过长问题。

### 这一条在卖什么
一句话：**用"文件系统"思路管理研究上下文**。网页材料不一次性塞进一个超大 prompt，而是按路径 `research://{id}/...` 存成三层节点（L0 短摘要/L1 结构化概览/L2 截断原文），报告阶段按章节和字符预算去检索需要的部分。解决三个老问题：上下文膨胀、来源难追溯、一次性 prompt 太长超时。

### 面试官会问

**Q1：L0/L1/L2 分别存什么？为什么不一层？**
- L0 `source_abstract`：短召回摘要（≤400 chars），让章节 Agent 不加载 L2 就能过滤来源。
- L1 `source_overview`：结构化概览（≤2500 chars），精排层，够起草大部分章节。
- L2 `source_raw`：截断原文（≤12000 chars），仅 L1 不足时按 parent_path 下钻。
- 三层而非一层：L0 廉价广召回→L1 精排→L2 按需下钻，把 L2 排除出热 prompt 路径，省 token。

**Q2：报告阶段怎么"按章节和预算检索"？**
- `ReportSectionTeam._retrieve_section_context`（`report_team.py:368-441`）：
  1. 建 TypedQuery（priority 5, context_type=SOURCE_ABSTRACT）。
  2. L0 召回：`rank_nodes_for_query[:12]`，取命中的 parent_path。
  3. L1 池：按 parent_path 过滤（只留"被 L0 召回的来源"的 overview），`[:6]`。
  4. evidence：`[:10]`。
  5. **needs_deep_raw**：query 含 数字/比例/时间/引用/冲突/风险/数据/规模/对比 **或** evidence<3 → 每 L1 调 `store.read_raw_for_parent(parent_path, raw_limit=max(200, 1200))` 读 L2。
  6. final = evidence+l1+l0 dedup by path + raw 追加。
- 预算：每章节 ≤8000 chars（`RESEARCH_CONTEXT_SECTION_MAX_CHARS`），整报告 ≤40000（`RESEARCH_CONTEXT_REPORT_MAX_CHARS`）。

**Q3：你怎么知道某条证据来自哪个网页？来源怎么追溯？**
- 每个节点带 `metadata={"url","score"}`，路径 `research://{id}/branches/branch-{idx:03d}/sources/{source_key}`。`source_key` 由 `stable_source_key(url)`（`domain/context.py:136`）生成，稳定可复现。报告里保留 `research://` 路径和 URL（merge prompt 明确要求"保留所有数字/限定词/URL/research://路径"）。

**Q4：为什么不用向量库做 RAG？**
- 刻意轻量。检索是**词法 BM25-ish 打分**，不是 embedding：`score_context_text`（`context_store.py:35`）+ `normalize_query_terms`（ASCII 词 + 中文 bigram，L24-32）。打分：title +1.5 / section_hint +1.0 / content +0.5 / source_strength high+0.5 medium+0.2 / type 匹配 +0.8。
- 理由：研究规模下关键词+结构化路径已够，且**可追溯**（向量检索召回的东西不好解释"为啥这条命中"），路径化的节点可点对点追。

### 参考答案要点 + 别踩的坑
- ✅ 三层字符上限要背：L0=400 / L1=2500 / L2=12000，外加 RAW_EXCERPT=1200（报告时单来源 prompt 安全边界，**不是 L2 持久化上限**）。
- ✅ 要说清 RAW_EXCERPT=1200 ≠ L2_MAX_CHARS=12000：前者是报告时读 L2 的单次摘录上限，后者是 L2 节点持久化上限。
- ⚠️ **坑**：别说"L2 存原文"——**L2 写入即截断，>12000 chars 的原文不保留**。面试官问"有信息丢失吗"要诚实说"有，超过 12K 的原文丢了"。
- ⚠️ **坑**：别说"用了向量检索/语义召回"——是词法打分。说错就穿。

### 代码/数字支撑
- 节点类型：`app/domain/context.py:17-32`（13 种 ContextNodeType）、L10-14（ContextLevel L0/L1/L2/derived）、L35-51（路径 scheme）、L136（stable_source_key）。
- 写：`app/application/context_writer.py:19-72 build_source_context_nodes`（L42 L0/L54 L1/L66 L2，全 truncate）、L147 `write_branch_package_context`（BRANCH_SUMMARY + 每 EvidenceItem 一个 EVIDENCE）。
- 检索：`app/application/context_retrieval.py:39-58 rank_nodes_for_query`；`app/infrastructure/context_store.py:35 score_context_text`、L24-32 normalize_query_terms、L142-154 read_raw_for_parent。
- 报告下钻链：`app/application/report_team.py:368-441`（L391 取 parent_path、L392 L1 过滤、L407 read_raw_for_parent、L410 raw_path）。
- 预算：`app/application/report_context.py:20 build`、L45 section 8000、L62 report 40000、L91 should_expand_raw。
- 字符上限：`app/core/config.py:50-56`。
- 表：MySQL `research_context_node` + `research_context_edge`（`app/domain/models.py`），content=MEDIUMTEXT(16MB)（L178），报告写 truncate 3M 兜底（`report_team.py:674`）。

### 反向风险

**Q：网页摘要的 AgentState 为什么不进 checkpoint？**
- 两原因（`性能与可观测性.md §6`）：① 网页正文巨大且已存 L2，再复制进 Redis checkpoint 会撑爆 Redis；② 独立 AgentState 防并发网页摘要互相继承上下文。
- 实现（`agentscope_runtime.py:161-179`）：snapshot 显式跳 `key.startswith("SearchAgent:")` 的 entry。

**Q：这个排除机制有什么风险？**
- **脆弱契约**：靠**字符串前缀**匹配。runtime key 格式 `f"{stage}:{instance}:{signature}"`（`llm.py:187-196`），SearchAgent 的 stage="SearchAgent"（agents.py:961）故匹配。但**将来任何 stage 名以 "SearchAgent:" 开头的 agent 会被误排除**。这是技术债，诚实说。

**Q：1406 bug 是什么？跟这条有什么关系？**
- `research_context_node.content` 最初是 TEXT(64KB)。章节草稿超长 → MySQL 抛 `DataError (1406) Data too long for column 'content'`。
- `ReportSectionTeam.run` 顶层有 `try/except` **吞掉**了异常 → **静默回退到多角度起草**。结果章节团队"从来没真正成功跑过"，直到可观测性 span 暴露 1406 ERROR 才发现。
- 修：content + chat_message.content 改 MEDIUMTEXT(16MB)（ALTER TABLE）+ `_write_text_node` 加 `truncate(content, 3_000_000)` 兜底（4MB utf8mb4 安全裕量）。
- 这是"埋点暴露吞掉的异常"经典案例——**面试金句**：可观测性的价值就是让静默失败变可见。
- ⚠️ 遗留：try/except 静默回退模式仍在；metadata_json/payload_json 还是 TEXT（64KB），可能别处复发 1406。

---

## 简历第4条：可靠状态恢复与 HITL 交互 ⚠️ 第二危险

**原文**（README:113）：
> 设计两层 HITL 机制：研究开始前支持方向 `APPROVE / REVISE`，根据用户反馈重新生成 research brief；ULTRA 研究过程中支持追加关注章节、证据补强方式和备注，并在不中断当前轮的情况下作为下一轮规划偏置生效。通过 MySQL CAS 状态迁移、Redis Checkpoint、AgentScope runtime snapshot 实现任务续跑和异常恢复，并使用 Redis ZSet、SSE、`Last-Event-ID` 支持实时进度与断线重放。

### 这一条在卖什么
一句话：**HITL + 断点恢复 + SSE 续传**。两层人机交互（研究前确认方向、ULTRA 过程中追加干预）+ 三层恢复（MySQL CAS 状态迁移 + Redis Checkpoint + AgentScope runtime snapshot）+ 实时进度（Redis ZSet 时间线 + SSE + Last-Event-ID 断线重放）。

### 面试官会问

**Q1：两层 HITL 分别是什么？**
- 第一层（方向确认）：`IN_SCOPE` 完成后 suspend 在 `AWAITING_DIRECTION_CONFIRM`，用户 POST `action=APPROVE|REVISE` + feedback。APPROVE→IN_RESEARCH（跳过 scope）；REVISE→回 IN_SCOPE 带 feedback 重分析。
- 第二层（轻干预，仅 ULTRA）：研究过程中 POST 追加 focusSections(≤3)/reinforceModes(≤2, enum official/data/comparison/latest)/note(≤500)。**不中断当前轮**，作为**下一轮 planner 偏置**生效（applyMode="next_round_planner_bias"）。

**Q2：MySQL CAS 状态迁移——具体 SQL 长什么样？**
- **必须答到 SQL 层**。真正 CAS 在 `app/application/services.py` 两处，都是**单条 UPDATE + WHERE status IN(...) + rowcount 检查，无重试 fail-fast**：
  - `_cas_update_to_queue`（L659-673）：`UPDATE research_session SET status='QUEUE', update_time=NOW() WHERE id=:id AND user_id=:user_id AND status IN ('NEW','NEED_CLARIFICATION','AWAITING_DIRECTION_CONFIRM','FAILED','CANCELLED')`。rowcount==0 → `send_message` 抛 `ResearchError("启动研究异常")`（L350）。
  - `_cas_confirm_direction`（L675-689）：`UPDATE ... SET status='QUEUE' WHERE ... AND status='AWAITING_DIRECTION_CONFIRM'`。rowcount==0 → 抛 `ResearchError("确认操作失败")`（L517）。
- **关键澄清**：pipeline 内部迁移 `update_research_session`（pipeline.py:651）是**无守卫普通 UPDATE**，不带 status 条件——因为出队后 pipeline 是单写者。CAS 只在**用户能并发触发的入口**。简历说"MySQL CAS 状态迁移"指的就是 services.py 这两处。

**Q3：Redis Checkpoint + AgentScope runtime snapshot 怎么配合？**
- `save_workflow_checkpoint`（pipeline.py:687-691）：先 `model_handler.snapshot(research_id)` 把 AgentScope runtime 拍进 `state.agent_runtime_snapshot`，再 `get_cache().save_checkpoint(research_id, state.model_dump())`。
- TTL=24h（`CHECKPOINT_TTL_SECONDS`，cache.py:21）。COMPLETED 时删（pipeline.py:364）。
- 装载：`_state_from_checkpoint`（pipeline.py:267）从 checkpoint 重建 state；没有则 `_new_state_from_history`（L276）从聊天历史重建。

**Q4：SSE 断线重放具体怎么做的？Last-Event-ID 怎么用？**
- 每个事件写 MySQL（ChatMessage/WorkflowEvent 行）**同时**写 Redis ZSet `research:{id}:timeline`，score=sequence_no（单调递增），`ZADD` + `EXPIRE 30min`（`cache.py:157-164`）。
- seq 来自 `SequenceUtil.next`（cache.py:29-47）：DB `SELECT MAX(sequence_no) FROM (chat_message UNION ALL workflow_event)` 起播 + per-research `asyncio.Lock` 自增。
- 连接（`api/research.py:24`）：读 `Last-Event-ID` header → `sse_hub.connect` → `_replay_if_needed`（sse.py:85-105）→ `get_timeline(research_id, last_seq)`（cache.py:147-155）`ZRANGEBYSCORE {last_seq+1} 214748363647`。
- 兜底：ZSet 空或被 evict → `load_from_db`（cache.py:181-214）从 MySQL 全量重建 ZSet 再过滤 `sequence_no > last_seq`。
- 心跳：`_event_generator`（sse.py:29-46）`asyncio.wait_for(queue.get(), 30)` 超时发 heartbeat 注释（sse-starlette 渲染成注释行）。`EventSourceResponse(generator, ping=None)` 关掉框架默认心跳，自己 30s 心跳。
- **测试不 mock sse-starlette**（直接构造 EventSourceResponse）。

### 参考答案要点 + 别踩的坑
- ✅ CAS 要给 SQL 原文，不是泛泛"乐观锁"。
- ✅ 说清 CAS 在 services.py（用户入口），pipeline 内部是无守卫（单写者）。
- ✅ ZSet score=sequence_no + 30min TTL + DB 兜底重建，三件套。
- ⚠️ **坑**：简历说"CAS 状态迁移"，但 **pipeline 内部迁移不是 CAS**。如果面试官问"状态迁移都走 CAS 吗"，诚实答"只有用户入口那两处是 CAS，pipeline 内部靠单写者假设不做 CAS"。
- ⚠️ **坑**：`VERIFY_REVISE` 旗标——HITL 契约文档里**没有**这个旗标，文档流是 action:APPROVE|REVISE+feedback。CLAUDE.md 提到的 `VERIFY_REVISE=false` 是 **smoke 测试开关**（`live_hybrid_workflow_smoke.py` 用，只验 HITL 批准分支不重复验修订），不是业务契约。面试官问就说"契约是 APPROVE/REVISE，VERIFY_REVISE 是测试开关"。

### 代码/数字支撑
- HITL 第一层：`app/application/services.py:675 _cas_confirm_direction`、L515 confirm_direction；pipeline.py:389-407 HITL 暂停。
- HITL 第二层（轻干预）：`app/application/interventions.py:63 ACTIVE_INTERVENTION_STATUSES`、L83 normalize_intervention_request（focus≤3/modes≤2/note≤500）、L245 create_or_replace_pending_intervention（`SELECT...WITH FOR UPDATE` 原子 supersede）；`app/application/agents.py:402-437 _activate_intervention_for_round`、L298-311 注入 planner、`interventions.py:296 mark_intervention_applied`。
- CAS：`app/application/services.py:659/675`；pipeline 无守卫写 pipeline.py:651。
- Checkpoint：`app/application/pipeline.py:687-691`、`app/infrastructure/cache.py:21`（TTL 24h）。
- ZSet timeline：`app/infrastructure/cache.py:157-164`（ZADD+EXPIRE 30min）、L29-47 SequenceUtil、L147-155 get_timeline、L181-214 load_from_db。
- SSE：`app/api/research.py:24`、`app/infrastructure/sse.py:19 connect`、L85-105 _replay_if_needed、L29-46 _event_generator。

### 反向风险（第二命门）

**Q：CAS race window 多大？**
- SELECT-for-display 和 UPDATE 之间**未加锁**。用户可能看到过期的"AWAITING"UI，提交时被 `rowcount==0` 拒。可接受——因为一旦进 QUEUE，pipeline 是唯一写者。

**Q：FAILED/CANCELLED 的研究能 resume 吗？**
- 能。`_cas_update_to_queue` 的 status IN 列表**包含 FAILED 和 CANCELLED**（services.py:667）。所以发新消息能把失败/取消的研究重新入队。
- resume 路径 `_build_resume_state`（services.py:390）先试 checkpoint，没有则 `_hydrate_resume_state_from_events`（L490）从 WorkflowEvent 行重建——**靠字符串匹配事件标题**"已制定研究计划"/"已拆解研究任务"/"已完成该主题研究"判断研究进行到哪步。
- **脆弱契约**：事件标题是中文硬字符串，改了就 resume 失败。诚实说这是债。

**Q：崩溃恢复具体怎么做的？能从中点续跑吗？**
- 启动时 `ResearchTaskQueue.start(recover=True)`（pipeline.py:74）→ `_recover_interrupted_tasks`（L153）：① `_fail_interrupted_running_tasks`（L174-198）把 START/IN_SCOPE/IN_RESEARCH/IN_REPORT 批量标 FAILED + ERROR 事件"服务重启导致任务中断"；② `_load_queued_states` 把 QUEUE 会话从 checkpoint 或历史重建后重入队。
- **限制：不能从阶段中点续跑，只能整阶段回退**。比如 IN_RESEARCH 崩了，resume 是**重跑整个 IN_RESEARCH 阶段**，不是接着上次的第 N 个搜索继续。文档 `report-section-agent-team.md §当前边界` 原话："当前异常恢复仍以整个 ReportAgent 阶段回退为主，尚未从单个章节修订节点续跑。"

**Q：ZSet 和 DB 会不一致吗？**
- 会。ZSet 30min TTL，DB 永久。30min 不活跃后连接，`get_timeline` 发现 ZSet 空 → 从 DB **全量**重建（cache.py:181-214）→ 再过滤。
- **冷回放是 O(总事件数)**，不是 O(漏掉事件数)。研究很长、事件很多时冷回放慢。诚实说。

**Q：temp_event 会重放吗？**
- **不会**。`publish_temp_event` 写 `sequence_no=-1`（cache.py:131-145），**不入 DB**，只进 Redis ZSet（score -1）。而 `get_timeline(research_id, 0)` 是 `ZRANGEBYSCORE ... 1 214748363647`（cache.py:148），-1 score 的被排除。所以 ZSet 过期或 DB 回放时 temp_event 消失——**真正临时**，用于队列位置通知。

---

## 简历第5条：性能与全链路可观测性

**原文**（README:114）：
> 通过研究任务并发、`LLM_MAX_CONCURRENCY=2`、搜索/摘要 TTL 缓存、in-flight 合并和超时降级控制耗时；三档冷启动实测约为 6/12/25 分钟，并使用 OpenTelemetry + Langfuse 贯通 workflow、Agent、model、tool 链路以定位性能瓶颈和异常。

### 这一条在卖什么
一句话：**性能护栏 + 全链路可观测**。一堆并发/缓存/超时/降级手段控耗时（实测 6/12/25 分钟），再用 OpenTelemetry+Langfuse 把 workflow→agent→model→tool 四层 span 串起来定位瓶颈和异常。

### 面试官会问

**Q1：LLM_MAX_CONCURRENCY=2 为什么这么小？**
- 全局 LLM 账户级 Semaphore（`llm.py:290-296`），keyed `base_url|model|sha1(api_key)[:12]`，limit=2。**所有 agent 共享这 2 个并发槽**（研究、Reviewer、章节起草与修订共享账户级限流）。
- 小是为了不把模型 API 打到限流。ULTRA 真正并发的不是 LLM 调用数，而是**研究分支并发**（max_concurrent_units=3），但每个分支要调 LLM 时共享这 2 个槽。

**Q2：in-flight 合并具体怎么做的？**
- SearchAgent 摘要缓存 keyed `(url.lower(), hash(content))`（agents.py:922-950），TTL 60min，max 1024 entries。**inflight future dedup**——同一网页并发摘要请求共享一次 LLM 调用（一个 future，其他等结果）。
- agent.instance 标 `f"{worker_id}:page:{sha1[:12]}"`（agents.py:972-974）做可观测区分。
- Tavily 搜索也有缓存（`tavily.py`，TTL 60min，max 512 entries，normalized-param cache key）。

**Q3：超时降级链？**
- SearchAgent `_action`（agents.py:895-913）：`parallelism=min(len(results), 4)`，每个 `summarize_one` 包 `asyncio.wait_for(..., timeout=60+5=65s)`，try/except 失败回退 Tavily raw abstract。
- `_summarize_webpage`（agents.py:952-969）：`truncate(content, 12000)` → SUMMARIZE_WEBPAGE_PROMPT，LLM 调用 `llm.timeout.seconds` override=60。异常→返回 `truncate(content, 1200)` 兜底。
- LLM 瞬态重试 `_run_agent_with_transient_retries`（llm.py:144）：匹配 `_TRANSIENT_RETRY_PHRASES`（rate limit/too many requests/service unavailable/server overloaded/concurrency limit exceeded/temporarily unavailable），指数退避 `initial_delay*2**(n-1)` capped max_delay=20s，max_attempts=3。

**Q4：可观测四层 span 怎么串的？**
- 单一全局 TracerProvider（`observability.py:28-36`，app 和 AgentScope `TracingMiddleware` **读同一个 provider**），所以 AgentScope 原生 span 自然成应用 span 子节点，**不是事后拼接**。
- 链：`deep_research.workflow`(root) → `deep_research.stage {AgentName}` → AgentScope invoke_agent → chat/execute_tool。
- 4 个 contextmanager（都 `start_as_current_span`）：workflow_span（L102-115）、stage_span（L118-131）、tool_span（L134-148）、model_span（L151-175）。

**Q5：冷启动 6/12/25 分钟怎么测的？公平吗？**
- README:67-73：同一 MiMo 模型、相同研究题目、`LLM_MAX_CONCURRENCY=2`，**每档测试前重启后端清空进程内搜索与摘要缓存**。
- MEDIUM 6分29秒/81K输入30K输出/9133字符/16 URL/单 ReportAgent。
- HIGH 12分02秒/132K/38K/10034字符/24 URL/comparative+data-driven+high-synthesis。
- ULTRA 24分41秒/501K输入120K输出/25474字符/54 URL/5章节Agent+Consistency+5Reviser+merge+ClaimVerifier。
- 公平点：同模型同题同并发，清缓存。但**只能横向比，不代表生产**（生产有缓存命中会快）。

### 参考答案要点 + 别踩的坑
- ✅ 性能护栏要能背表：concurrent 1/2/3、conduct 2/4/6、search 2/3/4、LLM_MAX_CONCURRENCY=2、Tavily TTL 60min/512、Summary TTL 60min/1024、Summary timeout 60s、raw 12000/fallback 1200、findings 20000、L0/L1/L2 400/2500/12000、report 40000/section 8000。
- ✅ 可观测要说"单一全局 provider + 四层 span 非事后拼接 + 默认不采 I/O"。
- ⚠️ **坑**：别说"我们采了所有 prompt 和 response"——**默认不采 I/O**（`CAPTURE_IO=False`，`observability.py:71-78`，summarize 返回 None）。只有 `CAPTURE_IO=true` 才采且截断 500 chars + regex 脱敏 authorization/api_key/secret/token。
- ⚠️ **坑**：别说"采样了"——**无采样**（默认 `ParentBased/AlwaysOn`），一次 ULTRA 几百个 span 全导出，生产成本风险。诚实说"dev 阶段够用，生产要加 `TraceIdRatioBased(0.1)`"。

### 代码/数字支撑
- 性能护栏全表：`app/core/config.py:37-90`（见下表）。
- LLM 并发/重试：`app/infrastructure/llm.py:88`(Semaphore limit 2)、L144(瞬态重试)、L63-70(重试短语)、L290-296(per-account key)。
- 摘要缓存+inflight：`app/application/agents.py:922-950`（cache key+TTL+future dedup）、L972-974(agent.instance)、L895-913(并行+timeout)、L952-969(摘要+truncate)。
- Tavily 缓存：`app/infrastructure/tavily.py:34/99/100`。
- 可观测：`app/infrastructure/observability.py:28-36`(provider)、L46-68(endpoint)、L71-78(summarize 默认 None)、L102-175(4 span)、config.py:73-80(开关)。

### 反向风险

**Q：可观测性你自己发现过什么问题？**
- **max_conduct_count bug**（见第2条）——M3 埋点暴露决策结果后才发现 ULTRA 一直单轮。
- **1406 静默回退**（见第3条）——span 暴露了被 try/except 吞的异常。
- 这俩是你的**面试金矿**：主动讲"埋点让我发现了两个之前看不见的 bug"，证明可观测性的价值。

**Q：可观测自己有什么已知问题？**
- BatchSpanProcessor 导出超时（`read timeout=9.99s` 到 langfuse.com）→ 部分 span batch 丢（本地有，没导出）。
- `trace_id`（OTel 128bit）≠ `research.id`（session id，在 research.id 属性上）→ 不能用 research.id 当 trace_id 查，要按属性过滤。建议设 Langfuse `session.id=research.id`（未做）。
- SearchAgent 摘要 ERROR 被 Researcher 容错吞，建议聚合成 `search.failures.count` span 属性（未做）。
- 无采样（见上）。
- `metadata_json`/`payload_json` 仍 TEXT，可能复发 1406。

---

## 三档对照表逐格答疑（README:45-63）

被指着任意一格都要能答。挑最容易被问的：

| 格 | 追问 | 答 |
|---|---|---|
| 外层业务状态机 | "ULTRA 状态骨架和 MEDIUM 一样？" | 一样（QUEUE→SCOPE→HITL→IN_RESEARCH→IN_REPORT→COMPLETED），ULTRA 只在 IN_RESEARCH 阶段套动态轮次循环 |
| ScopeAgent | "识别研究类型花几次 LLM？" | **0 次额外**，写 brief 同一次调用顺带做（借鉴点 E，agents.py:189-234） |
| SupervisorAgent | "ULTRA 最多 6 任务怎么来的？" | `budget.max_conduct_count=6`，agents.py:361 `max_count=max(1,max_conduct_count)` cap。**但这正是 bug 源头**（见第2条） |
| AgentScopeResearchTeam | "Worker 并发 1/2/3 谁控制？" | `max_concurrent_units`，research_team.py:47 `asyncio.Semaphore(concurrency)` |
| ResearcherAgent | "每分支搜索 2/3/4 次硬约束？" | `max_search_count`，agents.py:564 `max_iterations=max_search_count*2` |
| SearchAgent | "TTL 缓存+in-flight+超时降级具体？" | 见第5条 Q2/Q3 |
| LLM 账户并发 | "HIGH 两个报告角度真并发？" | 是，但都走 LLM_MAX_CONCURRENCY=2 共享槽 |
| Research Context FS | "ULTRA 额外存什么？" | 章节工作区、共享 claim、mailbox、初稿、修订稿、最终报告（research://{id}/report/workspace/） |
| 报告主链路 | "三档报告链路差异？" | MEDIUM 单 ReportAgent；HIGH comparative+data-driven+high-synthesis；ULTRA 章节团队（默认不开，opt-in） |
| ULTRA 对抗审查 | "5 个维度是？" | coverage/evidence/freshness/source diversity/consistency，多 Reviewer 投票 |
| 失败与降级 | "ULTRA 章节团队失败怎么办？" | 回退完整借鉴点 C（多角度起草+Judge+融合）→ 再失败兜底报告 |

## 冷启动数字盘点（README:69-73）

- **6/12/25 分钟**：MEDIUM/HIGH/ULTRA。公平条件：同 MiMo 模型、同题、LLM_MAX_CONCURRENCY=2、每档重启清缓存。
- **token 增长**：MEDIUM 81K→HIGH 132K→ULTRA 501K（ULTRA 是 MEDIUM 6 倍输入，因为多轮+多 Reviewer+章节团队）。
- **URL 增长**：16→24→54（ULTRA 来源最广，因每分支 4 次搜索 × 多轮 × 多章节）。
- **报告字符**：9K→10K→25K（ULTRA 最长，章节团队产出更详尽）。
- ⚠️ 这些是**冷启动**（无缓存命中）。生产有 Tavily+摘要缓存会更快。面试别把冷启动数当生产预期。

## 13 条 landmine 速查表（反向风险弹药库）

被问到极限时，照这张表诚实答。**主动暴露 = 加分；藏着等被问穿 = 减分**。

| # | landmine | 一句话 | 锚点 |
|---|---|---|---|
| 1 | **max_conduct_count 三重用** | conduct_count 轮间不重置，默认 ULTRA 退化单轮 | agents.py:519-523, pipeline.py:536 |
| 2 | SearchAgent checkpoint 排除靠字符串前缀 | 脆弱契约，将来 agent 命名冲突会误排除 | agentscope_runtime.py:161-179 |
| 3 | CAS 是单条守卫 UPDATE 无重试 fail-fast | 不是版本号乐观锁，无 retry | services.py:659/675 |
| 4 | temp_event seq=-1 不入 DB | ZSet 过期/DB 回放都消失，真正临时 | cache.py:131-145 |
| 5 | fork_for_research 不带 conduct_count | 子状态从 0 起，但递增在 parent → bug #1 机制 | state.py:148-190 |
| 6 | report_section_team_enabled 默认 False | 章节团队 opt-in，不是默认开 | workflow_template.py:203 |
| 7 | L0/L1/L2 检索词法非 embedding | BM25-ish 打分，刻意轻量可追溯 | context_store.py:35 |
| 8 | resume 靠字符串匹配事件标题 | 中文硬字符串，改了就 resume 失败 | services.py:490 |
| 9 | pipeline update_research_session 无守卫 | 依赖单写者，cancel 能 race（窗口期两边写） | pipeline.py:651, services.py:548 |
| 10 | _TRANSIENT_RETRY_PHRASES 子串匹配 | 小写异常 message，非英文错误不匹配 | llm.py:63-70 |
| 11 | CAPTURE_IO 默认 False | prompt/response 不入 trace，只 token+元数据 | observability.py:71-78 |
| 12 | budget_name 大小写不敏感 | .upper()，非 ULTRA 落 FIXED（未知默认 HIGH） | services.py:361 |
| 13 | ZSet 30min TTL vs DB 永久 | 冷回放 O(总事件数) 非 O(漏掉) | cache.py:147-214 |

## 性能护栏全表（config.py 核验）

| 护栏 | 默认 | 用途 |
|---|---|---|
| BUDGET_*_MAX_CONCURRENT_UNITS | 1/2/3 | 每研究 Worker 并发 |
| BUDGET_*_MAX_CONDUCT_COUNT | 2/4/6 | 每研究子任务上限（ULTRA bug 源头） |
| BUDGET_*_MAX_SEARCH_COUNT | 2/3/4 | 每分支搜索次数 |
| RESEARCH_SEARCH_MAX_RESULTS_PER_QUERY | 3 | 单次搜索结果上限 |
| LLM_MAX_CONCURRENCY | 2 | 全局 LLM 账户 Semaphore |
| LLM_TIMEOUT | 300s | 单次 LLM 调用超时（×max_iterations） |
| LLM_RETRY_MAX_ATTEMPTS | 3 | 瞬态重试次数 |
| TAVILY_CACHE_TTL_MINUTES | 60 | 搜索缓存 TTL |
| TAVILY_CACHE_MAX_ENTRIES | 512 | 搜索缓存上限（LRU） |
| RESEARCH_SEARCH_SUMMARY_CACHE_TTL_MINUTES | 60 | 摘要缓存 TTL |
| RESEARCH_SEARCH_SUMMARY_CACHE_MAX_ENTRIES | 1024 | 摘要缓存上限 |
| RESEARCH_SEARCH_SUMMARY_TIMEOUT_SECONDS | 60 | 摘要超时（+5s wait_for） |
| RESEARCH_SEARCH_SUMMARY_RAW_CONTENT_MAX_CHARS | 12000 | 摘要输入上限 |
| RESEARCH_SEARCH_SUMMARY_FALLBACK_CONTENT_MAX_CHARS | 1200 | 降级时截断 |
| RESEARCH_REPORT_FINDINGS_MAX_CHARS | 20000 | 报告材料输入上限 |
| RESEARCH_CONTEXT_L0_MAX_CHARS | 400 | L0 摘要 |
| RESEARCH_CONTEXT_L1_MAX_CHARS | 2500 | L1 概览 |
| RESEARCH_CONTEXT_L2_MAX_CHARS | 12000 | L2 原文（写入即截断） |
| RESEARCH_CONTEXT_RAW_EXCERPT_MAX_CHARS | 1200 | 报告时单来源 L2 摘录（非持久化上限） |
| RESEARCH_CONTEXT_REPORT_MAX_CHARS | 40000 | 报告总上下文预算 |
| RESEARCH_CONTEXT_SECTION_MAX_CHARS | 8000 | 每章节预算 |
| RESEARCH_ASYNC_MAX_POOL_SIZE | 10 | 任务队列 worker 数 |
| RESEARCH_ASYNC_QUEUE_CAPACITY | 50 | 队列上限（满抛"系统繁忙"） |
| RESEARCH_ULTRA_DYNAMIC_MAX_ROUNDS | 5 | ULTRA 动态最大轮次（默认到不了，见 bug #1） |
| Redis TIMELINE_TTL | 30min | ZSet 时间线寿命 |
| Redis CHECKPOINT_TTL | 24h | checkpoint 寿命 |
| Reviewer continue_threshold | 2 | 继续 vs 报告的票数门槛 |

---

## 下一步：模拟拷打

讲义到此。接下来我扮面试官，**逐条逼问**——尤其第2条 max_conduct_count bug 和第4条 CAS/resume 字符串匹配，这两个决定成败。你答，我纠，直到你能"问题→答案→代码/数字"三段式自圆其说，且对已知 bug 能诚实交代不编造。
