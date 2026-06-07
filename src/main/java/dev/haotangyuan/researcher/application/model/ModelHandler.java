package dev.haotangyuan.researcher.application.model;

import dev.haotangyuan.researcher.application.agent.runtime.AgentRuntime;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatClient;
import dev.haotangyuan.researcher.domain.entity.Model;
import org.springframework.stereotype.Component;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * @author: haotangyuan
 */
@Component
public class ModelHandler {
    private final AgentRuntime agentRuntime;
    private final Map<String, ResearchChatClient> chatClientPool = new ConcurrentHashMap<>();

    public ModelHandler(AgentRuntime agentRuntime) {
        this.agentRuntime = agentRuntime;
    }

    public ResearchChatClient getChatClient(String researchId) {
        return chatClientPool.get(researchId);
    }

    public void addModel(String researchId, Model model) {
        chatClientPool.put(researchId, agentRuntime.createChatClient(model));
    }

    public void removeModel(String researchId) {
        chatClientPool.remove(researchId);
    }
}
