package dev.haotangyuan.researcher.application.agent.runtime;

import dev.haotangyuan.researcher.application.agent.runtime.agentscope.AgentscopeJavaAgentRuntime;
import dev.haotangyuan.researcher.application.agent.runtime.langchain4j.Langchain4jAgentRuntime;
import dev.haotangyuan.researcher.application.model.ModelFactory;
import dev.haotangyuan.researcher.domain.entity.Model;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

@Tag("integration")
class RuntimeLiveIntegrationTest {
    private static final String LIVE_FLAG = "DEEP_RESEARCH_LIVE_LLM_TESTS";
    private static final String BASE_URL = "DEEP_RESEARCH_LIVE_BASE_URL";
    private static final String API_KEY = "DEEP_RESEARCH_LIVE_API_KEY";
    private static final String MODEL = "DEEP_RESEARCH_LIVE_MODEL";

    @ParameterizedTest
    @EnumSource(AgentFramework.class)
    void minimalOpenAiCompatibleChatWorksWhenLiveEnvIsEnabled(AgentFramework framework) {
        Assumptions.assumeTrue(Boolean.parseBoolean(System.getenv(LIVE_FLAG)),
                "Set " + LIVE_FLAG + "=true to run live LLM integration tests");
        Assumptions.assumeTrue(hasText(System.getenv(BASE_URL)), BASE_URL + " is required");
        Assumptions.assumeTrue(hasText(System.getenv(API_KEY)), API_KEY + " is required");
        Assumptions.assumeTrue(hasText(System.getenv(MODEL)), MODEL + " is required");

        AgentRuntime runtime = runtimeFor(framework);
        ResearchChatClient chatClient = runtime.createChatClient(Model.builder()
                .id("live-" + framework.propertyValue())
                .model(System.getenv(MODEL))
                .baseUrl(System.getenv(BASE_URL))
                .apiKey(System.getenv(API_KEY))
                .build());

        ResearchChatResponse response = chatClient.chat(ResearchChatRequest.textOnly(
                List.of(ResearchMessage.user("Reply with one short sentence."))));

        assertThat(response.aiMessage().text()).isNotBlank();
        assertThat(response.tokenUsage().inputTokenCount()).isGreaterThanOrEqualTo(0L);
        assertThat(response.tokenUsage().outputTokenCount()).isGreaterThanOrEqualTo(0L);
    }

    private static AgentRuntime runtimeFor(AgentFramework framework) {
        if (framework == AgentFramework.AGENTSCOPE_JAVA) {
            return new AgentscopeJavaAgentRuntime(30);
        }
        ModelFactory modelFactory = new ModelFactory();
        modelFactory.setTimeout(30);
        modelFactory.setLogRequestsEnabled(false);
        modelFactory.setLogResponsesEnabled(false);
        return new Langchain4jAgentRuntime(modelFactory);
    }

    private static boolean hasText(String value) {
        return value != null && !value.isBlank();
    }
}
