package dev.haotangyuan.researcher.application.agent.runtime;

public interface ResearchChatClient {
    ResearchChatResponse chat(ResearchChatRequest request);

    default ResearchChatResponse runAgent(ResearchAgentRequest request) {
        java.util.List<ResearchMessage> messages = new java.util.ArrayList<>(request.messages());
        ResearchTokenUsage totalUsage = ResearchTokenUsage.zero();
        ResearchMessage lastAssistantMessage = ResearchMessage.assistant("");
        int iterations = request.toolSpecifications().isEmpty() ? 1 : request.maxIterations();
        for (int i = 0; i < iterations; i++) {
            ResearchChatResponse response = chat(new ResearchChatRequest(
                    messages,
                    request.toolSpecifications(),
                    request.toolSpecifications().isEmpty() ? ToolChoiceMode.AUTO : ToolChoiceMode.REQUIRED));
            totalUsage = new ResearchTokenUsage(
                    totalUsage.inputTokenCount() + response.tokenUsage().inputTokenCount(),
                    totalUsage.outputTokenCount() + response.tokenUsage().outputTokenCount());
            lastAssistantMessage = response.aiMessage();
            messages.add(response.aiMessage());
            if (request.toolSpecifications().isEmpty() || response.aiMessage().toolCalls().isEmpty()) {
                break;
            }
            for (ResearchToolCall toolCall : response.aiMessage().toolCalls()) {
                String toolResult = request.toolExecutor().apply(toolCall);
                messages.add(ResearchMessage.toolResult(toolCall, toolResult));
            }
        }
        return new ResearchChatResponse(lastAssistantMessage, totalUsage, null);
    }
}
