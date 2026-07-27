# Redis + MySQL 面试要点（必要性与实例）

> 专项突击文档。聚焦一个问题：**这个项目为什么必须同时用 MySQL 和 Redis？各自不可替代在哪？**
> 所有结论已对照代码核验，带 file:line。配 `docs/resume-grill-讲义.md` 一起看。

---

## 一、一句话总纲

**MySQL 存"不能丢的事实"，Redis 存"要快但能重建的热数据"。**

分工的唯一判断标准：**这数据丢了能不能接受 / 能不能从别处重建**。
- 不能接受 → 放 MySQL（持久、ACID、可审计）。
- 能接受（能从 MySQL 重建）→ 放 Redis（快、低延迟）。

**核心设计原则**：Redis 永远不是事实来源，MySQL 才是。Redis 挂了/过期了，系统能从 MySQL 恢复，只是慢一点。Redis 的定位是"热数据加速层 + 断线重连的快速查找层"。

---

## 二、各存什么（一张表记住）

### MySQL 存的（持久事实来源，`app/domain/models.py`）

| 表 | 存什么 | 为什么必须在 MySQL |
|---|---|---|
| `ResearchSession` | status / brief / budget / conduct_count / dynamic_round_no / token 计数 / 时间 | 研究的"身份证+状态"，丢了研究就没了；CAS 靠它的 status 列 |
| `ChatMessage` | 用户和 assistant 的完整对话 | 审计 + resume 兜底重建，必须永久 |
| `WorkflowEvent` | 研究过程事件（已制定计划/已拆解任务/已完成研究...） | 审计 + SSE 断线重连的兜底数据源 + resume 字符串匹配 |
| `ResearchContextNode` + `ResearchContextEdge` | L0/L1/L2 节点、evidence、章节工作区、mailbox | **研究内容的真身**，报告阶段读这；丢了等于研究白做 |
| `ResearchIntervention` | 轻干预记录（pending/applied/expired） | 用户输入，必须留痕 |
| `ResearchPlanningRound` / `ResearchWorkItem` / `ResearchDecisionLog` / `ResearchEvidenceLedger` | ULTRA 每轮规划、任务项、决策、证据账本 | 审计可追溯 |
| `User` / `Model` | 用户、模型配置 | 基础数据 |

### Redis 存的（热数据，快但能重建，`app/infrastructure/cache.py`）

| key | 类型 | 存什么 | TTL | 丢了能重建吗 |
|---|---|---|---|---|
| `research:{id}:timeline` | ZSet | 研究事件，score=sequence_no | **30min** | 能，从 ChatMessage+WorkflowEvent 全量重建（cache.py:181-214） |
| `research:{id}:checkpoint` | String | DeepResearchState 序列化（含 AgentScope runtime snapshot） | **24h** | 能（慢且脆弱），兜底走事件行字符串匹配（services.py:490） |
| `user:{user_id}:researches` | Set | 用户的 research_id 集合 | — | 能，DB 兜底（cache.py:216-229） |

⚠️ 注意：**搜索缓存 + 摘要缓存是进程内 dict，不是 Redis**（`agents.py` self._summary_cache、`tavily.py` self._cache），TTL 60min，**重启就清空**——所以冷启动测试每档前要重启后端。

---

## 三、为什么必须用两个（必要性论证）

面试官会问"为什么不只用 MySQL / 不只用 Redis"。三个必要性：

### 必要性 1：SSE 断线重连既要"快"又要"不丢"——单个存储做不到

SSE 断线重连要求：客户端说"我收到 101 号了"，后端要快速查出"101 之后的事件"补发。

- **只用 MySQL**：`SELECT * FROM events WHERE seq>101 ORDER BY seq`。研究事件多了（ULTRA 几百个）就慢，SSE 重连是高频操作（用户刷新就触发），扛不住。
- **只用 Redis**：Redis ZSet 范围查 `ZRANGEBYSCORE` 极快，但 ZSet 有 TTL（30min）会过期，且 Redis 重启/evict 会丢，断线超过 30 分钟就全没了。

**两个一起**：Redis ZSet 挡 99% 的短断线重连（毫秒级），MySQL 兜住超长断线和 Redis 丢失（慢但不丢）。**快路径 + 慢兜底，缺一不可**。

### 必要性 2：崩溃恢复既要"完整 state"又要"持久可靠"——分两层

研究崩在 IN_RESEARCH 第 3 轮，重启要恢复"跑到第 3 轮、conduct_count 用了几个"。

- **只用 Redis Checkpoint**：24h TTL，过了就没了，Redis 重启也没了。长时间崩或机器重启，state 全丢。
- **只用 MySQL**：从 `WorkflowEvent` 行重建 state（`_hydrate_resume_state_from_events`），但靠**中文字符串匹配事件标题**，慢且脆弱（改了标题就崩）。

