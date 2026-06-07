package dev.haotangyuan.researcher.application.agent.runtime.agentscope;

import io.agentscope.core.middleware.MiddlewareBase;
import io.agentscope.core.model.Model;
import io.agentscope.core.tool.Toolkit;

import java.time.Duration;
import java.util.List;

record AgentscopeStageAgentDefinition(
        String name,
        String systemPrompt,
        Model model,
        Toolkit toolkit,
        List<? extends MiddlewareBase> middlewares,
        int maxIters,
        Duration executionTimeout
) {
    AgentscopeStageAgentDefinition {
        toolkit = toolkit == null ? new Toolkit() : toolkit;
        middlewares = middlewares == null ? List.of() : List.copyOf(middlewares);
        maxIters = maxIters <= 0 ? 10 : maxIters;
        executionTimeout = executionTimeout == null ? Duration.ofMinutes(15) : executionTimeout;
    }
}
