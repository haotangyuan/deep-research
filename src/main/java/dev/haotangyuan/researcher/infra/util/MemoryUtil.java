package dev.haotangyuan.researcher.infra.util;

import dev.langchain4j.data.message.*;
import dev.langchain4j.memory.ChatMemory;
import org.springframework.stereotype.Component;

import java.util.stream.Collectors;

/**
 * @author: haotangyuan
 */
@Component
public class MemoryUtil {
    public static String toBufferString(ChatMemory memory) {
        return memory.messages().stream()
                .map(MemoryUtil::renderMessage)
                .collect(Collectors.joining("\n"));
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
