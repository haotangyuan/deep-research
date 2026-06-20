# Deep Research HITL（人机协同）设计方案

> 生成日期：2026-06-15
> 设计对象：deep-research-main 多智能体深度研究平台
> 目标：在现有三阶段流水线（Scope → Supervisor → Report）基础上，引入 Human-in-the-Loop 能力，对齐 OpenAI Deep Research / Gemini Deep Research 的核心交互体验，并充分利用已集成的 AgentScope Java 框架能力。

---

## 0. TL;DR

- 主流 Deep Research 产品的 HITL 可分为四个层次（L1 澄清 → L2 计划评审 → L3 执行中断 → L4 源级审阅），其中 **L2 计划评审** ROI 最高，是 OpenAI/Gemini 的核心卖点。
- 本项目**已具备 L1**（`NEED_CLARIFICATION` 状态 + SSE 推送 + Timeline 持久化），但缺乏真正的"暂停-恢复"机制。
- AgentScope Java 框架原生提供 **Middleware 拦截 + Hook 事件 + `stopAgent()`** 三种 HITL 落地方式，但当前项目把 ReActAgent 封装在 `ResearchChatClient` 抽象后，编排逻辑在 `AgentPipeline` 层。
- 给出 **3 个递进方案**（A 计划评审 / B A+执行中断 / C 检查点平台），**推荐方案 A 先行、B 作为演进**。

---

## 1. 背景与目标

### 1.1 为什么需要 HITL

当前 deep-research 平台是**全自动**的：用户提交主题后，从 Scope 到 Report 一路跑完，中途无法干预。这带来三个痛点：

1. **方向跑偏无法纠正**：ScopeAgent 理解错需求时，Supervisor 会基于错误的研究计划消耗大量 token 做无用搜索。
2. **计划不可控**：用户无法增删研究子问题、调整研究深度，只能被动接受。
3. **缺乏信任建立**：用户看不到"AI 打算怎么做"，对长耗时（数分钟）的研究过程缺乏掌控感。

主流产品（OpenAI Deep Research、Gemini Deep Research）已把"研究前审阅计划"作为核心交互，实践证明能显著提升结果质量和用户信任。

### 1.2 设计目标

- **G1**：在 Scope 阶段产出研究计划后、Supervisor 执行前，支持用户**审阅、编辑、确认**。
- **G2**：在研究执行过程中，支持**暂停、补充指令、恢复**。
- **G3**：复用现有 SSE + EventPublisher + CacheUtil 基础设施，**不推翻**现有架构。
- **G4**：渐进式落地，每个阶段可独立交付、独立验证价值。

---

## 2. 调研结论

### 2.1 主流 Deep Research 产品的 HITL 形态

调研 OpenAI Deep Research、Google Gemini Deep Research、Perplexity Deep Research 等产品，HITL 能力可归纳为四个层次（由弱到强）：

| 层次 | 能力 | 代表产品 | 价值 |
|------|------|----------|------|
| **L1 澄清问答** | 研究前反问用户补充信息 | OpenAI、Gemini | 澄清模糊需求 |
| **L2 计划评审/编辑** | 生成研究大纲后，用户**审阅、增删、修改**研究任务，确认后才执行 | OpenAI（"review and modify plan"）、Gemini（"collaborative planning"） | **ROI 最高**，在花费 token 前校准方向 |
| **L3 执行中干预** | 研究进行中可**中断、暂停**，补充指令或修正方向后**恢复** | OpenAI（"interrupt at any time"） | 动态纠偏 |
| **L4 源级审阅** | 展示引用来源，用户可**标记可信/不可信**、要求深挖某条 | Gemini、Perplexity | 提升可信度 |

**关键洞察**：
- OpenAI 官方帮助文档明确说明："ChatGPT creates a **proposed research plan**. You can **review and modify it before the research begins**. You can follow progress as it runs and **interrupt at any time**."
- Gemini 称之为 "Collaborative planning"："allows you to **review and refine the research plan before execution**."
- **L2 计划评审**是所有主流产品的标配，且是用户感知最强、技术成本可控的 HITL 形态。

