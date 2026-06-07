package dev.haotangyuan.researcher.infra.util;

import dev.haotangyuan.researcher.application.agent.runtime.ResearchMessage;
import dev.haotangyuan.researcher.domain.entity.ChatMessage;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class ResearchMessageConverterTest {

    @Test
    void convertsPersistedMessagesIntoNeutralRuntimeMessages() {
        List<ChatMessage> dbMessages = List.of(
                message("user", "first user"),
                message("assistant", "assistant reply"),
                message("system", "ignored"),
                message("user", "second user")
        );

        List<ResearchMessage> converted = ResearchMessageConverter.fromDbMessages(dbMessages);

        assertThat(converted).containsExactly(
                ResearchMessage.user("first user"),
                ResearchMessage.assistant("assistant reply"),
                ResearchMessage.user("second user")
        );
    }

    private static ChatMessage message(String role, String content) {
        return ChatMessage.builder()
                .role(role)
                .content(content)
                .build();
    }
}
