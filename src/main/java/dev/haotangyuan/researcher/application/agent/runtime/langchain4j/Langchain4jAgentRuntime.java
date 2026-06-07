package dev.haotangyuan.researcher.application.agent.runtime.langchain4j;

import dev.haotangyuan.researcher.application.agent.runtime.AgentFramework;
import dev.haotangyuan.researcher.application.agent.runtime.AgentRuntime;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatClient;
import dev.haotangyuan.researcher.application.model.ModelFactory;
import dev.haotangyuan.researcher.domain.entity.Model;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(name = "research.agent.framework", havingValue = "langchain4j")
public class Langchain4jAgentRuntime implements AgentRuntime {
    private final ModelFactory modelFactory;

    public Langchain4jAgentRuntime(ModelFactory modelFactory) {
        this.modelFactory = modelFactory;
    }

    @Override
    public AgentFramework framework() {
        return AgentFramework.LANGCHAIN4J;
    }

    @Override
    public ResearchChatClient createChatClient(Model model) {
        return new Langchain4jChatClient(modelFactory.createChatModel(model));
    }
}