### 2.2 AgentScope 框架（Java 版）的 HITL 能力

本项目使用 **AgentScope Java**（`io.agentscope.core`，默认运行时），它原生提供三套与 HITL 相关的机制：

#### 2.2.1 Middleware（中间件拦截）— 本项目已在用

项目已有 `AgentscopeTraceContextMiddleware`（用于注入 Trace 上下文）。Middleware 可在以下阶段拦截：

- `onAgent()`：Agent 执行入口
- `onModelCall()`：模型调用前后
- `onActing()`：**工具执行前后**（HITL 的关键拦截点）

理论上可在这些阶段改写输入输出或中止执行，是落细粒度 HITL 的首选方式。

#### 2.2.2 Hook 事件 + `stopAgent()`

根据 AgentScope Java 官方 HITL 文档（`java.agentscope.io/v1/en/docs/task/hitl.html`）：

- **统一事件模型**：所有 Agent 行为通过 Hook 事件暴露
- **两个暂停点**：
  - `PostReasoningEvent.stopAgent()` — 推理后、工具执行前暂停
  - `PostActingEvent.stopAgent()` — 工具执行后、下次推理前暂停
- **恢复机制**：
  - `agent.call()` — 继续执行
  - `agent.call(toolResultMsg)` — 提供自定义工具结果后继续
- **可修改事件**：`PreReasoningEvent` 可修改输入消息，`PostReasoningEvent` 可修改推理结果

#### 2.2.3 统一事件总线（Issue #1698）

AgentScope 2.0 引入统一事件总线，明确设计目标之一就是"support frontend interactions and human-in-the-loop (HITL) workflows"。Issue #926 进一步讨论了"在不结束当前请求线程的前提下，同步等待前端用户输入"的需求。

#### 2.2.4 关键约束：当前架构的封装问题

> ⚠️ **这是方案设计的核心约束。**

当前项目把 AgentScope 的 ReActAgent 封装在 `ResearchChatClient` 抽象背后：

```java
// ResearchChatClient.java — runAgent 是一次性同步调用
default ResearchChatResponse runAgent(ResearchAgentRequest request) {
    for (int i = 0; i < iterations; i++) {
        ResearchChatResponse response = chat(...);
        // 执行工具 ...
        if (response.aiMessage().toolCalls().isEmpty()) break;
    }
    return new ResearchChatResponse(lastAssistantMessage, totalUsage, null);
}
```

真正的流水线编排（Scope → Supervisor → Report）由 `AgentPipeline` 自定义驱动，**没有暴露 Hook/暂停点**。因此"直接用 AgentScope 原生 HITL"需要权衡：要么下沉改造 ReActAgent 层暴露暂停能力，要么在 `AgentPipeline` 编排层做断点。

### 2.3 本项目现状评估

| 维度 | 现状 | 对 HITL 的影响 |
|------|------|----------------|
| **架构** | Spring Boot + AgentScope Java + React，DDD 分层清晰 | 后端改造成本可控 |
| **工作流** | `AgentPipeline` 三阶段同步 `run()`，`@QueuedAsync` 异步触发 | 暂停-恢复需要断点续跑能力，**这是最大的改造点** |
| **状态机** | 有 `NEED_CLARIFICATION`，但触发后需用户重发消息才能继续 | 已有 HITL 雏形，缺"恢复执行"接口 |
| **实时通信** | SSE + EventPublisher 完备，支持断线重放（`Last-Event-ID`） | HITL 通知推送可直接复用 ✅ |
| **持久化** | `ResearchSession`/`WorkflowEvent`/`ChatMessage` + CacheUtil | HITL 草稿（待确认计划）需新增持久化 |
| **前端** | Arena 轮询拉状态（2.5s），非纯 SSE 推 | 增加交互卡片即可 |
| **多模型对比** | Arena 模式同时跑最多 3 个研究 | HITL 要考虑"是否对每个模型都暂停确认" |

