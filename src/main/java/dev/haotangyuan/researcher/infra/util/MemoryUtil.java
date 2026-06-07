package dev.haotangyuan.researcher.infra.util;

import dev.haotangyuan.researcher.application.agent.runtime.ResearchMemory;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchMessage;
import dev.langchain4j.data.message.*;
import dev.langchain4j.memory.ChatMemory;
import org.springframework.stereotype.Component;

import java.util.stream.Collectors;

/**
 * @author: haotangyuan
 */
@Component
public class MemoryUtil {
    public static String toBufferString(ResearchMemory memory) {
        return memory.messages().stream()
                .map(MemoryUtil::renderMessage)
                .collect(Collectors.joining("\n"));
    }

    public static String toBufferString(ChatMemory memory) {
        return memory.messages().stream()
                .map(MemoryUtil::renderMessage)
                .collect(Collectors.joining("\n"));
    }

    private static String renderMessage(ResearchMessage message) {
        if (message.role() == ResearchMessage.Role.USER) {
            return "Human: " + message.text();
        }
        if (message.role() == ResearchMessage.Role.ASSISTANT) {
            return "AI: " + message.text();
        }
        if (message.role() == ResearchMessage.Role.SYSTEM) {
            return "System: " + message.text();
        }
        if (message.role() == ResearchMessage.Role.TOOL) {
            return "Tool: " + message.text();
        }
        return message.role() + ": " + message;
    }

    private static String renderMessage(ChatMessage message) {
        if (message instanceof UserMessage user) {
            return "Human: " + user.singleText();
        }
        if (message instanceof AiMessage ai) {
            return "AI: " + ai.text();
        }
        if (message instanceof SystemMessage system) {
            return "System: " + system.text();
        }
        if (message instanceof ToolExecutionResultMessage tool) {
            return "Tool: " + tool.text();
        }
        return message.type() + ": " + message;
    }
}