**两个一起**：优先走 Redis Checkpoint（快，完整 state 快照），过期/丢了兜底走 MySQL 事件行（慢但可靠）。**快路径 + 慢兜底**。

### 必要性 3：业务事实和运行时态是两种东西——MySQL 管前者，Redis/进程管后者

- 业务状态（status / brief / 谁的研究）是**强一致性需求**，要持久、要审计、要给前端协议用 → MySQL。
- 运行时态（AgentScope AgentState、当前轮次进度）是**临时态**，崩了能重算 → Redis Checkpoint + 进程内。

**不能让业务事实依赖 Redis**（Redis 挂了业务就瘫），也不能让热数据全进 MySQL（MySQL 扛不住高频读写）。分层是必然。

---

## 四、实例（面试官最爱"举个例子"）

### 实例 1：CAS 防重复启动（纯 MySQL，Redis 不参与）

**场景**：用户连点两次"启动研究"按钮。

**解法**（`services.py:659 _cas_update_to_queue`）：
```sql
UPDATE research_session SET status='QUEUE', update_time=NOW()
WHERE id=? AND user_id=? AND status IN ('NEW','NEED_CLARIFICATION','AWAITING_DIRECTION_CONFIRM','FAILED','CANCELLED')
```
- 第一次：状态是 NEW → 改成 QUEUE，rowcount=1，成功。
- 第二次：状态已经是 QUEUE（不是那 5 个）→ rowcount=0 → 抛 `ResearchError("启动研究异常")`。

**为什么必须 MySQL**：状态迁移是业务事实，必须持久 + 原子。这条 SQL 在数据库层面原子执行，**没有"先 SELECT 再 UPDATE"两步之间被插队的窗口**。Redis 做不到这种跨请求的原子状态迁移（Redis 事务弱、无 ACID）。

**反向风险**：pipeline 内部迁移 `update_research_session`（pipeline.py:651）**无 status 守卫**（普通 UPDATE），靠"出队后单写者"假设。cancel（services.py:548）能和 pipeline race（窗口期两边写），靠 `is_cancelled`（agents.py:1509 读 DB）兜底观测。诚实交代。

---

### 实例 2：SSE 断线重连（Redis 快路径 + MySQL 兜底，典型双写）

**场景**：研究跑到一半，用户刷新页面，30 秒后重连。

**解法**：
1. 产生事件时**双写**（`events.py:8-35 EventPublisher`）：写 `WorkflowEvent` 表（MySQL，永久）+ `ZADD` Redis ZSet（30min TTL）+ `sse_hub` 实时推在线客户端。
2. 客户端重连带 `Last-Event-ID: 101`（最后收到的序号）。
3. `get_timeline(research_id, 101)`（cache.py:147-155）：先 `ZRANGEBYSCORE timeline 102 → 上限`，毫秒级返回。
4. 补发 102,103... → 接实时流。

**Redis 的不可替代性**：SSE 重连高频（刷新就触发），MySQL 全量查+排序扛不住，Redis ZSet 范围查极快。

**MySQL 的不可替代性**：Redis ZSet 30min 过期、Redis 重启丢。断线 35 分钟重连，ZSet 空了 → `load_from_db`（cache.py:181-214）从 `ChatMessage`+`WorkflowEvent` **全量**读出来重建 ZSet，再过滤。**慢（O 总事件数）但不丢**。

**反向风险**：
- 冷回放 O(总事件数) 非 O(漏掉)，超长研究慢。
- `publish_temp_event` 写 sequence_no=-1 **不入 MySQL**（cache.py:131-145），ZSet 过期/重建时临时通知丢失——刻意的，临时通知不必重放。

---

### 实例 3：崩溃恢复（Redis Checkpoint 快路径 + MySQL 事件行兜底）

**场景**：ULTRA 跑到 IN_RESEARCH 第 3 轮，后端崩了重启。

**解法**（`pipeline.py:153 _recover_interrupted_tasks`）：
1. 启动时把卡在 START/IN_SCOPE/IN_RESEARCH/IN_REPORT 的会话**批量标 FAILED** + ERROR 事件（`_fail_interrupted_running_tasks` L174-198）——因为**不能从中间点续跑，只能整阶段重跑**。
2. QUEUE 状态的会话重入队：优先 `_state_from_checkpoint`（L267，从 Redis Checkpoint 重建完整 state），兜底 `_new_state_from_history`（L276，从 ChatMessage+WorkflowEvent 重建）。

**Redis 的不可替代性**：Checkpoint 是完整 state 快照（含 conduct_count、dynamic_round_no、AgentScope runtime snapshot），恢复快，不用拼。

