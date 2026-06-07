package dev.haotangyuan.researcher.infra.util;

import dev.haotangyuan.researcher.domain.entity.ChatMessage;
import dev.langchain4j.data.message.AiMessage;
import dev.langchain4j.data.message.UserMessage;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class Langchain4jMessageConverterTest {

    @Test
    void convertsPersistedUserAndAssistantMessagesInOrder() {
        List<ChatMessage> dbMessages = List.of(
                message("user", "first user"),
                message("assistant", "assistant reply"),
                message("system", "ignored"),
                message("user", "second user")
        );

        List<dev.langchain4j.data.message.ChatMessage> converted =
                Langchain4jMessageConverter.fromDbMessages(dbMessages);

        assertThat(converted).hasSize(3);
        assertThat(converted.get(0)).isInstanceOf(UserMessage.class);
        assertThat(((UserMessage) converted.get(0)).singleText()).isEqualTo("first user");
        assertThat(converted.get(1)).isInstanceOf(AiMessage.class);
        assertThat(((AiMessage) converted.get(1)).text()).isEqualTo("assistant reply");
        assertThat(converted.get(2)).isInstanceOf(UserMessage.class);
        assertThat(((UserMessage) converted.get(2)).singleText()).isEqualTo("second user");
    }

    private static ChatMessage message(String role, String content) {
        return ChatMessage.builder()
                .role(role)
                .content(content)
                .build();
    }
}
