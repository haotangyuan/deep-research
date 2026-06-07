package dev.haotangyuan.researcher.infra.config;

import dev.haotangyuan.researcher.application.agent.runtime.AgentFramework;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Configuration
@ConfigurationProperties(prefix = "research.agent")
public class AgentRuntimeProps {
    private String framework = AgentFramework.AGENTSCOPE_JAVA.propertyValue();

    public AgentFramework framework() {
        return AgentFramework.fromProperty(framework);
    }

    public String getFramework() {
        return framework;
    }

    public void setFramework(String framework) {
        AgentFramework.fromProperty(framework);
        this.framework = framework;
    }
}
