package dev.haotangyuan.researcher.application.agent.runtime;

import java.util.List;
import java.util.Map;
import java.util.function.Function;

public record ResearchAgentRequest(
        String stageName,
        String systemPrompt,
        List<ResearchMessage> messages,
        List<ResearchToolSpec> toolSpecifications,
        Function<ResearchToolCall, String> toolExecutor,
        int maxIterations,
        Map<String, Object> runtimeContext
) {
    public ResearchAgentRequest {
        messages = messages == null ? List.of() : List.copyOf(messages);
        toolSpecifications = toolSpecifications == null ? List.of() : List.copyOf(toolSpecifications);
        maxIterations = maxIterations <= 0 ? 10 : maxIterations;
        runtimeContext = runtimeContext == null ? Map.of() : Map.copyOf(runtimeContext);
    }

    public static ResearchAgentRequest textOnly(
            String stageName,
            String systemPrompt,
            List<ResearchMessage> messages) {
        return textOnly(stageName, systemPrompt, messages, Map.of());
    }

    public static ResearchAgentRequest textOnly(
            String stageName,
            String systemPrompt,
            List<ResearchMessage> messages,
            Map<String, Object> runtimeContext) {
        return new ResearchAgentRequest(
                stageName,
                systemPrompt,
                messages,
                List.of(),
                ignored -> "",
                1,
                runtimeContext);
    }
}
