package dev.haotangyuan.researcher.application.agent;

import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatClient;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatRequest;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatResponse;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchMemory;
import dev.langchain4j.memory.ChatMemory;
import dev.langchain4j.model.chat.ChatModel;
import dev.langchain4j.model.chat.StreamingChatModel;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;

import static org.assertj.core.api.Assertions.assertThat;

class AgentAbilityRuntimeBoundaryTest {

    @Test
    void usesNeutralMemoryAndChatClientInsteadOfFrameworkTypes() {
        ResearchChatClient chatClient = request -> new ResearchChatResponse(null, null, null);
        AgentAbility ability = AgentAbility.builder()
                .memory(new ResearchMemory(100))
                .chatClient(chatClient)
                .build();

        assertThat(ability.getMemory()).isInstanceOf(ResearchMemory.class);
        assertThat(ability.getChatClient()).isSameAs(chatClient);
        assertThat(Arrays.stream(AgentAbility.class.getDeclaredFields())
                .map(Field::getType))
                .doesNotContain(ChatMemory.class, ChatModel.class, StreamingChatModel.class);
    }
}
