package dev.haotangyuan.researcher.application.model;

import dev.haotangyuan.researcher.application.agent.runtime.AgentFramework;
import dev.haotangyuan.researcher.application.agent.runtime.AgentRuntime;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatClient;
import dev.haotangyuan.researcher.domain.entity.Model;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class ModelHandlerRuntimeBoundaryTest {

    @Test
    void storesNeutralChatClientsCreatedBySelectedRuntime() {
        ResearchChatClient chatClient = request -> null;
        ModelHandler modelHandler = new ModelHandler(new FakeRuntime(chatClient));

        modelHandler.addModel("research-1", Model.builder().id("model-1").build());

        assertThat(modelHandler.getChatClient("research-1")).isSameAs(chatClient);
        modelHandler.removeModel("research-1");
        assertThat(modelHandler.getChatClient("research-1")).isNull();
    }

    private static final class FakeRuntime implements AgentRuntime {
        private final ResearchChatClient chatClient;

        private FakeRuntime(ResearchChatClient chatClient) {
            this.chatClient = chatClient;
        }

        @Override
        public AgentFramework framework() {
            return AgentFramework.LANGCHAIN4J;
        }

        @Override
        public ResearchChatClient createChatClient(Model model) {
            return chatClient;
        }
    }
}