**核心结论**：基础设施（SSE、状态机、持久化）完备，**唯一的关键缺口是"工作流暂停-恢复"能力**。已有的 `NEED_CLARIFICATION` 机制证明"状态暂停 + 等待用户"模式在当前架构可行，HITL 本质是把它泛化为多个可控断点。

---

## 3. 总体设计

### 3.1 HITL 能力层次与方案映射

```
┌─────────────────────────────────────────────────────────┐
│  方案 C：检查点平台（L1-L4 全覆盖，重型）                  │
│  ┌───────────────────────────────────────────────────┐  │
│  │  方案 B：计划评审 + 执行中断（L2+L3，中等）          │  │
│  │  ┌─────────────────────────────────────────────┐  │  │
│  │  │  方案 A：计划评审（L2，轻量，推荐先行）        │  │  │
│  │  └─────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

三个方案是**递进关系**：方案 A 是 B 的子集，B 是 C 的子集。可以独立选其一，也可分阶段 A→B→C 实施。

### 3.2 三方案速览

| 维度 | 方案 A：计划评审 | 方案 B：A + 执行中断 | 方案 C：检查点平台 |
|------|------------------|---------------------|-------------------|
| HITL 层级 | L2 | L2 + L3 | L1-L4 全覆盖 |
| AgentScope 能力利用 | 编排层断点（轻） | **Middleware 拦截**（中） | Hook + Middleware + 事件总线（重） |
| 后端改动 | 4-5 文件 | +2 类 + 改造注入 | 重构引擎 + 持久化 |
| 前端改动 | 1 个计划卡片 | +审批卡片 | 多种交互形态 |
| 核心风险 | 低 | 并行分支阻塞处理 | 架构重构风险 |
| 用户体验 | 对标 OpenAI 核心 | 接近 OpenAI 完整 | 超越主流产品 |
| 工作量预估 | ~1-2 周 | ~2-3 周 | ~4-6 周 |

---

## 4. 方案 A：计划评审（L2，推荐先行）

### 4.1 核心思路

在 Scope 阶段产出研究计划（`researchQuestion` / `researchBrief`）后、Supervisor 阶段执行前，插入一个**人工确认断点**。用户可编辑/增删研究子问题，确认后才继续。完全对标 OpenAI/Gemini 的核心 HITL 体验。

### 4.2 为什么推荐

1. **ROI 最高**：在花费大量 token 做研究前校准方向，避免资源浪费。
2. **改动最聚焦**：流水线天然在 Scope→Supervisor 之间有清晰边界，插入断点代价最小。
3. **完全复用现有基础设施**：`NEED_CLARIFICATION` 已证明"状态暂停 + 等待用户"可行，SSE/EventPublisher/CacheUtil 全部现成。
4. **落在 `AgentPipeline` 编排层**，最符合当前架构，不侵入 AgentScope 封装。

### 4.3 状态机设计

```
                          ┌──────────────────────────────┐
                          │                              │
                          ▼                              │ (用户编辑计划后重新确认)
START → IN_SCOPE → AWAIT_PLAN_REVIEW ──────────► IN_RESEARCH → IN_REPORT → COMPLETED
                       │            ▲
                       │            │ (用户直接确认)
                       │            │
                       └─(超时/降级)┘
```

新增状态：

```java
// WorkflowStatus.java
public static final String AWAIT_PLAN_REVIEW = "AWAIT_PLAN_REVIEW"; // 等待用户审阅研究计划
```

### 4.4 后端改动清单

#### 4.4.1 新增/修改的状态字段

```java
// DeepResearchState.java 新增
private String resumeFrom;       // 恢复断点：SCOPE_DONE / null（从头跑）
private PlanDraft planDraft;     // 待审阅的研究计划草稿

