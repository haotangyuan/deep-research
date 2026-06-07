package dev.haotangyuan.researcher.application.agent.runtime;

public record ResearchToolParameter(
        String name,
        String description,
        boolean required,
        Class<?> type
) {
}
