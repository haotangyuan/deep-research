package dev.haotangyuan.researcher.application.agent.runtime;

public record ResearchTokenUsage(long inputTokenCount, long outputTokenCount) {
    public static ResearchTokenUsage zero() {
        return new ResearchTokenUsage(0L, 0L);
    }
}