// 计划草稿结构
public record PlanDraft(
    String researchBrief,            // 研究综述
    List<ResearchSubQuestion> subQuestions,  // 子问题列表（用户可增删改）
    LocalDateTime createdAt
) {}
```

#### 4.4.2 `AgentPipeline` 改造（核心）

```java
@QueuedAsync
public void run(DeepResearchState state) {
    String researchId = state.getResearchId();
    // ... 

    // Phase 1: Scope（带断点判断）
    if (!"SCOPE_DONE".equals(state.getResumeFrom())) {
        researchObservation.observeStage("ScopeAgent", state, () -> scopeAgent.run(state));
        // ... 失败/澄清处理同原逻辑 ...

        // ★ HITL 断点：Scope 完成后，若启用计划评审，则暂停
        if (hitlEnabled(state) && state.getResearchBrief() != null) {
            state.setResumeFrom("SCOPE_DONE");
            state.setStatus(WorkflowStatus.AWAIT_PLAN_REVIEW);
            state.setPlanDraft(buildPlanDraftFromState(state));
            updateResearchSession(researchId, WorkflowStatus.AWAIT_PLAN_REVIEW, state);
            eventPublisher.publishEvent(researchId, EventType.SCOPE,
                "研究计划待确认", state.getResearchBrief(), state.getCurrentScopeEventId());
            return;  // ★ 优雅退出异步线程，等待用户确认
        }
    }

    // Phase 2: Supervisor
    state.setStatus(WorkflowStatus.IN_RESEARCH);
    // ... 原逻辑 ...

    // Phase 3: Report
    // ... 原逻辑 ...
}
```

关键点：
- `state.resumeFrom` 记录断点位置，恢复时跳过已完成阶段
- 暂停 = `return` 退出 `@QueuedAsync` 线程（**不阻塞线程**）
- `ResearchSession` 持久化 `resumeFrom`，保证服务重启可恢复

#### 4.4.3 新增 Controller 接口

```java
// ResearchController.java 新增

// 用户确认计划（可携带编辑后的子问题）
@PostMapping("/api/v1/research/{researchId}/plan/approve")
public Result<SendMessageRespDTO> approvePlan(
        @RequestAttribute("userId") Long userId,
        @PathVariable String researchId,
        @RequestBody(required = false) PlanReviewReqDTO review) {
    // 1. 校验归属 & 状态必须为 AWAIT_PLAN_REVIEW
    // 2. 若 review 非空，用编辑后的计划覆盖 state.planDraft
    // 3. 重新构建 state（从 DB 恢复），设置 resumeFrom = "SCOPE_DONE"
    // 4. 再次调用 agentPipeline.run(state)，从 Supervisor 继续
    return Results.success(researchService.approvePlan(userId, researchId, review));
}

