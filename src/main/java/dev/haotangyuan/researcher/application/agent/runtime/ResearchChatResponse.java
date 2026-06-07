package dev.haotangyuan.researcher.application.agent.runtime;

public record ResearchChatResponse(
        ResearchMessage aiMessage,
        ResearchTokenUsage tokenUsage,
        String finishReason
) {
    public ResearchChatResponse {
        tokenUsage = tokenUsage == null ? ResearchTokenUsage.zero() : tokenUsage;
    }
}
