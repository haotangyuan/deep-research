package dev.haotangyuan.researcher.application.tool;

import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolCall;

public interface ResearchToolExecutor {
    String execute(ResearchToolCall toolCall);
}
