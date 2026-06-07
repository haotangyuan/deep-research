package dev.haotangyuan.researcher.application.agent.runtime;

import java.util.List;

public record ResearchToolSpec(
        String name,
        String description,
        List<ResearchToolParameter> parameters
) {
    public ResearchToolSpec {
        parameters = parameters == null ? List.of() : List.copyOf(parameters);
    }
}
