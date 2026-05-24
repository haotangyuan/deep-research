package dev.haotangyuan.researcher.application.agent;

import dev.langchain4j.memory.ChatMemory;
import dev.langchain4j.model.chat.ChatModel;
import dev.langchain4j.model.chat.StreamingChatModel;
import lombok.Builder;
import lombok.Data;

/**
 * @author: haotangyuan
 */
@Data
@Builder
public class AgentAbility {
    private final ChatMemory memory;
    private final ChatModel chatModel;
    private final StreamingChatModel streamingChatModel;
}
