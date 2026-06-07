package dev.haotangyuan.researcher.application.agent;

import com.fasterxml.jackson.databind.ObjectMapper;
import cn.hutool.core.date.DateUtil;
import cn.hutool.core.util.StrUtil;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchMemory;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatRequest;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatResponse;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchMessage;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolCall;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolSpec;
import dev.haotangyuan.researcher.application.agent.runtime.ToolChoiceMode;
import dev.haotangyuan.researcher.application.data.WorkflowStatus;
import dev.haotangyuan.researcher.application.model.ModelHandler;
import dev.haotangyuan.researcher.application.state.DeepResearchState;
import dev.haotangyuan.researcher.application.tool.ToolRegistry;
import dev.haotangyuan.researcher.application.tool.annotation.SupervisorTool;
import dev.haotangyuan.researcher.infra.data.EventType;
import dev.haotangyuan.researcher.infra.exception.WorkflowException;
import dev.haotangyuan.researcher.infra.util.EventPublisher;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static dev.haotangyuan.researcher.application.prompt.SupervisorPrompts.LEAD_RESEARCHER_PROMPT;

/**
 * @author: haotangyuan
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class SupervisorAgent {
    private final ModelHandler modelHandler;
    private final ObjectMapper objectMapper;
    private final ToolRegistry toolRegistry;
    private final ResearcherAgent researcherAgent;
    private final EventPublisher eventPublisher;

    private static final String SUPERVISOR_STAGE = SupervisorTool.class.getSimpleName();
    private static final String TOOL_REMINDER = "上一轮未实际调用任何工具。请用 think_tool 先做规划，再以工具调用形式触发 conductResearch，想要结束时使用 researchComplete 结束。";

    public void run(DeepResearchState state) {
        state.setStatus(WorkflowStatus.IN_RESEARCH);
        Long supervisorEventId = eventPublisher.publishEvent(state.getResearchId(),
                EventType.SUPERVISOR, "开始规划研究路线...", state.getResearchBrief());
        state.setCurrentSupervisorEventId(supervisorEventId);
        AgentAbility agent = AgentAbility.builder()
                .memory(new ResearchMemory(100))
                .chatClient(modelHandler.getChatClient(state.getResearchId()))
                .build();
        ResearchMessage systemMessage = ResearchMessage.system(
                StrUtil.format(LEAD_RESEARCHER_PROMPT, Map.of(
                        "date", DateUtil.today(),
                        "max_concurrent_research_units", state.getBudget().getMaxConcurrentUnits(),
                        "max_researcher_iterations", state.getBudget().getMaxConductCount()
                )));
        agent.getMemory().add(systemMessage);
        agent.getMemory().add(ResearchMessage.user(state.getResearchBrief()));
        plan(agent, state);
    }

    private void plan(AgentAbility agent, DeepResearchState state) {
        // 核心限制: conductCount < maxConductCount
        // 安全阀: supervisorIterations < maxConductCount * 2
        int maxConductCount = state.getBudget().getMaxConductCount();
        int maxIterations = maxConductCount * 2;
        while (state.getConductCount() < maxConductCount
                && state.getSupervisorIterations() < maxIterations) {
            // 1. 获取决策
            List<ResearchToolSpec> toolSpecifications = toolRegistry.getToolSpecifications(SUPERVISOR_STAGE);
            ResearchChatResponse chatResponse = agent.getChatClient().chat(new ResearchChatRequest(
                    agent.getMemory().messages(),
                    toolSpecifications,
                    ToolChoiceMode.REQUIRED));
            state.setTotalInputTokens(state.getTotalInputTokens() + chatResponse.tokenUsage().inputTokenCount());
            state.setTotalOutputTokens(state.getTotalOutputTokens() + chatResponse.tokenUsage().outputTokenCount());
            agent.getMemory().add(chatResponse.aiMessage());

            List<ResearchToolCall> toolExecutionRequests = chatResponse.aiMessage().toolCalls();
            if (toolExecutionRequests == null || toolExecutionRequests.isEmpty()) {
                agent.getMemory().add(ResearchMessage.user(TOOL_REMINDER));
                state.setSupervisorIterations(state.getSupervisorIterations() + 1);
                continue;
            }

            // 2. 执行工具
            action(agent, toolExecutionRequests, state);

            // 3. 是否终止
            if (toolExecutionRequests.stream()
                    .anyMatch(toolRequest -> "researchComplete".equals(toolRequest.name()))) {
                break;
            }

            state.setSupervisorIterations(state.getSupervisorIterations() + 1);
        }
    }

    private void action(AgentAbility agent, List<ResearchToolCall> toolExecutionRequests, DeepResearchState state) {
        if (toolExecutionRequests == null || toolExecutionRequests.isEmpty()) {
            return;
        }
        for (ResearchToolCall toolExecutionRequest : toolExecutionRequests) {
            String result;

            if ("conductResearch".equals(toolExecutionRequest.name())) {
                // 检查 conductResearch 调用次数限制
                int maxConductCount = state.getBudget().getMaxConductCount();
                if (state.getConductCount() >= maxConductCount) {
                    log.warn("conductResearch count limit reached: {}/{}",
                            state.getConductCount(), maxConductCount);
                    result = "已达到研究任务配额限制，请调用 researchComplete 完成研究";
                    agent.getMemory().add(toolResult(toolExecutionRequest, result));
                    continue;
                }

                String researchTopic = null;
                try {
                    var argsNode = objectMapper.readTree(toolExecutionRequest.arguments());
                    researchTopic = argsNode.get("researchTopic").asText();
                } catch (Exception e) {
                    log.error("Failed to parse conductResearch arguments", e);
                    throw new WorkflowException("Failed to parse conductResearch arguments", e);
                }

                Long planEventId = eventPublisher.publishEvent(state.getResearchId(), EventType.SUPERVISOR,
                        "正在研究: " + researchTopic, null, state.getCurrentSupervisorEventId());
                state.setCurrentResearchEventId(planEventId);

                // 设置 researcher 相关字段
                state.setResearchTopic(researchTopic);
                state.setResearcherIterations(0);
                state.setSearchCount(0);  // 重置搜索计数
                state.setResearcherNotes(new ArrayList<>());

                result = researcherAgent.run(state);

                // 增加 conductCount
                state.setConductCount(state.getConductCount() + 1);
            } else {
                var executor = toolRegistry.getExecutor(toolExecutionRequest.name());
                if (executor == null) {
                    log.warn("No executor found for tool {} in stage {}", toolExecutionRequest.name(), SUPERVISOR_STAGE);
                    continue;
                }
                result = executor.execute(toolExecutionRequest);
            }

            if (toolExecutionRequest.name().equals("thinkTool")) {
                eventPublisher.publishEvent(state.getResearchId(), EventType.SUPERVISOR,
                        "思考中...", result, state.getCurrentSupervisorEventId());
                state.getSupervisorNotes().add(result);
            } else if (toolExecutionRequest.name().equals("conductResearch")) {
                state.getSupervisorNotes().add(result);
            }

            agent.getMemory().add(toolResult(toolExecutionRequest, result));
        }
    }

    private ResearchMessage toolResult(ResearchToolCall toolExecutionRequest, String result) {
        return ResearchMessage.toolResult(toolExecutionRequest, result);
    }
}
