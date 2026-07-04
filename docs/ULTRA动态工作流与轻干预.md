# ULTRA 动态工作流与轻干预

## 范围

- 仅 `ULTRA` 档位进入动态工作流。
- `MEDIUM / HIGH` 继续保持原有固定工作流，不接入轻干预入口和调度逻辑。
- 轻干预只影响下一轮规划，不会中断当前轮已发出的研究任务。

## 本次新增能力

### 1. 动态工作流主链路

- `SupervisorAgent` 在每轮研究后生成动态决策。
- 决策包含：
  - `strategy`
  - `deltaSummary`
  - `qualityScoreboard`
  - `sectionScoreboard`
  - `sourceTypeBreakdown`
  - `nextFocus`
  - `nextAction`
  - `blockingGaps`
- `AgentPipeline` 根据 `nextAction=continue|report` 决定是否进入下一轮补强。

### 2. 质量约束

- 动态轮次结束后会生成全局质量上下文。
- 如果证据仍然不足，报告阶段会收到 `needs_disclosure` 上下文。
- 最终报告必须明确标注弱 section、不确定性和证据缺口，不能伪装成确定性结论。

### 3. 轻干预

- 用户可以在研究进行中追加“下一轮偏置”。
- 支持三类输入：
  - 重点 section
  - 补强方向
  - 自然语言备注
- 当前策略为 `latest_wins`：
  - 同一研究同一时刻只保留一条 `pending`
  - 新提交会替换旧的待生效调整
  - 被替换记录保留并标记为 `superseded`

## 用户可感知的前端表现

### 入口

- 顶部工具栏显示 `追加关注点` / `替换下一轮调整`
- Agent Flow 面板显示 `调整下一轮`

### 提交后的回显

- 聊天区出现用户消息：说明新增的关注点
- 聊天区出现助手确认：说明当前轮不会中断，下一轮前应用
- 主时间线出现 `INTERVENTION` 事件
- Agent Flow 出现干预节点
- 若存在待生效干预，页头会显示“下一轮待应用调整”卡片
- 下一轮开始时，系统会显示“正在按你的追加关注点重新规划”
- 下一轮规划采纳后，系统会显示“已在第 N 轮规划中采纳你的调整”

## 后端执行链路

1. `POST /api/v1/research/{id}/interventions` 写入 `research_intervention`
2. `ResearchService.create_intervention` 负责：
   - 预算和状态校验
   - 规范化 `focusSections / reinforceModes / note`
   - 以单事务方式完成 `latest_wins`
   - 发布聊天消息与时间线事件
3. `SupervisorAgent.run` 在每轮开始前加载 `pending` 干预
4. 干预内容会注入 planner prompt，和系统判定的 `nextFocus` 一起影响任务拆解
5. 规划完成后：
   - 干预记录更新为 `applied` 或 `partially_applied`
   - 采纳摘要写回 `apply_summary`
   - 聊天区与 Agent Flow 展示采纳结果
6. 若到达最大轮次或无法继续下一轮，未执行的 `pending` 干预会被标记为 `expired`

## 数据模型

### `research_intervention`

核心字段：

| 字段 | 说明 |
|---|---|
| `research_id` | 研究会话 ID |
| `status` | `pending / applied / partially_applied / expired / rejected / superseded` |
| `focus_sections_json` | 重点 section 列表 |
| `reinforce_modes_json` | 结构化补强方向 |
| `note` | 用户备注 |
| `replace_mode` | 当前固定为 `latest_wins` |
| `applied_round_no` | 实际采纳轮次 |
| `apply_summary_json` | 系统实际采纳内容 |
| `reject_code` / `reject_reason` | 未执行原因 |

### `research_planning_round`

- 每一轮 ULTRA 动态规划生成一条 round 记录
- `intervention_id` 记录本轮规划消费的是哪一条干预
- `planner_bias_json` 保留进入 planner 的偏置信息

## 可观测性

- 主时间线保留研究关键阶段和干预事件
- Agent Flow 可看到：
  - 动态决策节点
  - 任务批次节点
  - 干预节点
  - 下一轮采纳结果
- `GET /api/v1/research/{id}/messages` 会返回：
  - `pendingIntervention`
  - `recentInterventions`

## 当前边界

- 轻干预不接管 workflow，只提供下一轮偏置
- 不支持修改当前轮已经发出的子任务
- 不为非 ULTRA 工作流开放入口
- 结构化补强方向仍以后端枚举值持久化，但所有用户可见文案统一展示中文标签

## 推荐验证点

1. 启动一条 `ULTRA` 研究，确认出现轻干预入口。
2. 提交重点 section、补强方向和备注，确认聊天区、时间线、Agent Flow 同时回显。
3. 在已有 `pending` 时再次提交，确认旧记录变为 `superseded`，新记录成为唯一待生效干预。
4. 等待下一轮开始，确认出现“正在按你的追加关注点重新规划”。
5. 等待规划完成，确认出现“已在第 N 轮规划中采纳你的调整”。
6. 查看最终报告，确认弱 section 会明确披露证据缺口。
