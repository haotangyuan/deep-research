package dev.haotangyuan.researcher.application.agent;

import org.springframework.stereotype.Component;

import cn.hutool.core.date.DateUtil;
import cn.hutool.core.util.StrUtil;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchAgentRequest;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatRequest;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatResponse;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchMemory;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchMessage;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchTokenUsage;
import dev.haotangyuan.researcher.infra.data.EventType;
import dev.haotangyuan.researcher.application.data.WorkflowStatus;
import dev.haotangyuan.researcher.infra.util.EventPublisher;
import dev.haotangyuan.researcher.application.model.ModelHandler;
import dev.haotangyuan.researcher.application.state.DeepResearchState;
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
                .memory(new ResearchMemory(100))
                .chatClient(modelHandler.getChatClient(state.getResearchId()))
                .build();
        ResearchMessage userMessage = ResearchMessage.user(
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
        ResearchChatResponse chatResponse = agent.getChatClient().runAgent(
                ResearchAgentRequest.textOnly(
                        "ReportAgent",
                        "",
                        agent.getMemory().messages(),
                        state.traceContext()));
        addTokenUsage(state, chatResponse.tokenUsage());
        agent.getMemory().add(chatResponse.aiMessage());
        state.setReport(chatResponse.aiMessage().text());
        eventPublisher.publishEvent(state.getResearchId(), EventType.REPORT,
                "研究报告已完成", null);
        eventPublisher.publishMessage(state.getResearchId(), "assistant", chatResponse.aiMessage().text());
    }

    private void addTokenUsage(DeepResearchState state, ResearchTokenUsage tokenUsage) {
        state.addTokenUsage(tokenUsage);
    }
}