**MySQL 的不可替代性**：Checkpoint 24h TTL 过期/Redis 重启丢了 → 兜底走 MySQL 事件行。但 `_hydrate_resume_state_from_events`（services.py:490）**靠中文字符串匹配事件标题**"已制定研究计划"/"已拆解任务"/"已完成该主题研究"判断进度——**脆弱契约**，改了就 resume 失败。诚实交代这是债。

**反向风险**：
- 整阶段回退，不能从阶段中点续跑（文档 `report-section-agent-team.md §当前边界` 原话）。
- Checkpoint 主动排除 SearchAgent 网页摘要 state（`agentscope_runtime.py:161-179`，靠 `key.startswith("SearchAgent:")` 字符串前缀），防 Redis 被网页正文撑爆——但**脆弱契约**，将来 agent 命名冲突会误排除。

---

### 实例 4：研究内容持久 vs 搜索缓存（MySQL 持久 + 进程内缓存）

**场景**：Researcher 搜了 Tavily 拿到网页，要存起来给报告阶段用。

**解法**：
- 网页内容**写 MySQL** `ResearchContextNode`（L0/L1/L2 节点，content=MEDIUMTEXT 16MB）——这是研究内容真身，报告阶段读这，永久不丢。
- Tavily 搜索结果和网页摘要**存进程内 dict 缓存**（TTL 60min，512/1024 entries，`tavily.py`/`agents.py:922-950`）——同一查询/同一网页不重复调 API，省 token 省钱。

**MySQL 的不可替代性**：L0/L1/L2 是研究产出，丢了报告没素材。

**进程内缓存的不可替代性**：Tavily API + LLM 摘要贵且慢，缓存避免重复。但**重启清空**，所以不是事实来源——重新搜也行，只是慢。

**反向风险**：
- **L2 写入即截断，>12000 chars 原文不保留**（context_writer.py:66）。面试官问"有信息丢失吗"要诚实说有。
- content 字段曾 TEXT(64KB) 引发 1406 静默回退 bug，已改 MEDIUMTEXT(16MB)+truncate 3M 兜底（report_team.py:674）；但 metadata_json/payload_json 仍 TEXT，潜在复发。

---

### 实例 5：双写一致性（事件同时写 MySQL 和 Redis）

**场景**：研究过程中每个事件都要写 MySQL + Redis ZSet + 实时推。

**解法**（`cache.py:72-92 save_event` + `save_message`）：每条事件**先写 MySQL，再写 Redis ZSet**，同一函数内顺序执行。

**为什么不担心不一致**：
- MySQL 是事实来源，Redis 是副本。Redis 丢了从 MySQL 补，**以 MySQL 为准**。
- 不做"先 Redis 后 MySQL"（那样 MySQL 写失败会 Redis 有 MySQL 无，不一致）；也不做分布式事务（太重）。
- 接受"最终一致"：极端情况下 Redis 可能短暂多/少几条，但 `load_from_db` 重建时以 MySQL 为准对齐。

**反向风险**：双写在同一函数顺序执行，MySQL 写成功但 Redis ZADD 失败的话，那条事件只在 MySQL 不在 Redis——但下次 ZSet 重建（30min 后或下次断线重连）会从 MySQL 补回来。短暂不一致可接受。

---

## 五、面试高频追问 + 标准答法

### Q1：MySQL 和 Redis 数据不一致怎么办？
> MySQL 是事实来源，Redis 是缓存/快照。每条事件双写（先 MySQL 后 Redis），冲突以 MySQL 为准，Redis 从 MySQL 重建。ZSet 30min 过期或 Redis 丢了，`load_from_db` 从 MySQL 全量重建对齐。我接受最终一致，不做分布式事务（太重，且 Redis 本就是可重建层）。

### Q2：为什么不只用 Redis？Redis 不是也能持久化（RDB/AOF）吗？
> Redis 持久化不如 MySQL 的 ACID 可靠；研究内容量大（L2 节点 + 事件 + 对话），全放 Redis 内存吃不消；审计查询（按 research_id/user_id/时间范围条件 SELECT）MySQL 更合适。Redis 定位是"热数据加速层 + 断线重连快查层"，不是主存储。把业务事实放 Redis 等于让业务依赖 Redis 可用性——Redis 挂了业务就瘫，不可接受。

### Q3：为什么不只用 MySQL？MySQL 加索引不也能快吗？
> SSE 断线重连是高频操作（用户刷新就触发），每次都从 MySQL 全量读+排序，研究事件多了（ULTRA 几百个）就慢，会拖慢业务查询。Checkpoint 高频写 MySQL 也会拖慢。Redis 做 hot path 缓冲，ZSet 范围查毫秒级挡住 99% 短重连，MySQL 兜超长断线。

