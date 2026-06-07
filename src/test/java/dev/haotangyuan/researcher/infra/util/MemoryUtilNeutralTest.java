package dev.haotangyuan.researcher.infra.util;

import dev.haotangyuan.researcher.application.agent.runtime.ResearchMemory;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchMessage;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolCall;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class MemoryUtilNeutralTest {

    @Test
    void rendersNeutralMessagesWithExistingRolePrefixes() {
        ResearchToolCall toolCall = new ResearchToolCall("call-1", "thinkTool", "{}");
        ResearchMemory memory = new ResearchMemory(10);
        memory.add(ResearchMessage.system("system prompt"));
        memory.add(ResearchMessage.user("user prompt"));
        memory.add(ResearchMessage.assistant("assistant reply"));
        memory.add(ResearchMessage.toolResult(toolCall, "tool output"));

        assertThat(MemoryUtil.toBufferString(memory)).isEqualTo("""
                System: system prompt
                Human: user prompt
                AI: assistant reply
                Tool: tool output""");
    }
}
