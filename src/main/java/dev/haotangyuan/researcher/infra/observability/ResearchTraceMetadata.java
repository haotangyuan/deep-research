package dev.haotangyuan.researcher.infra.observability;

public record ResearchTraceMetadata(
        String researchId,
        Long userId,
        String modelId,
        String budgetLevel,
        String agentFramework
) {
}
