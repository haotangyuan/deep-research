package dev.haotangyuan.researcher.application.agent;

import cn.hutool.core.collection.CollUtil;
import cn.hutool.core.date.DateUtil;
import cn.hutool.core.util.StrUtil;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.haotangyuan.researcher.infra.data.EventType;
import dev.haotangyuan.researcher.application.model.ModelHandler;
import dev.haotangyuan.researcher.application.schema.ScopeSchema;
import dev.haotangyuan.researcher.application.state.DeepResearchState;
import dev.haotangyuan.researcher.application.data.WorkflowStatus;
import dev.haotangyuan.researcher.infra.util.EventPublisher;
import dev.haotangyuan.researcher.infra.util.MemoryUtil;
import dev.langchain4j.data.message.AiMessage;
import dev.langchain4j.data.message.UserMessage;
import dev.langchain4j.memory.chat.MessageWindowChatMemory;
import dev.langchain4j.model.chat.request.ChatRequest;
import dev.langchain4j.model.chat.response.ChatResponse;
import dev.langchain4j.model.output.TokenUsage;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.Map;

import static dev.haotangyuan.researcher.application.prompt.ScopePrompts.CLARIFY_WITH_USER_INSTRUCTIONS;
import static dev.haotangyuan.researcher.application.prompt.ScopePrompts.TRANSFORM_MESSAGES_INTO_RESEARCH_TOPIC_PROMPT;

/**
 * @author: haotangyuan
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class ScopeAgent {
    private final ModelHandler modelHandler;
    private final ObjectMapper objectMapper;
    private final EventPublisher eventPublisher;

    public void run(DeepResearchState state) {
        state.setStatus(WorkflowStatus.IN_SCOPE);
        UserMessage userInput = (UserMessage) CollUtil.getLast(state.getChatHistory());
        Long scopeEventId = eventPublisher.publishEvent(state.getResearchId(),
                EventType.SCOPE, "正在分析您的研究需求...", userInput.singleText());
        state.setCurrentScopeEventId(scopeEventId);
        AgentAbility agent = AgentAbility.builder()
                .memory(MessageWindowChatMemory.withMaxMessages(100))
                .chatModel(modelHandler.getModel(state.getResearchId()))
                .streamingChatModel(modelHandler.getStreamModel(state.getResearchId()))
                .build();
        agent.getMemory().add(state.getChatHistory());
        clarifyUserInstructions(agent, state);
        if (state.getClarifyWithUserSchema().needClarification()) {
            return;
        }
        writeResearchBrief(agent, state);
    }

    private void clarifyUserInstructions(AgentAbility agent, DeepResearchState state) {
        String messages = MemoryUtil.toBufferString(agent.getMemory());
        UserMessage userMessage = UserMessage.from(
            StrUtil.format(CLARIFY_WITH_USER_INSTRUCTIONS, Map.of(
                "messages", messages,
                "date", DateUtil.today()
            ))
        );
        ChatRequest chatRequest = ChatRequest.builder()
                .messages(userMessage)
                .build();
        ChatResponse chatResponse = agent.getChatModel().chat(chatRequest);
        TokenUsage tokenUsage = chatResponse.tokenUsage();
        state.setTotalInputTokens(state.getTotalInputTokens() + tokenUsage.inputTokenCount());
        state.setTotalOutputTokens(state.getTotalOutputTokens() + tokenUsage.outputTokenCount());
        String jsonResponse = chatResponse.aiMessage().text();
        try {
            ScopeSchema.ClarifyWithUserSchema clarifyResult = objectMapper.readValue(
                    jsonResponse, ScopeSchema.ClarifyWithUserSchema.class);
            if (clarifyResult.needClarification()) {
                agent.getMemory().add(AiMessage.from(clarifyResult.question()));
                state.setStatus(WorkflowStatus.NEED_CLARIFICATION);
                eventPublisher.publishEvent(state.getResearchId(), EventType.SCOPE,
                        "需要您提供更多信息", clarifyResult.question(), state.getCurrentScopeEventId());
                eventPublisher.publishMessage(state.getResearchId(), "assistant", clarifyResult.question());
            } else {
                agent.getMemory().add(AiMessage.from(clarifyResult.verification()));
                eventPublisher.publishEvent(state.getResearchId(), EventType.SCOPE,
                        "研究需求已明确", clarifyResult.verification(), state.getCurrentScopeEventId());
            }
            state.setClarifyWithUserSchema(clarifyResult);
        } catch (Exception e) {
            log.error("Failed to parse JSON response: {}", jsonResponse, e);
            state.setStatus(WorkflowStatus.FAILED);
            return; // 失败后直接返回
        }
    }

    private void writeResearchBrief(AgentAbility agent, DeepResearchState state) {
        String messages = MemoryUtil.toBufferString(agent.getMemory());
        UserMessage userMessage = UserMessage.from(
                StrUtil.format(TRANSFORM_MESSAGES_INTO_RESEARCH_TOPIC_PROMPT, Map.of(
                    "messages", messages,
                    "date", DateUtil.today()
                )));
        ChatRequest chatRequest = ChatRequest.builder()
                .messages(userMessage)
                .build();
        ChatResponse chatResponse = agent.getChatModel().chat(chatRequest);
        TokenUsage tokenUsage = chatResponse.tokenUsage();
        state.setTotalInputTokens(state.getTotalInputTokens() + tokenUsage.inputTokenCount());
        state.setTotalOutputTokens(state.getTotalOutputTokens() + tokenUsage.outputTokenCount());
        String jsonResponse = chatResponse.aiMessage().text();
        try {
            ScopeSchema.ResearchQuestion researchQuestion = objectMapper.readValue(
                    jsonResponse, ScopeSchema.ResearchQuestion.class);
            agent.getMemory().add(AiMessage.from(researchQuestion.researchBrief()));
            eventPublisher.publishEvent(state.getResearchId(), EventType.SCOPE,
                    "已制定研究计划", researchQuestion.researchBrief(), state.getCurrentScopeEventId());
            state.setResearchQuestion(researchQuestion);
            String researchBrief = researchQuestion.researchBrief();
            state.setResearchBrief(researchBrief);
        } catch (Exception e) {
            log.error("Failed to parse JSON response: {}", jsonResponse, e);
            state.setStatus(WorkflowStatus.FAILED);
        }
    }
}
