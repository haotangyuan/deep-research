package dev.haotangyuan.researcher.application.agent.runtime.agentscope;

import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolSpec;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolCall;

import java.util.Map;
import java.util.function.Function;

record AgentscopeToolBinding(
        ResearchToolSpec spec,
        Function<ResearchToolCall, String> executor,
        String stageName,
        Map<String, Object> runtimeContext
) {
}
