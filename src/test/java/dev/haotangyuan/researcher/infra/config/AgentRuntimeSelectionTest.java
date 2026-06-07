package dev.haotangyuan.researcher.infra.config;

import dev.haotangyuan.researcher.application.agent.runtime.AgentFramework;
import dev.haotangyuan.researcher.application.agent.runtime.AgentRuntime;
import dev.haotangyuan.researcher.application.agent.runtime.agentscope.AgentscopeJavaAgentRuntime;
import dev.haotangyuan.researcher.application.agent.runtime.langchain4j.Langchain4jAgentRuntime;
import dev.haotangyuan.researcher.application.model.ModelFactory;
import org.junit.jupiter.api.Test;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.autoconfigure.context.ConfigurationPropertiesAutoConfiguration;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import static org.assertj.core.api.Assertions.assertThat;

class AgentRuntimeSelectionTest {
    private final ApplicationContextRunner contextRunner = new ApplicationContextRunner()
            .withConfiguration(AutoConfigurations.of(ConfigurationPropertiesAutoConfiguration.class))
            .withUserConfiguration(
                    AgentRuntimeProps.class,
                    AgentscopeJavaAgentRuntime.class,
                    Langchain4jAgentRuntime.class,
                    ModelFactory.class)
            .withPropertyValues("llm.timeout=1");

    @Test
    void selectsAgentscopeRuntimeWhenConfigured() {
        contextRunner
                .withPropertyValues("research.agent.framework=agentscope-java")
                .run(context -> {
                    assertThat(context).hasSingleBean(AgentRuntime.class);
                    assertThat(context.getBean(AgentRuntime.class).framework())
                            .isEqualTo(AgentFramework.AGENTSCOPE_JAVA);
                });
    }

    @Test
    void selectsLangchain4jBackupRuntimeWhenConfigured() {
        contextRunner
                .withPropertyValues("research.agent.framework=langchain4j")
                .run(context -> {
                    assertThat(context).hasSingleBean(AgentRuntime.class);
                    assertThat(context.getBean(AgentRuntime.class).framework())
                            .isEqualTo(AgentFramework.LANGCHAIN4J);
                });
    }

    @Test
    void invalidRuntimeValueFailsStartup() {
        contextRunner
                .withPropertyValues("research.agent.framework=other")
                .run(context -> {
                    assertThat(context).hasFailed();
                    assertThat(context.getStartupFailure())
                            .hasRootCauseInstanceOf(IllegalArgumentException.class)
                            .hasRootCauseMessage("Unsupported agent framework: other");
                });
    }
}
