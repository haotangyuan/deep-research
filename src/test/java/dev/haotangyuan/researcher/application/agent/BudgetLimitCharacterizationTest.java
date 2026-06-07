package dev.haotangyuan.researcher.application.agent;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchMemory;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchMessage;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolCall;
import dev.haotangyuan.researcher.application.state.DeepResearchState;
import dev.haotangyuan.researcher.infra.config.BudgetProps;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class BudgetLimitCharacterizationTest {

    @Test
    void supervisorReturnsQuotaGuidanceWhenConductResearchLimitReached() throws Exception {
        SupervisorAgent supervisorAgent = new SupervisorAgent(
                null, new ObjectMapper(), null, null, null);
        AgentAbility agent = agentAbility();
        DeepResearchState state = DeepResearchState.builder()
                .budget(budget(1, 1))
                .conductCount(1)
                .supervisorNotes(new ArrayList<>())
                .build();

        invokeSupervisorAction(supervisorAgent, agent, List.of(toolCall(
                "call-1", "conductResearch", "{\"researchTopic\":\"topic\"}")), state);

        assertThat(state.getConductCount()).isEqualTo(1);
        assertThat(state.getSupervisorNotes()).isEmpty();
        assertThat(agent.getMemory().messages()).hasSize(1);
        ResearchMessage resultMessage = agent.getMemory().messages().getFirst();
        assertThat(resultMessage.role()).isEqualTo(ResearchMessage.Role.TOOL);
        assertThat(resultMessage.toolName()).isEqualTo("conductResearch");
        assertThat(resultMessage.text()).isEqualTo("已达到研究任务配额限制，请调用 researchComplete 完成研究");
    }

    @Test
    void researcherReturnsQuotaGuidanceWhenSearchLimitReached() throws Exception {
        ResearcherAgent researcherAgent = new ResearcherAgent(
                null, null, new ObjectMapper(), null, null);
        AgentAbility agent = agentAbility();
        DeepResearchState state = DeepResearchState.builder()
                .budget(budget(1, 1))
                .searchCount(1)
                .researcherNotes(new ArrayList<>())
                .build();

        invokeResearcherAction(researcherAgent, agent, List.of(toolCall(
                "call-2", "tavilySearch", "{\"query\":\"topic\",\"maxResults\":3,\"topic\":\"general\"}")), state);

        assertThat(state.getSearchCount()).isEqualTo(1);
        assertThat(state.getResearcherNotes()).isEmpty();
        assertThat(agent.getMemory().messages()).hasSize(1);
        ResearchMessage resultMessage = agent.getMemory().messages().getFirst();
        assertThat(resultMessage.role()).isEqualTo(ResearchMessage.Role.TOOL);
        assertThat(resultMessage.toolName()).isEqualTo("tavilySearch");
        assertThat(resultMessage.text()).isEqualTo("已达到搜索配额限制，请根据已有信息完成研究");
    }

    private static AgentAbility agentAbility() {
        return AgentAbility.builder()
                .memory(new ResearchMemory(100))
                .build();
    }

    private static BudgetProps.BudgetLevel budget(int maxConductCount, int maxSearchCount) {
        BudgetProps.BudgetLevel budget = new BudgetProps.BudgetLevel();
        budget.setMaxConductCount(maxConductCount);
        budget.setMaxSearchCount(maxSearchCount);
        budget.setMaxConcurrentUnits(1);
        return budget;
    }

    private static ResearchToolCall toolCall(String id, String name, String arguments) {
        return new ResearchToolCall(id, name, arguments);
    }

    private static void invokeSupervisorAction(
            SupervisorAgent supervisorAgent,
            AgentAbility agent,
            List<ResearchToolCall> toolCalls,
            DeepResearchState state
    ) throws Exception {
        Method action = SupervisorAgent.class.getDeclaredMethod(
                "action", AgentAbility.class, List.class, DeepResearchState.class);
        action.setAccessible(true);
        action.invoke(supervisorAgent, agent, toolCalls, state);
    }

    private static void invokeResearcherAction(
            ResearcherAgent researcherAgent,
            AgentAbility agent,
            List<ResearchToolCall> toolCalls,
            DeepResearchState state
    ) throws Exception {
        Method action = ResearcherAgent.class.getDeclaredMethod(
                "action", AgentAbility.class, List.class, DeepResearchState.class);
        action.setAccessible(true);
        action.invoke(researcherAgent, agent, toolCalls, state);
    }
}
