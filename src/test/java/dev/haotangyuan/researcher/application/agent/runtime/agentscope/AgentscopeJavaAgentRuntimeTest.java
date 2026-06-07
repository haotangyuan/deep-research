package dev.haotangyuan.researcher.application.agent.runtime.agentscope;

import dev.haotangyuan.researcher.application.agent.runtime.AgentFramework;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatClient;
import dev.haotangyuan.researcher.domain.entity.Model;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class AgentscopeJavaAgentRuntimeTest {

    @Test
    void createsOpenAiCompatibleAgentscopeChatClientFromExistingModelRecord() {
        AgentscopeJavaAgentRuntime runtime = new AgentscopeJavaAgentRuntime(3);

        ResearchChatClient chatClient = runtime.createChatClient(Model.builder()
                .id("model-1")
                .model("gpt-4o-mini")
                .baseUrl("http://localhost:8080/v1")
                .apiKey("test-key")
                .build());

        assertThat(runtime.framework()).isEqualTo(AgentFramework.AGENTSCOPE_JAVA);
        assertThat(chatClient).isInstanceOf(AgentscopeJavaChatClient.class);
    }
}
