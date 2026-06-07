package dev.haotangyuan.researcher.infra.config;

import dev.haotangyuan.researcher.application.agent.runtime.AgentFramework;
import org.junit.jupiter.api.Test;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.autoconfigure.context.ConfigurationPropertiesAutoConfiguration;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import static org.assertj.core.api.Assertions.assertThat;

class AgentRuntimePropsTest {

    private final ApplicationContextRunner contextRunner = new ApplicationContextRunner()
            .withConfiguration(AutoConfigurations.of(ConfigurationPropertiesAutoConfiguration.class))
            .withUserConfiguration(AgentRuntimeProps.class);

    @Test
    void defaultsToAgentscopeJavaRuntime() {
        assertThat(new AgentRuntimeProps().framework()).isEqualTo(AgentFramework.AGENTSCOPE_JAVA);
    }

    @Test
    void bindsLangchain4jRuntime() {
        contextRunner
                .withPropertyValues("research.agent.framework=langchain4j")
                .run(context -> assertThat(context.getBean(AgentRuntimeProps.class).framework())
                        .isEqualTo(AgentFramework.LANGCHAIN4J));
    }

    @Test
    void rejectsUnsupportedRuntime() {
        contextRunner
                .withPropertyValues("research.agent.framework=other")
                .run(context -> assertThat(context).hasFailed());
    }
}
