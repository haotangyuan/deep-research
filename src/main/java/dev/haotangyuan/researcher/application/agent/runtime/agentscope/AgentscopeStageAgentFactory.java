package dev.haotangyuan.researcher.application.agent.runtime.agentscope;

import io.agentscope.core.ReActAgent;
import io.agentscope.core.model.ExecutionConfig;

class AgentscopeStageAgentFactory {
    ReActAgent create(AgentscopeStageAgentDefinition definition) {
        ExecutionConfig executionConfig = ExecutionConfig.builder()
                .timeout(definition.executionTimeout())
                .maxAttempts(1)
                .build();
        return ReActAgent.builder()
                .name(definition.name())
                .sysPrompt(definition.systemPrompt())
                .model(definition.model())
                .toolkit(definition.toolkit())
                .middlewares(definition.middlewares())
                .maxIters(definition.maxIters())
                .modelExecutionConfig(executionConfig)
                .toolExecutionConfig(executionConfig)
                .build();
    }
}
