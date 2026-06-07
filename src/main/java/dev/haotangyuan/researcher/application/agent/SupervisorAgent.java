package dev.haotangyuan.researcher.application.agent;

import com.fasterxml.jackson.databind.ObjectMapper;
import cn.hutool.core.date.DateUtil;
import cn.hutool.core.util.StrUtil;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchAgentRequest;
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
import dev.haotangyuan.researcher.infra.observability.ResearchObservation;
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
    private final ResearchObservation researchObservation;

    private static final String SUPERVISOR_STAGE = SupervisorTool.class.getSimpleName();
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
        int maxConductCount = state.getBudget().getMaxConductCount();
        int maxIterations = maxConductCount * 2;
        List<ResearchToolSpec> toolSpecifications = toolRegistry.getToolSpecifications(SUPERVISOR_STAGE);
        ResearchChatResponse response = agent.getChatClient().runAgent(new ResearchAgentRequest(
                "SupervisorAgent",
                null,
                agent.getMemory().messages(),
                toolSpecifications,
                toolCall -> executeTool(toolCall, state),
                maxIterations,
                state.traceContext()));
        state.setTotalInputTokens(state.getTotalInputTokens() + response.tokenUsage().inputTokenCount());
        state.setTotalOutputTokens(state.getTotalOutputTokens() + response.tokenUsage().outputTokenCount());
        agent.getMemory().add(response.aiMessage());
    }

    private String executeTool(ResearchToolCall toolExecutionRequest, DeepResearchState state) {
        String result;
        if ("conductResearch".equals(toolExecutionRequest.name())) {
            int maxConductCount = state.getBudget().getMaxConductCount();
            if (state.getConductCount() >= maxConductCount) {
                log.warn("conductResearch count limit reached: {}/{}",
                        state.getConductCount(), maxConductCount);
                result = researchObservation.observeTool(toolExecutionRequest.name(), "SupervisorAgent", state,
                        () -> "已达到研究任务配额限制，请调用 researchComplete 完成研究");
            } else {
                result = executeConductResearch(toolExecutionRequest, state);
                state.setConductCount(state.getConductCount() + 1);
            }
        } else {
            var executor = toolRegistry.getExecutor(toolExecutionRequest.name());
            if (executor == null) {
                log.warn("No executor found for tool {} in stage {}", toolExecutionRequest.name(), SUPERVISOR_STAGE);
                return "";
            }
            result = researchObservation.observeTool(toolExecutionRequest.name(), "SupervisorAgent", state,
                    () -> executor.execute(toolExecutionRequest));
        }

        if (toolExecutionRequest.name().equals("thinkTool")) {
            eventPublisher.publishEvent(state.getResearchId(), EventType.SUPERVISOR,
                    "思考中...", result, state.getCurrentSupervisorEventId());
            state.getSupervisorNotes().add(result);
        } else if (toolExecutionRequest.name().equals("conductResearch")) {
            state.getSupervisorNotes().add(result);
        }
        state.setSupervisorIterations(state.getSupervisorIterations() + 1);
        return result;
    }

    private String executeConductResearch(ResearchToolCall toolExecutionRequest, DeepResearchState state) {
        String researchTopic;
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

        state.setResearchTopic(researchTopic);
        state.setResearcherIterations(0);
        state.setSearchCount(0);
        state.setResearcherNotes(new ArrayList<>());

        return researchObservation.observeTool(toolExecutionRequest.name(), "SupervisorAgent", state,
                () -> researcherAgent.run(state));
    }
}