// 用户放弃 / 重新生成计划
@PostMapping("/api/v1/research/{researchId}/plan/regenerate")
public Result<Void> regeneratePlan(...) { ... }
```

#### 4.4.4 持久化

- `ResearchSession` 表新增字段：`resume_from VARCHAR(32)`、`plan_draft TEXT`（JSON）
- 或新增 `workflow_checkpoint` 表（为方案 C 预留）

### 4.5 前端改动

在 `ArenaPage.tsx` 中，检测到 `AWAIT_PLAN_REVIEW` 状态时，渲染**研究计划审阅卡片**：

```
┌─────────────────────────────────────────────┐
│  📋 研究计划待确认                            │
├─────────────────────────────────────────────┤
│  研究综述：xxx                                │
│                                              │
│  子问题（可编辑/增删）：                       │
│  ┌─────────────────────────────────────┐    │
│  │ 1. [可编辑文本]                  ✕  │    │
│  │ 2. [可编辑文本]                  ✕  │    │
│  │ + 添加子问题                         │    │
│  └─────────────────────────────────────┘    │
│                                              │
│              [放弃]  [重新生成]  [确认开始]   │
└─────────────────────────────────────────────┘
```

### 4.6 改动范围汇总

| 层 | 文件 | 改动 |
|----|------|------|
| 状态 | `WorkflowStatus.java` | +1 常量 |
| 状态 | `DeepResearchState.java` | +2 字段（resumeFrom, planDraft）|
| 编排 | `AgentPipeline.java` | 插入断点逻辑 |
| 服务 | `ResearchServiceImpl.java` | +approvePlan 方法 |
| 接口 | `ResearchController.java` | +2 接口 |
| 持久化 | `ResearchSession` + DDL | +2 字段 |
| 前端 | `ArenaPage.tsx` | +计划审阅卡片 |

### 4.7 关键设计决策

- **D1：暂停即退出线程**，不阻塞 `@QueuedAsync` 线程池。状态持久化保证可恢复。
- **D2：Arena 多模型对比**：每个模型独立暂停确认（因为各模型的 ScopeAgent 产出的计划不同）。前端为每个 Run 独立展示计划卡片。
- **D3：超时降级**：`AWAIT_PLAN_REVIEW` 超过 N 分钟（可配置）自动按原计划继续，避免用户遗忘导致任务挂死。
- **D4：开关控制**：通过配置 `research.hitl.plan-review.enabled` 控制，默认关闭，逐步放量。

---

## 5. 方案 B：计划评审 + 执行中断（L2 + L3）

### 5.1 核心思路

在方案 A 的"计划评审"断点之外，再增加 **Supervisor 阶段执行中的中断能力**——用户可在研究跑到一半时暂停、补充指令、恢复。这次**真正用上 AgentScope 的 Middleware 拦截机制**。

### 5.2 设计要点

#### 5.2.1 新增 HitlMiddleware

```java
// 新增：HitlMiddleware.java
public class HitlMiddleware implements MiddlewareBase {

    @Override
    public Flux<AgentEvent> onActing(Agent agent, ActingInput input,
                                     Function<ActingInput, Flux<AgentEvent>> next) {
        // 当 ReActAgent 要执行 conductResearch / tavilySearch 工具前
        HitlFlag flag = evaluateHitlFlag(agent, input);
        if (flag.shouldPause()) {
            // 1. 推送"等待审批"事件到前端
            eventPublisher.publishEvent(researchId, EventType.SUPERVISOR,
                "等待人工审批", describeToolCall(input), parentEventId);
            // 2. 阻塞当前 Flux，等待用户决策
            return HitlDecisionHolder.await(researchId, flag.decisionId())
                .flatMapMany(decision -> applyDecision(decision, input, next));
        }
        return next.apply(input);
    }
}
```

#### 5.2.2 阻塞-唤醒机制

```java
// HitlDecisionHolder.java
@Component
public class HitlDecisionHolder {
    private final Map<String, CompletableFuture<HitlDecision>> pending = new ConcurrentHashMap<>();

    public Mono<HitlDecision> await(String researchId, String decisionId) {
        CompletableFuture<HitlDecision> future = new CompletableFuture<>();
        pending.put(decisionId, future);
        // 超时降级：10 分钟后自动 APPROVE
        scheduler.schedule(() -> complete(decisionId, HitlDecision.APPROVE), 10, MINUTES);
        return Mono.fromFuture(future);
    }

    public void complete(String decisionId, HitlDecision decision) {
        CompletableFuture<HitlDecision> f = pending.remove(decisionId);
        if (f != null) f.complete(decision);
    }
}
```

#### 5.2.3 HITL 触发策略（可配置）

```yaml
research:
  hitl:
    execution:
      enabled: true
      strategy: PER_N_TASKS   # PER_N_TASKS | ON_KEYWORD | MANUAL_ONLY
      pause-every: 3          # 每完成 3 个研究任务暂停一次
      timeout-minutes: 10     # 超时自动放行
