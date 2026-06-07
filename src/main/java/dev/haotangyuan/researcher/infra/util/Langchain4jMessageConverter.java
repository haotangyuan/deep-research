package dev.haotangyuan.researcher.infra.util;

import dev.haotangyuan.researcher.application.agent.runtime.ResearchMessage;
import dev.haotangyuan.researcher.domain.entity.ChatMessage;
import dev.langchain4j.data.message.AiMessage;
import dev.langchain4j.data.message.SystemMessage;
import dev.langchain4j.data.message.ToolExecutionResultMessage;
import dev.langchain4j.data.message.UserMessage;

import java.util.ArrayList;
import java.util.List;

/**
 * Converts persisted conversation messages into the current langchain4j runtime format.
 */
public final class Langchain4jMessageConverter {

    private Langchain4jMessageConverter() {
    }

    public static List<dev.langchain4j.data.message.ChatMessage> fromDbMessages(List<ChatMessage> dbMessages) {
        List<dev.langchain4j.data.message.ChatMessage> chatHistory = new ArrayList<>();
        for (ChatMessage msg : dbMessages) {
            if ("user".equals(msg.getRole())) {
                chatHistory.add(UserMessage.from(msg.getContent()));
            } else if ("assistant".equals(msg.getRole())) {
                chatHistory.add(AiMessage.from(msg.getContent()));
            }
        }
        return chatHistory;
    }

    public static List<dev.langchain4j.data.message.ChatMessage> fromResearchMessages(
            List<ResearchMessage> researchMessages
    ) {
        List<dev.langchain4j.data.message.ChatMessage> chatHistory = new ArrayList<>();
        for (ResearchMessage message : researchMessages) {
            if (message.role() == ResearchMessage.Role.USER) {
                chatHistory.add(UserMessage.from(message.text()));
            } else if (message.role() == ResearchMessage.Role.ASSISTANT) {
                chatHistory.add(AiMessage.from(message.text()));
            } else if (message.role() == ResearchMessage.Role.SYSTEM) {
                chatHistory.add(SystemMessage.from(message.text()));
            } else if (message.role() == ResearchMessage.Role.TOOL) {
                chatHistory.add(ToolExecutionResultMessage.from(
                        message.toolCallId(), message.toolName(), message.text()));
            }
        }
        return chatHistory;
    }
}