### Q4：Checkpoint 24h TTL，研究跑超过 24 小时怎么办？
> 兜底走 MySQL 事件行重建（`_hydrate_resume_state_from_events`）。但超长任务（>24h）是边界 case，正常研究不会跑这么久（ULTRA 冷启动才 25 分钟）。而且研究崩了是整阶段重跑，不是从中间续，所以 checkpoint 过期影响的是"重建速度"不是"能否恢复"。

### Q5：Redis 挂了系统还能跑吗？
> 能，降级。SSE 实时推送靠进程内 `asyncio.Queue`（`sse.py _clients`），不依赖 Redis——在线客户端照常收实时事件。只是断线重连补发会走 MySQL 兜底（慢）。Checkpoint 丢了走事件行重建。所以 Redis 挂了是"变慢 + 超长断线补发变慢"，不是"系统挂"。

### Q6：SSE 实时推送用 Redis 吗？
> **不用。** 实时推送靠进程内 `asyncio.Queue`（`sse.py` 的 `_clients` 字典，keyed research_id→client_id）。后端产生事件→`_broadcast` put 进各客户端的队列→generator yield 给前端。Redis 的角色是"同时写一份 ZSet 存档，以防待会儿有人断线重连要补发"。**实时推送用进程内 Queue，断线重连补发才用 Redis**——别搞混。

### Q7：状态迁移都走 CAS 吗？
> **不是。** 只有**用户能并发触发的入口**走 CAS（启动研究 `_cas_update_to_queue`、确认方向 `_cas_confirm_direction`、取消 `cancel`）。pipeline **内部**的状态迁移（START→IN_SCOPE→IN_RESEARCH→IN_REPORT）是 `update_research_session`（pipeline.py:651）**普通 UPDATE 无 status 守卫**，靠"出队后单写者"假设。因为出队后只有一个 worker 跑这个 research，没并发，不需要乐观锁。CAS 只放在并发入口防重复。

---

## 六、一图速记

```
┌────────────────────────────────────────────────────────────┐
│ MySQL（持久事实来源，不能丢，ACID）                          │
│  ├ ResearchSession（status/brief/计数器）← CAS 在这          │
│  ├ ChatMessage + WorkflowEvent（对话+事件，resume&SSE兜底） │
│  ├ ResearchContextNode+Edge（L0/L1/L2 内容真身）            │
│  └ 5张ULTRA审计表（Round/WorkItem/DecisionLog/Evidence/Intervention）│
└────────────────────────────────────────────────────────────┘
              ▲ 双写（先MySQL后Redis）       ▲ 兜底重建
              │                              │
┌─────────────┴──────────────────────────────┴──────────────┐
│ Redis（热数据，快但能重建）                                 │
│  ├ ZSet timeline（SSE重放，TTL 30min，空→MySQL全量重建）   │
│  ├ Checkpoint（state快照，TTL 24h，过期→MySQL事件行兜底）  │
│  └ 所有权SET（SSE鉴权，DB兜底）                             │
└────────────────────────────────────────────────────────────┘
              ▲ 实时推送不经过Redis
              │ 进程内（重启清空）
┌─────────────┴────────────────────────────────────────────┐
│ 进程内 asyncio.Queue（SSE实时推送）+ dict缓存（搜索/摘要）│
│  ├ sse.py _clients（research_id→client_id→Queue）        │
│  └ Tavily缓存60min/512 + 摘要缓存60min/1024+inflight合并 │
└────────────────────────────────────────────────────────────┘
```

---

## 七、必须诚实交代的 7 个限制（反向风险）

| # | 限制 | 锚点 |
|---|---|---|
| 1 | CAS 是单条守卫 UPDATE 无重试 fail-fast（非版本号乐观锁） | services.py:659/675 |
| 2 | pipeline 内部迁移无 status 守卫，cancel 能 race | pipeline.py:651, services.py:548 |
| 3 | resume 靠中文字符串匹配事件标题，脆弱契约 | services.py:490 |
| 4 | ZSet 30min TTL，冷回放 O(总事件数) 非 O(漏掉) | cache.py:147-214 |
| 5 | Checkpoint 24h TTL，过期走脆弱兜底；不能从阶段中点续跑 | pipeline.py:267, services.py:490 |
| 6 | SearchAgent checkpoint 靠字符串前缀排除，脆弱契约 | agentscope_runtime.py:161-179 |
| 7 | temp_event seq=-1 不入 MySQL，ZSet 重建时丢失（刻意） | cache.py:131-145 |

**面试策略**：主动说"这些是我后来用可观测性 span 发现的/已知的取舍"——把弱点变亮点，比藏着等被问穿强 10 倍。
