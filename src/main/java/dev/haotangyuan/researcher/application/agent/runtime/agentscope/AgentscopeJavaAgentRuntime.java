package dev.haotangyuan.researcher.application.agent.runtime.agentscope;

import dev.haotangyuan.researcher.application.agent.runtime.AgentFramework;
import dev.haotangyuan.researcher.application.agent.runtime.AgentRuntime;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatClient;
import dev.haotangyuan.researcher.domain.entity.Model;
import dev.haotangyuan.researcher.infra.exception.ResearchException;
import dev.haotangyuan.researcher.infra.observability.ResearchObservation;
import io.agentscope.core.model.ExecutionConfig;
import io.agentscope.core.model.GenerateOptions;
import io.agentscope.core.model.OpenAIChatModel;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.time.Duration;

@Component
@ConditionalOnProperty(name = "research.agent.framework", havingValue = "agentscope-java", matchIfMissing = true)
public class AgentscopeJavaAgentRuntime implements AgentRuntime {
    private final int timeout;
    private final ResearchObservation researchObservation;

    public AgentscopeJavaAgentRuntime(
            @Value("${llm.timeout:120}") int timeout,
            ResearchObservation researchObservation) {
        this.timeout = timeout;
        this.researchObservation = researchObservation;
    }

    @Override
    public AgentFramework framework() {
        return AgentFramework.AGENTSCOPE_JAVA;
    }

    @Override
    public ResearchChatClient createChatClient(Model model) {
        if (model == null || model.getId() == null) {
            throw new ResearchException("模型不应为空");
        }
        Duration duration = Duration.ofSeconds(timeout);
        OpenAIChatModel chatModel = OpenAIChatModel.builder()
                .baseUrl(model.getBaseUrl())
                .apiKey(model.getApiKey())
                .modelName(model.getModel())
                .stream(false)
                .generateOptions(GenerateOptions.builder()
                        .maxTokens(16384)
                        .executionConfig(ExecutionConfig.builder()
                                .timeout(duration)
                                .maxAttempts(1)
                                .build())
                        .build())
                .build();
        return new AgentscopeJavaChatClient(chatModel, duration.plusSeconds(5), researchObservation);
    }
}
