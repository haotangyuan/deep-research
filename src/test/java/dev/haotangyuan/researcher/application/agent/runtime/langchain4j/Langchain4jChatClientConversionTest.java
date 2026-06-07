package dev.haotangyuan.researcher.application.agent.runtime.langchain4j;

import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatRequest;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatResponse;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchMessage;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolCall;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolParameter;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolSpec;
import dev.haotangyuan.researcher.application.agent.runtime.ToolChoiceMode;
import dev.langchain4j.agent.tool.ToolExecutionRequest;
import dev.langchain4j.data.message.AiMessage;
import dev.langchain4j.model.chat.ChatModel;
import dev.langchain4j.model.chat.request.ChatRequest;
import dev.langchain4j.model.chat.request.ToolChoice;
import dev.langchain4j.model.chat.response.ChatResponse;
import dev.langchain4j.model.output.TokenUsage;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class Langchain4jChatClientConversionTest {

    @Test
    void mapsNeutralRequestAndResponseThroughLangchain4jTypes() {
        ToolExecutionRequest langchainToolCall = ToolExecutionRequest.builder()
                .id("call-1")
                .name("thinkTool")
                .arguments("{\"reflection\":\"review\"}")
                .build();
        CapturingChatModel chatModel = new CapturingChatModel(ChatResponse.builder()
                .aiMessage(AiMessage.from("thinking", List.of(langchainToolCall)))
                .tokenUsage(new TokenUsage(12, 4))
                .build());
        Langchain4jChatClient chatClient = new Langchain4jChatClient(chatModel);

        ResearchChatResponse response = chatClient.chat(new ResearchChatRequest(
                List.of(ResearchMessage.user("plan")),
                List.of(new ResearchToolSpec(
                        "thinkTool",
                        "Reflect",
                        List.of(new ResearchToolParameter("reflection", "Reflection text", true, String.class)))),
                ToolChoiceMode.REQUIRED));

        assertThat(chatModel.lastRequest.messages()).hasSize(1);
        assertThat(chatModel.lastRequest.toolChoice()).isEqualTo(ToolChoice.REQUIRED);
        assertThat(chatModel.lastRequest.toolSpecifications()).singleElement()
                .satisfies(spec -> assertThat(spec.name()).isEqualTo("thinkTool"));
        assertThat(response.aiMessage().text()).isEqualTo("thinking");
        assertThat(response.aiMessage().toolCalls()).containsExactly(
                new ResearchToolCall("call-1", "thinkTool", "{\"reflection\":\"review\"}"));
        assertThat(response.tokenUsage().inputTokenCount()).isEqualTo(12L);
        assertThat(response.tokenUsage().outputTokenCount()).isEqualTo(4L);
    }

    private static final class CapturingChatModel implements ChatModel {
        private final ChatResponse response;
        private ChatRequest lastRequest;

        private CapturingChatModel(ChatResponse response) {
            this.response = response;
        }

        @Override
        public ChatResponse doChat(ChatRequest chatRequest) {
            this.lastRequest = chatRequest;
            return response;
        }
    }
}
