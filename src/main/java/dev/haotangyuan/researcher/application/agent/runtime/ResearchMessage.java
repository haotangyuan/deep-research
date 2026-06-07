package dev.haotangyuan.researcher.application.agent.runtime;

import java.util.List;

public record ResearchMessage(
        Role role,
        String text,
        List<ResearchToolCall> toolCalls,
        String toolCallId,
        String toolName
) {
    public enum Role {
        SYSTEM,
        USER,
        ASSISTANT,
        TOOL
    }

    public ResearchMessage {
        toolCalls = toolCalls == null ? List.of() : List.copyOf(toolCalls);
    }

    public static ResearchMessage system(String text) {
        return new ResearchMessage(Role.SYSTEM, text, List.of(), null, null);
    }

    public static ResearchMessage user(String text) {
        return new ResearchMessage(Role.USER, text, List.of(), null, null);
    }

    public static ResearchMessage assistant(String text) {
        return assistant(text, List.of());
    }

    public static ResearchMessage assistant(String text, List<ResearchToolCall> toolCalls) {
        return new ResearchMessage(Role.ASSISTANT, text, toolCalls, null, null);
    }

    public static ResearchMessage toolResult(ResearchToolCall toolCall, String result) {
        return new ResearchMessage(Role.TOOL, result, List.of(), toolCall.id(), toolCall.name());
    }
}
