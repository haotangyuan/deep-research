package dev.haotangyuan.researcher.application.agent.runtime;

import dev.haotangyuan.researcher.domain.entity.Model;

public interface AgentRuntime {
    AgentFramework framework();

    ResearchChatClient createChatClient(Model model);
}
