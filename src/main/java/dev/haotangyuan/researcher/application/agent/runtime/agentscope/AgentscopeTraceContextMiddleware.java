package dev.haotangyuan.researcher.application.agent.runtime.agentscope;

import io.agentscope.core.agent.Agent;
import io.agentscope.core.agent.AgentBase;
import io.agentscope.core.agent.RuntimeContext;
import io.agentscope.core.event.AgentEvent;
import io.agentscope.core.middleware.ActingInput;
import io.agentscope.core.middleware.AgentInput;
import io.agentscope.core.middleware.MiddlewareBase;
import io.agentscope.core.middleware.ModelCallInput;
import io.opentelemetry.api.trace.Span;
import reactor.core.publisher.Flux;

import java.util.function.Function;

class AgentscopeTraceContextMiddleware implements MiddlewareBase {
    @Override
    public Flux<AgentEvent> onAgent(
            Agent agent,
            AgentInput input,
            Function<AgentInput, Flux<AgentEvent>> next) {
        enrichCurrentSpan(agent);
        return next.apply(input);
    }

    @Override
    public Flux<AgentEvent> onModelCall(
            Agent agent,
            ModelCallInput input,
            Function<ModelCallInput, Flux<AgentEvent>> next) {
        enrichCurrentSpan(agent);
        return next.apply(input);
    }

    @Override
    public Flux<AgentEvent> onActing(
            Agent agent,
            ActingInput input,
            Function<ActingInput, Flux<AgentEvent>> next) {
        enrichCurrentSpan(agent);
        return next.apply(input);
    }

    private static void enrichCurrentSpan(Agent agent) {
        Span span = Span.current();
        if (!span.getSpanContext().isValid()) {
            return;
        }
        if (agent != null) {
            span.setAttribute("agent.stage", nullToEmpty(agent.getName()));
        }
        RuntimeContext context = agent instanceof AgentBase agentBase ? agentBase.getRuntimeContext() : null;
        if (context == null) {
            return;
        }
        set(span, "research.id", context.get("research.id"));
        set(span, "user.id", context.getUserId());
        set(span, "model.id", context.get("model.id"));
        set(span, "budget.level", context.get("budget.level"));
        set(span, "agent.framework", context.get("agent.framework"));
    }

    private static void set(Span span, String key, Object value) {
        if (value != null) {
            span.setAttribute(key, value.toString());
        }
    }

    private static String nullToEmpty(String value) {
        return value == null ? "" : value;
    }
}
