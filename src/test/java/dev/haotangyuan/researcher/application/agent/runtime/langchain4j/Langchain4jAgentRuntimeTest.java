package dev.haotangyuan.researcher.application.agent.runtime.langchain4j;

import dev.haotangyuan.researcher.application.agent.runtime.AgentFramework;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatClient;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatRequest;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchMessage;
import dev.haotangyuan.researcher.application.model.ModelFactory;
import dev.haotangyuan.researcher.domain.entity.Model;
import dev.langchain4j.data.message.AiMessage;
import dev.langchain4j.model.chat.ChatModel;
import dev.langchain4j.model.chat.request.ChatRequest;
import dev.langchain4j.model.chat.response.ChatResponse;
import dev.langchain4j.model.output.TokenUsage;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class Langchain4jAgentRuntimeTest {

    @Test
    void createsNeutralChatClientFromExistingModelFactory() {
        FakeChatModel fakeChatModel = new FakeChatModel();
        Langchain4jAgentRuntime runtime = new Langchain4jAgentRuntime(new FakeModelFactory(fakeChatModel));

        ResearchChatClient chatClient = runtime.createChatClient(Model.builder().id("model-1").build());

        assertThat(runtime.framework()).isEqualTo(AgentFramework.LANGCHAIN4J);
        assertThat(chatClient.chat(ResearchChatRequest.textOnly(List.of(ResearchMessage.user("hello"))))
                .aiMessage()
                .text()).isEqualTo("ok");
        assertThat(fakeChatModel.lastRequest.messages()).hasSize(1);
    }

    private static final class FakeModelFactory extends ModelFactory {
        private final ChatModel chatModel;

        private FakeModelFactory(ChatModel chatModel) {
            this.chatModel = chatModel;
        }

        @Override
        public ChatModel createChatModel(Model model) {
            return chatModel;
        }
    }

    private static final class FakeChatModel implements ChatModel {
        private ChatRequest lastRequest;

        @Override
        public ChatResponse doChat(ChatRequest chatRequest) {
            lastRequest = chatRequest;
            return ChatResponse.builder()
                    .aiMessage(AiMessage.from("ok"))
                    .tokenUsage(new TokenUsage(1, 2))
                    .build();
        }
    }
}