```

### 5.3 并行场景的处理

⚠️ **核心难点**：Supervisor 的 `executeResearchTasks` 用线程池并行执行多个研究任务。

两种策略：

- **策略 1：分支独立审批**（推荐）：每个并行分支独立持有 `HitlDecisionHolder`，互不阻塞。前端为每个分支展示审批卡片。
- **策略 2：统一汇总审批**：在 Supervisor 汇总点（所有分支完成后）插入审批，代价是失去"中途干预"的实时性。

### 5.4 改动范围

在方案 A 基础上新增：

| 层 | 文件 | 改动 |
|----|------|------|
| 中间件 | `HitlMiddleware.java`（新增） | 工具调用前拦截 |
| 唤醒 | `HitlDecisionHolder.java`（新增） | CompletableFuture 阻塞-唤醒 |
| 配置 | `AgentscopeStageAgentDefinition.java` | 注入 HitlMiddleware |
| 接口 | `ResearchController.java` | +审批接口 |
| 前端 | `ArenaPage.tsx` | +审批卡片 |

比方案 A 多约 30% 工作量。

### 5.5 风险点

- **线程池阻塞**：并行分支阻塞会影响整体并行度和线程池利用率，需合理设置超时。
- **AgentScope Reactor 集成**：Middleware 基于 Reactor `Flux`，阻塞需用 `Mono.fromFuture` 转换，注意调度器不要阻塞事件循环线程。

---

## 6. 方案 C：完整 HITL 平台（L1-L4，检查点机制）

### 6.1 核心思路

把工作流从"一次性同步 run"重构为**可持久化、可恢复的状态机**（类似 LangGraph 的 checkpoint 机制），任意阶段都可暂停、回放、分叉。这是最完备但改造最大的方案。

### 6.2 设计要点

#### 6.2.1 Checkpoint 机制

```
workflow_checkpoint 表：
  - id, research_id, step_name (SCOPE/SUPERVISOR_0/SUPERVISOR_1/REPORT)
  - state_snapshot (JSON, 完整 DeepResearchState 序列化)
  - created_at, status (COMPLETED/PAUSED/FAILED)
```

- 每完成一个"原子步骤"就持久化快照
- `AgentPipeline` 从"最后完成的步骤"恢复，而非从头跑
- 支持分支：用户可基于某个检查点 fork 出新研究（`forkForResearch` 已有雏形）

#### 6.2.2 全面接入 AgentScope 能力

- **Hook 系统**：`PostReasoningEvent`/`PostActingEvent` 实现 ReActAgent 内部细粒度暂停
- **Middleware**：拦截所有工具调用，支持审批/改写
- **事件总线**：统一的 status event 推送

#### 6.2.3 支持的能力

- **L1 澄清**：已有
- **L2 计划评审**：方案 A
- **L3 执行中断**：方案 B
- **L4 源级审阅**：展示每条搜索来源，用户可标记可信度、要求深挖
- **回退重跑**：基于检查点回退到任意步骤重新执行
- **分叉对比**：从同一检查点 fork 多个研究方向

### 6.3 改动范围

重构核心工作流引擎，新增持久化层，改动 10+ 文件，工作量是方案 A 的 3-4 倍。适合作为长期演进目标。

---

## 7. 实施建议

### 7.1 推荐路线：A → B → C 渐进式

```
Phase 1（1-2 周）：方案 A — 计划评审
  ✅ 验证 HITL 业务价值，打通"暂停-恢复"骨架
  ✅ 复用现有基础设施，改动聚焦
  ✅ 上线后观察用户参与率、计划修改率、结果质量提升

Phase 2（2-3 周）：方案 B — 执行中断
  ✅ 在 A 的骨架上增加细粒度断点
  ✅ 引入 AgentScope Middleware，深挖框架能力
  ✅ 积累 Reactor 异步阻塞经验

