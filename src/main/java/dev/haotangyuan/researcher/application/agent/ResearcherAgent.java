package dev.haotangyuan.researcher.application.agent;

import cn.hutool.core.date.DateUtil;
import cn.hutool.core.util.StrUtil;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchAgentRequest;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatRequest;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatResponse;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchMemory;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchMessage;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolCall;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolSpec;
import dev.haotangyuan.researcher.application.agent.runtime.ToolChoiceMode;
import dev.haotangyuan.researcher.infra.data.EventType;
import dev.haotangyuan.researcher.application.model.ModelHandler;
import dev.haotangyuan.researcher.application.state.DeepResearchState;
import dev.haotangyuan.researcher.infra.config.SearchProps;
import dev.haotangyuan.researcher.infra.util.EventPublisher;
import dev.haotangyuan.researcher.application.tool.annotation.ResearcherTool;
import dev.haotangyuan.researcher.infra.exception.WorkflowException;
import dev.haotangyuan.researcher.infra.observability.ResearchObservation;
import dev.haotangyuan.researcher.application.tool.ToolRegistry;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Semaphore;
import java.util.stream.Collectors;

import static dev.haotangyuan.researcher.application.prompt.ResearcherPrompts.*;

/**
 * Researcher Agent - performs iterative web searches and synthesis
 * @author: haotangyuan
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class ResearcherAgent {
    private final ModelHandler modelHandler;
    private final ToolRegistry toolRegistry;
    private final ObjectMapper objectMapper;
    private final SearchAgent searchAgent;
    private final EventPublisher eventPublisher;
    private final ResearchObservation researchObservation;
    private final SearchProps searchProps;

    private static final String RESEARCHER_STAGE = ResearcherTool.class.getSimpleName();

    public String run(DeepResearchState state) {
        log.info("ResearcherAgent run: researchId='{}', topic='{}'", state.getResearchId(), state.getResearchTopic());
        Long researchEventId = eventPublisher.publishEvent(state.getResearchId(), EventType.RESEARCH,
                "深入研究: " + state.getResearchTopic(), null, state.getCurrentResearchEventId());
        state.setCurrentResearchEventId(researchEventId);
        
        AgentAbility agent = AgentAbility.builder()
                .memory(new ResearchMemory(100))
                .chatClient(modelHandler.getChatClient(state.getResearchId()))
                .build();
        
        ResearchMessage systemMessage = ResearchMessage.system(
            StrUtil.format(RESEARCH_AGENT_PROMPT,Map.of("date", DateUtil.today()))
        );
        agent.getMemory().add(systemMessage);
        agent.getMemory().add(ResearchMessage.user(state.getResearchTopic()));
        
        plan(agent, state);
        return compressResearch(agent, state);
    }

    private void plan(AgentAbility agent, DeepResearchState state) {
        int maxSearchCount = state.getBudget().getMaxSearchCount();
        int maxIterations = maxSearchCount * 2;
        Semaphore searchConcurrency = new Semaphore(Math.max(1, maxSearchCount));
        List<ResearchToolSpec> toolSpecifications = toolRegistry.getToolSpecifications(RESEARCHER_STAGE);
        ResearchChatResponse response = agent.getChatClient().runAgent(new ResearchAgentRequest(
                "ResearcherAgent",
                null,
                agent.getMemory().messages(),
                toolSpecifications,
                toolCall -> executeTool(toolCall, state, searchConcurrency),
                maxIterations,
                state.traceContext()));
        state.addTokenUsage(response.tokenUsage());
        agent.getMemory().add(response.aiMessage());
    }

    private String executeTool(
            ResearchToolCall toolExecutionRequest,
            DeepResearchState state,
            Semaphore searchConcurrency) {
        String result;
        if ("tavilySearch".equals(toolExecutionRequest.name())) {
            if (!reserveSearchSlot(state)) {
                log.warn("tavilySearch count limit reached: {}/{}",
                        state.getSearchCount(), state.getBudget().getMaxSearchCount());
                result = researchObservation.observeTool(toolExecutionRequest.name(), "ResearcherAgent", state,
                        () -> "已达到搜索配额限制，请根据已有信息完成研究");
            } else {
                result = executeSearchTool(toolExecutionRequest, state, searchConcurrency);
            }
        } else {
            var executor = toolRegistry.getExecutor(toolExecutionRequest.name());
            if (executor == null) {
                log.warn("No executor found for tool {} in stage {}", toolExecutionRequest.name(), RESEARCHER_STAGE);
                return "";
            }
            result = researchObservation.observeTool(toolExecutionRequest.name(), "ResearcherAgent", state,
                    () -> executor.execute(toolExecutionRequest));
        }

        synchronized (state) {
            if ("thinkTool".equals(toolExecutionRequest.name())) {
                eventPublisher.publishEvent(state.getResearchId(), EventType.RESEARCH,
                        "分析中...", result, state.getCurrentResearchEventId());
            }
            state.getResearcherNotes().add(String.format("[%s] %s", toolExecutionRequest.name(), result));
            state.setResearcherIterations(state.getResearcherIterations() + 1);
        }
        return result;
    }

    private String executeSearchTool(
            ResearchToolCall toolExecutionRequest,
            DeepResearchState state,
            Semaphore searchConcurrency) {
        try {
            var argsNode = objectMapper.readTree(toolExecutionRequest.arguments());
            String query = argsNode.get("query").asText();
            int maxResults = argsNode.has("maxResults") ? argsNode.get("maxResults").asInt() : 3;
            maxResults = Math.max(1, Math.min(maxResults, Math.max(1, searchProps.getMaxResultsPerQuery())));
            String topic = argsNode.has("topic") ? argsNode.get("topic").asText() : "general";
            DeepResearchState searchState = state.forkForSearch(query, maxResults, topic);

            boolean acquired = false;
            try {
                searchConcurrency.acquire();
                acquired = true;
                return researchObservation.observeTool(toolExecutionRequest.name(), "ResearcherAgent", state,
                        () -> searchAgent.run(searchState));
            } finally {
                if (acquired) {
                    searchConcurrency.release();
                }
                state.mergeTokenUsageFrom(searchState);
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new WorkflowException("Interrupted while waiting for tavilySearch concurrency slot", e);
        } catch (Exception e) {
            log.error("Failed to parse tavilySearch arguments", e);
            throw new WorkflowException("Failed to parse tavilySearch arguments", e);
        }
    }

    private String compressResearch(AgentAbility agent, DeepResearchState state) {
        String systemPrompt = StrUtil.format(COMPRESS_RESEARCH_SYSTEM_PROMPT, Map.of("date", DateUtil.today()));
        
        List<ResearchMessage> messages = new ArrayList<>();
        messages.add(ResearchMessage.system(systemPrompt));
        // 跳过前两条（ResearcherAgent 的 system + user），只保留工具调用历史
        messages.addAll(agent.getMemory().messages().stream().skip(2).collect(Collectors.toList()));
        messages.add(ResearchMessage.user(
            StrUtil.format(COMPRESS_RESEARCH_HUMAN_MESSAGE, Map.of("research_topic", state.getResearchTopic()))));
        
        ResearchChatResponse compressResponse = agent.getChatClient().runAgent(
                ResearchAgentRequest.textOnly("ResearcherAgent", null, messages, state.traceContext()));
        state.addTokenUsage(compressResponse.tokenUsage());
        String compressedResearch = compressResponse.aiMessage().text();
        
        state.setCompressedResearch(compressedResearch);
        eventPublisher.publishEvent(state.getResearchId(), EventType.RESEARCH,
                "已完成该主题研究", compressedResearch.substring(0, Math.min(200, compressedResearch.length())) + "...", state.getCurrentResearchEventId());
        
        return compressedResearch;
    }

    private boolean reserveSearchSlot(DeepResearchState state) {
        synchronized (state) {
            int current = state.getSearchCount() == null ? 0 : state.getSearchCount();
            if (current >= state.getBudget().getMaxSearchCount()) {
                return false;
            }
            state.setSearchCount(current + 1);
            return true;
        }
    }

}
