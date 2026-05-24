package dev.haotangyuan.researcher.application.agent;

import cn.hutool.core.date.DateUtil;
import cn.hutool.core.util.StrUtil;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.haotangyuan.researcher.infra.data.EventType;
import dev.haotangyuan.researcher.application.model.ModelHandler;
import dev.haotangyuan.researcher.application.state.DeepResearchState;
import dev.haotangyuan.researcher.infra.util.EventPublisher;
import dev.haotangyuan.researcher.application.tool.annotation.ResearcherTool;
import dev.haotangyuan.researcher.infra.exception.WorkflowException;
import dev.haotangyuan.researcher.application.tool.ToolRegistry;
import dev.langchain4j.agent.tool.ToolExecutionRequest;
import dev.langchain4j.agent.tool.ToolSpecification;
import dev.langchain4j.data.message.ChatMessage;
import dev.langchain4j.data.message.SystemMessage;
import dev.langchain4j.data.message.ToolExecutionResultMessage;
import dev.langchain4j.data.message.UserMessage;
import dev.langchain4j.memory.chat.MessageWindowChatMemory;
import dev.langchain4j.model.chat.request.ChatRequest;
import dev.langchain4j.model.chat.request.ToolChoice;
import dev.langchain4j.model.chat.response.ChatResponse;
import dev.langchain4j.model.output.TokenUsage;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
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

    private static final String RESEARCHER_STAGE = ResearcherTool.class.getSimpleName();

    public String run(DeepResearchState state) {
        log.info("ResearcherAgent run: researchId='{}', topic='{}'", state.getResearchId(), state.getResearchTopic());
        Long researchEventId = eventPublisher.publishEvent(state.getResearchId(), EventType.RESEARCH,
                "深入研究: " + state.getResearchTopic(), null, state.getCurrentResearchEventId());
        state.setCurrentResearchEventId(researchEventId);
        
        AgentAbility agent = AgentAbility.builder()
                .memory(MessageWindowChatMemory.withMaxMessages(100))
                .chatModel(modelHandler.getModel(state.getResearchId()))
                .streamingChatModel(modelHandler.getStreamModel(state.getResearchId()))
                .build();
        
        SystemMessage systemMessage = SystemMessage.from(
            StrUtil.format(RESEARCH_AGENT_PROMPT,Map.of("date", DateUtil.today()))
        );
        agent.getMemory().add(systemMessage);
        agent.getMemory().add(UserMessage.from(state.getResearchTopic()));
        
        plan(agent, state);
        return compressResearch(agent, state);
    }

    private void plan(AgentAbility agent, DeepResearchState state) {
        // 核心限制: searchCount < maxSearchCount
        // 安全阀: researcherIterations < maxSearchCount * 2
        int maxSearchCount = state.getBudget().getMaxSearchCount();
        int maxIterations = maxSearchCount * 2;
        while (state.getSearchCount() < maxSearchCount 
                && state.getResearcherIterations() < maxIterations) {
            // 1. 获取决策
            List<ToolSpecification> toolSpecifications = toolRegistry.getToolSpecifications(RESEARCHER_STAGE);
            ChatRequest chatRequest = ChatRequest.builder()
                    .messages(agent.getMemory().messages())
                    .toolSpecifications(toolSpecifications)
                    .toolChoice(ToolChoice.REQUIRED)
                    .build();
            ChatResponse chatResponse = agent.getChatModel().chat(chatRequest);
            TokenUsage tokenUsage = chatResponse.tokenUsage();
            state.setTotalInputTokens(state.getTotalInputTokens() + tokenUsage.inputTokenCount());
            state.setTotalOutputTokens(state.getTotalOutputTokens() + tokenUsage.outputTokenCount());
            agent.getMemory().add(chatResponse.aiMessage());

            // 2. 执行工具
            action(agent, chatResponse.aiMessage().toolExecutionRequests(), state);
            
            // 3. 检查是否继续
            if (!chatResponse.aiMessage().hasToolExecutionRequests()) {
                break;
            }
            
            state.setResearcherIterations(state.getResearcherIterations() + 1);
        }
    }

    private void action(AgentAbility agent, List<ToolExecutionRequest> toolExecutionRequests, DeepResearchState state) {
        if (toolExecutionRequests == null || toolExecutionRequests.isEmpty()) {
            return;
        }
        
        for (ToolExecutionRequest toolExecutionRequest : toolExecutionRequests) {
            String result;
            
            if ("tavilySearch".equals(toolExecutionRequest.name())) {
                // 检查 tavilySearch 调用次数限制
                int maxSearchCount = state.getBudget().getMaxSearchCount();
                if (state.getSearchCount() >= maxSearchCount) {
                    log.warn("tavilySearch count limit reached: {}/{}",
                            state.getSearchCount(), maxSearchCount);
                    result = "已达到搜索配额限制，请根据已有信息完成研究";
                    agent.getMemory().add(ToolExecutionResultMessage.from(toolExecutionRequest, result));
                    continue;
                }
                
                try {
                    var argsNode = objectMapper.readTree(toolExecutionRequest.arguments());
                    String query = argsNode.get("query").asText();
                    int maxResults = argsNode.has("maxResults") ? argsNode.get("maxResults").asInt() : 3;
                    String topic = argsNode.has("topic") ? argsNode.get("topic").asText() : "general";
                    
                    // 设置 search 相关字段
                    state.setQuery(query);
                    state.setMaxResults(maxResults);
                    state.setTopic(topic);
                    state.setSearchResults(new HashMap<>());
                    state.setSearchNotes(new ArrayList<>());

                    result = searchAgent.run(state);
                    
                    // 增加 searchCount
                    state.setSearchCount(state.getSearchCount() + 1);
                } catch (Exception e) {
                    log.error("Failed to parse tavilySearch arguments", e);
                    throw new WorkflowException("Failed to parse tavilySearch arguments", e);
                }
            } else {
                var executor = toolRegistry.getExecutor(toolExecutionRequest.name());
                if (executor == null) {
                    log.warn("No executor found for tool {} in stage {}", toolExecutionRequest.name(), RESEARCHER_STAGE);
                    continue;
                }
                result = executor.execute(toolExecutionRequest, null);
            }
            
            // 收集 rawNotes 即工具执行结果 ThinkTool 和 Search 结果
            if ("thinkTool".equals(toolExecutionRequest.name())) {
                eventPublisher.publishEvent(state.getResearchId(), EventType.RESEARCH,
                        "分析中...", result, state.getCurrentResearchEventId());
            }
            state.getResearcherNotes().add(String.format("[%s] %s", toolExecutionRequest.name(), result));
            
            agent.getMemory().add(ToolExecutionResultMessage.from(toolExecutionRequest, result));
        }
    }

    private String compressResearch(AgentAbility agent, DeepResearchState state) {
        String systemPrompt = StrUtil.format(COMPRESS_RESEARCH_SYSTEM_PROMPT, Map.of("date", DateUtil.today()));
        
        List<ChatMessage> messages = new ArrayList<>();
        messages.add(SystemMessage.from(systemPrompt));
        // 跳过前两条（ResearcherAgent 的 system + user），只保留工具调用历史
        messages.addAll(agent.getMemory().messages().stream().skip(2).collect(Collectors.toList()));
        messages.add(UserMessage.from(
            StrUtil.format(COMPRESS_RESEARCH_HUMAN_MESSAGE, Map.of("research_topic", state.getResearchTopic()))));
        
        ChatRequest compressRequest = ChatRequest.builder()
                .messages(messages)
                .build();
        
        ChatResponse compressResponse = agent.getChatModel().chat(compressRequest);
        TokenUsage tokenUsage = compressResponse.tokenUsage();
        state.setTotalInputTokens(state.getTotalInputTokens() + tokenUsage.inputTokenCount());
        state.setTotalOutputTokens(state.getTotalOutputTokens() + tokenUsage.outputTokenCount());
        String compressedResearch = compressResponse.aiMessage().text();
        
        state.setCompressedResearch(compressedResearch);
        eventPublisher.publishEvent(state.getResearchId(), EventType.RESEARCH,
                "已完成该主题研究", compressedResearch.substring(0, Math.min(200, compressedResearch.length())) + "...", state.getCurrentResearchEventId());
        
        return compressedResearch;
    }
}
