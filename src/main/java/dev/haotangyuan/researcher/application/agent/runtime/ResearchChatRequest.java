package dev.haotangyuan.researcher.application.agent.runtime;

import java.util.List;

public record ResearchChatRequest(
        List<ResearchMessage> messages,
        List<ResearchToolSpec> toolSpecifications,
        ToolChoiceMode toolChoice
) {
    public ResearchChatRequest {
        messages = messages == null ? List.of() : List.copyOf(messages);
        toolSpecifications = toolSpecifications == null ? List.of() : List.copyOf(toolSpecifications);
        toolChoice = toolChoice == null ? ToolChoiceMode.AUTO : toolChoice;
    }

    public static ResearchChatRequest textOnly(List<ResearchMessage> messages) {
        return new ResearchChatRequest(messages, List.of(), ToolChoiceMode.AUTO);
    }
}
