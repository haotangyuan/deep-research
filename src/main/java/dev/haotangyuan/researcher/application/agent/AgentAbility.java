package dev.haotangyuan.researcher.application.agent;

import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatClient;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchMemory;
import lombok.Builder;
import lombok.Data;

/**
 * @author: haotangyuan
 */
@Data
@Builder
public class AgentAbility {
    private final ResearchMemory memory;
    private final ResearchChatClient chatClient;
}