Phase 3（4-6 周）：方案 C — 检查点平台（按需）
  ✅ 当业务需要回退/分叉/L4 源级审阅时启动
  ✅ 重构为状态机 + Checkpoint
```

### 7.2 为什么推荐 A 先行

1. **方案 A 直接复用已有基础设施**：`NEED_CLARIFICATION` 已证明模式可行，SSE + EventPublisher + CacheUtil 全部现成。
2. **方案 A 落在 `AgentPipeline` 编排层，最符合架构**：不侵入 AgentScope 封装，改动聚焦。
3. **方案 B 是 A 的自然延伸**：A 的断点框架（状态机 + 恢复接口 + 前端卡片）建好后，B 只是"增加更多断点 + 用 Middleware 拦截工具调用"，是增量工作。
4. **AgentScope 能力引入要循序渐进**：A 暂时不用 AgentScope 的 HITL（因为 ReActAgent 被封装了），等熟悉中间件机制后，B 正好把它用起来——符合"先验证业务价值，再深挖框架能力"的节奏。

### 7.3 待确认的决策点

- **Q1：Arena 多模型对比模式下，HITL 是否对每个模型独立暂停？**
  - 建议：方案 A 阶段每个模型独立暂停（各模型计划不同）；方案 B 可考虑只对"基准模型"暂停，其余自动跟随。
- **Q2：HITL 是否默认开启？**
  - 建议：配置开关控制，默认关闭，逐步放量。可按用户/按预算级别开关。
- **Q3：暂停状态是否计入研究时长？**
  - 建议：`AWAIT_PLAN_REVIEW` 期间不计入 `startTime-completeTime` 时长统计，避免污染耗时指标。

---

## 8. 参考资料

### 8.1 AgentScope 框架

- [AgentScope Java 官方 HITL 文档](https://java.agentscope.io/v1/en/docs/task/hitl.html)
- [AgentScope Java Hook 文档](https://java.agentscope.io/v1/en/docs/task/hook.html)
- [AgentScope 事件系统支持 HITL (Issue #1698)](https://github.com/agentscope-ai/agentscope/issues/1698)
- [AgentScope Feature: human in loop (Issue #926)](https://github.com/agentscope-ai/agentscope/issues/926)
- [AgentScope 1.0 论文 (arXiv 2508.16279)](https://arxiv.org/html/2508.16279v1)
- [AgentScope GitHub 仓库](https://github.com/agentscope-ai/agentscope)

### 8.2 主流 Deep Research 产品

- [Deep research in ChatGPT — OpenAI 官方帮助文档](https://help.openai.com/en/articles/10500283-deep-research-in-chatgpt)
- [Introducing Deep Research — OpenAI 官方博客](https://openai.com/index/introducing-deep-research/)
- [Gemini Deep Research — Collaborative Planning](https://ai.google.dev/gemini-api/docs/interactions/deep-research)
- [Google Deep Research vs. OpenAI Deep Research — Seer Interactive](https://www.seerinteractive.com/insights/google-deep-research-vs.-openai-deep-research-a-comprehensive-guide-for-seo-digital-marketing-professionals)

### 8.3 其他 HITL 框架（对比参考）

- [AG2 Human-in-the-Loop](https://docs.ag2.ai/latest/docs/beta/context/human_in_the_loop/)
- [OpenAI Agents SDK — HITL](https://openai.github.io/openai-agents-python/human_in_the_loop/)
- [Microsoft Agent Framework Workflows — HITL](https://learn.microsoft.com/en-us/agent-framework/workflows/human-in-the-loop)
- [LangGraph HITL (LangChain)](https://docs.langchain.com/oss/python/langchain/frontend/human-in-the-loop)
- [Cloudflare Agents — HITL patterns](https://developers.cloudflare.com/agents/concepts/agentic-patterns/human-in-the-loop/)
- [AI SDK — HITL with Next.js](https://ai-sdk.dev/cookbook/next/human-in-the-loop)
