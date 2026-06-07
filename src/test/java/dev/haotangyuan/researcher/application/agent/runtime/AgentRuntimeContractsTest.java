package dev.haotangyuan.researcher.application.agent.runtime;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class AgentRuntimeContractsTest {

    @Test
    void parsesSupportedFrameworkPropertyValues() {
        assertThat(AgentFramework.fromProperty("agentscope-java")).isEqualTo(AgentFramework.AGENTSCOPE_JAVA);
        assertThat(AgentFramework.fromProperty("langchain4j")).isEqualTo(AgentFramework.LANGCHAIN4J);
    }

    @Test
    void rejectsUnsupportedFrameworkPropertyValues() {
        assertThatThrownBy(() -> AgentFramework.fromProperty("other"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("Unsupported agent framework");
    }

    @Test
    void representsAssistantToolCallsAndToolResultsWithoutFrameworkTypes() {
        ResearchToolCall call = new ResearchToolCall("call-1", "thinkTool", "{\"reflection\":\"review\"}");

        ResearchMessage assistant = ResearchMessage.assistant("", List.of(call));
        ResearchMessage toolResult = ResearchMessage.toolResult(call, "Reflection recorded: review");

        assertThat(assistant.role()).isEqualTo(ResearchMessage.Role.ASSISTANT);
        assertThat(assistant.toolCalls()).containsExactly(call);
        assertThat(toolResult.role()).isEqualTo(ResearchMessage.Role.TOOL);
        assertThat(toolResult.toolCallId()).isEqualTo("call-1");
        assertThat(toolResult.toolName()).isEqualTo("thinkTool");
        assertThat(toolResult.text()).isEqualTo("Reflection recorded: review");
    }
}
