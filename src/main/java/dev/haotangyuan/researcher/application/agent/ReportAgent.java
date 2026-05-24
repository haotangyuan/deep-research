package dev.haotangyuan.researcher.application.agent;

import org.springframework.stereotype.Component;

import cn.hutool.core.date.DateUtil;
import cn.hutool.core.util.StrUtil;
import dev.haotangyuan.researcher.infra.data.EventType;
import dev.haotangyuan.researcher.application.data.WorkflowStatus;
import dev.haotangyuan.researcher.infra.util.EventPublisher;
import dev.haotangyuan.researcher.application.model.ModelHandler;
import dev.haotangyuan.researcher.application.state.DeepResearchState;
import dev.langchain4j.data.message.UserMessage;
import dev.langchain4j.memory.chat.MessageWindowChatMemory;
import dev.langchain4j.model.chat.request.ChatRequest;
import dev.langchain4j.model.chat.response.ChatResponse;
import dev.langchain4j.model.output.TokenUsage;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;

import java.util.Map;

import static dev.haotangyuan.researcher.application.prompt.ReportPrompts.REPORT_AGENT_PROMPT;

/**
 * Report Agent - generates a final report based on researchers' notes
 * @author: haotangyuan
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class ReportAgent {
    private final ModelHandler modelHandler;
    private final EventPublisher eventPublisher;

    public String run(DeepResearchState state) {
        state.setStatus(WorkflowStatus.IN_REPORT);
        eventPublisher.publishEvent(state.getResearchId(), 
                EventType.REPORT, "正在生成研究报告...", null);
        AgentAbility agent = AgentAbility.builder()
                .memory(MessageWindowChatMemory.withMaxMessages(100))
                .chatModel(modelHandler.getModel(state.getResearchId()))
                .streamingChatModel(modelHandler.getStreamModel(state.getResearchId()))
                .build();
        UserMessage userMessage = UserMessage.from(
            StrUtil.format(REPORT_AGENT_PROMPT, Map.of(
                "research_brief", state.getResearchBrief(),
                "date", DateUtil.today(),
                "findings", StrUtil.join("\n", state.getSupervisorNotes())
            )));
        agent.getMemory().add(userMessage);
        action(agent, state);
        return state.getReport();
    }

    public void action(AgentAbility agent, DeepResearchState state) {
        ChatRequest chatRequest = ChatRequest.builder()
                .messages(agent.getMemory().messages())
                .build();
        ChatResponse chatResponse = agent.getChatModel().chat(chatRequest);
        TokenUsage tokenUsage = chatResponse.tokenUsage();
        state.setTotalInputTokens(state.getTotalInputTokens() + tokenUsage.inputTokenCount());
        state.setTotalOutputTokens(state.getTotalOutputTokens() + tokenUsage.outputTokenCount());
        agent.getMemory().add(chatResponse.aiMessage());
        state.setReport(chatResponse.aiMessage().text());
        eventPublisher.publishEvent(state.getResearchId(), EventType.REPORT,
                "研究报告已完成", null);
        eventPublisher.publishMessage(state.getResearchId(), "assistant", chatResponse.aiMessage().text());
    }
}
