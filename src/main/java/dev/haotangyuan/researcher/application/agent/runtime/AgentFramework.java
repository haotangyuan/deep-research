package dev.haotangyuan.researcher.application.agent.runtime;

import java.util.Locale;

public enum AgentFramework {
    AGENTSCOPE_JAVA("agentscope-java"),
    LANGCHAIN4J("langchain4j");

    private final String propertyValue;

    AgentFramework(String propertyValue) {
        this.propertyValue = propertyValue;
    }

    public String propertyValue() {
        return propertyValue;
    }

    public static AgentFramework fromProperty(String value) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("Unsupported agent framework: " + value);
        }
        String normalized = value.trim().toLowerCase(Locale.ROOT);
        for (AgentFramework framework : values()) {
            if (framework.propertyValue.equals(normalized)) {
                return framework;
            }
        }
        throw new IllegalArgumentException("Unsupported agent framework: " + value);
    }
}
