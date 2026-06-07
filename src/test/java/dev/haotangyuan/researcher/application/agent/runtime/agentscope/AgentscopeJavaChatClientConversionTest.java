package dev.haotangyuan.researcher.application.agent.runtime.agentscope;

import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatRequest;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatResponse;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchMessage;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolCall;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolParameter;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolSpec;
import dev.haotangyuan.researcher.application.agent.runtime.ToolChoiceMode;
import io.agentscope.core.message.Msg;
import io.agentscope.core.message.MsgRole;
import io.agentscope.core.message.TextBlock;
import io.agentscope.core.message.ToolResultBlock;
import io.agentscope.core.message.ToolUseBlock;
import io.agentscope.core.model.ChatResponse;
import io.agentscope.core.model.ChatUsage;
import io.agentscope.core.model.GenerateOptions;
import io.agentscope.core.model.Model;
import io.agentscope.core.model.ToolChoice;
import io.agentscope.core.model.ToolSchema;
import org.junit.jupiter.api.Test;
import reactor.core.publisher.Flux;

import java.time.Duration;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class AgentscopeJavaChatClientConversionTest {

    @Test
    void mapsNeutralRequestAndResponseThroughAgentscopeTypes() {
        CapturingAgentscopeModel model = new CapturingAgentscopeModel(ChatResponse.builder()
                .content(List.of(
                        TextBlock.builder().text("thinking").build(),
                        ToolUseBlock.builder()
                                .id("call-1")
                                .name("thinkTool")
                                .input(Map.of("reflection", "review"))
                                .content("{\"reflection\":\"review\"}")
                                .build()))
                .usage(ChatUsage.builder().inputTokens(12).outputTokens(4).build())
                .finishReason("tool_calls")
                .build());
        AgentscopeJavaChatClient chatClient = new AgentscopeJavaChatClient(model, Duration.ofSeconds(1));

        ResearchToolCall previousToolCall = new ResearchToolCall("previous", "thinkTool", "{\"reflection\":\"old\"}");
        ResearchChatResponse response = chatClient.chat(new ResearchChatRequest(
                List.of(
                        ResearchMessage.system("system"),
                        ResearchMessage.user("plan"),
                        ResearchMessage.assistant("", List.of(previousToolCall)),
                        ResearchMessage.toolResult(previousToolCall, "recorded")),
                List.of(new ResearchToolSpec(
                        "thinkTool",
                        "Reflect",
                        List.of(new ResearchToolParameter("reflection", "Reflection text", true, String.class)))),
                ToolChoiceMode.REQUIRED));

        assertThat(model.lastMessages).hasSize(4);
        assertThat(model.lastMessages.get(0).getRole()).isEqualTo(MsgRole.SYSTEM);
        assertThat(model.lastMessages.get(1).getRole()).isEqualTo(MsgRole.USER);
        assertThat(model.lastMessages.get(2).getContentBlocks(ToolUseBlock.class))
                .singleElement()
                .satisfies(toolUse -> {
                    assertThat(toolUse.getId()).isEqualTo("previous");
                    assertThat(toolUse.getName()).isEqualTo("thinkTool");
                    assertThat(toolUse.getInput()).containsEntry("reflection", "old");
                });
        assertThat(model.lastMessages.get(3).getContentBlocks(ToolResultBlock.class))
                .singleElement()
                .satisfies(result -> {
                    assertThat(result.getId()).isEqualTo("previous");
                    assertThat(result.getName()).isEqualTo("thinkTool");
                });
        assertThat(model.lastOptions.getToolChoice()).isInstanceOf(ToolChoice.Required.class);
        assertThat(model.lastTools).singleElement()
                .satisfies(schema -> assertThat(schema.getName()).isEqualTo("thinkTool"));

        assertThat(response.aiMessage().text()).isEqualTo("thinking");
        assertThat(response.aiMessage().toolCalls()).containsExactly(
                new ResearchToolCall("call-1", "thinkTool", "{\"reflection\":\"review\"}"));
        assertThat(response.tokenUsage().inputTokenCount()).isEqualTo(12L);
        assertThat(response.tokenUsage().outputTokenCount()).isEqualTo(4L);
        assertThat(response.finishReason()).isEqualTo("tool_calls");
    }

    @Test
    void convertsToolSchemaAndRequiredParameters() {
        ToolSchema schema = AgentscopeJavaChatClient.toAgentscopeToolSpecs(List.of(new ResearchToolSpec(
                "tavilySearch",
                "Search web",
                List.of(
                        new ResearchToolParameter("query", "Search query", true, String.class),
                        new ResearchToolParameter("maxResults", "Maximum results", true, int.class),
                        new ResearchToolParameter("topic", "Topic type", false, String.class)))))
                .getFirst();

        assertThat(schema.getName()).isEqualTo("tavilySearch");
        assertThat(schema.getDescription()).isEqualTo("Search web");
        assertThat(schema.getParameters()).containsEntry("type", "object");
        assertThat(schema.getParameters()).containsKey("properties");
        assertThat(schema.getParameters()).containsEntry("required", List.of("query", "maxResults"));
        @SuppressWarnings("unchecked")
        Map<String, Object> properties = (Map<String, Object>) schema.getParameters().get("properties");
        assertThat(properties).containsKeys("query", "maxResults", "topic");
        assertThat(properties.get("maxResults")).isInstanceOf(Map.class);
        @SuppressWarnings("unchecked")
        Map<String, Object> maxResults = (Map<String, Object>) properties.get("maxResults");
        assertThat(maxResults).containsEntry("type", "integer");
    }

    @Test
    void mapsAutoToolChoiceToNoExplicitAgentscopeToolChoice() {
        GenerateOptions options = AgentscopeJavaChatClient.toAgentscopeGenerateOptions(ToolChoiceMode.AUTO);

        assertThat(options.getToolChoice()).isNull();
    }

    @Test
    void handlesMissingUsageAsZero() {
        ResearchChatResponse response = AgentscopeJavaChatClient.toResearchResponse(ChatResponse.builder()
                .content(List.of(TextBlock.builder().text("done").build()))
                .finishReason("stop")
                .build(), "gpt-test");

        assertThat(response.aiMessage().text()).isEqualTo("done");
        assertThat(response.tokenUsage().inputTokenCount()).isZero();
        assertThat(response.tokenUsage().outputTokenCount()).isZero();
        assertThat(response.finishReason()).isEqualTo("stop");
    }

    private static final class CapturingAgentscopeModel implements Model {
        private final ChatResponse response;
        private List<Msg> lastMessages;
        private List<ToolSchema> lastTools;
        private GenerateOptions lastOptions;

        private CapturingAgentscopeModel(ChatResponse response) {
            this.response = response;
        }

        @Override
        public Flux<ChatResponse> stream(List<Msg> messages, List<ToolSchema> tools, GenerateOptions options) {
            this.lastMessages = messages;
            this.lastTools = tools;
            this.lastOptions = options;
            return Flux.just(response);
        }

        @Override
        public String getModelName() {
            return "gpt-test";
        }
    }
}
