package dev.haotangyuan.researcher.infra.observability;

import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatRequest;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatResponse;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchMessage;
import dev.haotangyuan.researcher.application.state.DeepResearchState;
import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.StatusCode;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.context.Context;
import io.opentelemetry.context.Scope;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.function.Supplier;

@Component
public class ResearchObservation {
    private final ResearchObservabilityProps props;

    public ResearchObservation(ResearchObservabilityProps props) {
        this.props = props;
    }

    public WorkflowScope startWorkflow(DeepResearchState state) {
        ResearchOtelContext.clear();
        ResearchTraceMetadata metadata = state == null ? null : state.getTraceMetadata();
        Span span = tracer().spanBuilder("deep_research.workflow")
                .setParent(Context.root())
                .setAttribute("research.id", value(metadata == null ? null : metadata.researchId()))
                .setAttribute("user.id", metadata == null || metadata.userId() == null ? 0L : metadata.userId())
                .setAttribute("model.id", value(metadata == null ? null : metadata.modelId()))
                .setAttribute("budget.level", value(metadata == null ? null : metadata.budgetLevel()))
                .setAttribute("agent.framework", value(metadata == null ? null : metadata.agentFramework()))
                .setAttribute("workflow.status", value(state == null ? null : state.getStatus()))
                .startSpan();
        return new WorkflowScope(span, ResearchOtelContext.makeCurrent(ResearchOtelContext.current().with(span)));
    }

    public void observeStage(String stage, DeepResearchState state, Runnable runnable) {
        observe(stage, "agent.stage", state, () -> {
            runnable.run();
            return null;
        });
    }

    public <T> T observeStage(String stage, DeepResearchState state, Supplier<T> supplier) {
        return observe(stage, "agent.stage", state, supplier);
    }

    public <T> T observeTool(String toolName, String stage, DeepResearchState state, Supplier<T> supplier) {
        if (isAgentscopeNative(state)) {
            return supplier.get();
        }
        Context parentContext = ResearchOtelContext.current();
        Span span = baseSpan("deep_research.tool " + toolName, "tool.execution", state, parentContext)
                .setAttribute("tool.name", value(toolName))
                .setAttribute("agent.stage", value(stage))
                .startSpan();
        try (Scope ignored = ResearchOtelContext.makeCurrent(parentContext.with(span))) {
            T result = supplier.get();
            span.setStatus(StatusCode.OK);
            ResearchTraceSanitizer.summarize(result == null ? "" : result.toString(), props)
                    .ifPresent(summary -> span.setAttribute("tool.result.summary", summary));
            return result;
        } catch (RuntimeException e) {
            fail(span, e);
            throw e;
        } finally {
            span.end();
            ResearchOtelContext.restore(parentContext);
        }
    }

    public ResearchChatResponse observeModelCall(
            String modelName,
            String framework,
            ResearchChatRequest request,
            Supplier<ResearchChatResponse> supplier) {
        if ("agentscope-java".equals(framework)) {
            return supplier.get();
        }
        Context parentContext = ResearchOtelContext.current();
        Span span = tracer().spanBuilder("deep_research.model " + value(modelName))
                .setParent(parentContext)
                .setAttribute("gen_ai.operation.name", "chat")
                .setAttribute("gen_ai.request.model", value(modelName))
                .setAttribute("agent.framework", value(framework))
                .setAttribute("gen_ai.request.messages.count", messageCount(request))
                .setAttribute("gen_ai.request.tools.count",
                        request == null || request.toolSpecifications() == null ? 0L : request.toolSpecifications().size())
                .startSpan();
        try (Scope ignored = ResearchOtelContext.makeCurrent(parentContext.with(span))) {
            ResearchTraceSanitizer.summarize(renderMessages(request == null ? null : request.messages()), props)
                    .ifPresent(summary -> span.setAttribute("gen_ai.request.summary", summary));
            ResearchChatResponse response = supplier.get();
            if (response != null) {
                span.setAttribute("gen_ai.response.finish_reason", value(response.finishReason()));
                if (response.tokenUsage() == null) {
                    span.setAttribute("gen_ai.usage.available", false);
                } else {
                    span.setAttribute("gen_ai.usage.available", true);
                    span.setAttribute("gen_ai.usage.input_tokens", response.tokenUsage().inputTokenCount());
                    span.setAttribute("gen_ai.usage.output_tokens", response.tokenUsage().outputTokenCount());
                    span.setAttribute("gen_ai.usage.total_tokens",
                            response.tokenUsage().inputTokenCount() + response.tokenUsage().outputTokenCount());
                }
                ResearchTraceSanitizer.summarize(response.aiMessage() == null ? "" : response.aiMessage().text(), props)
                        .ifPresent(summary -> span.setAttribute("gen_ai.response.summary", summary));
            }
            span.setStatus(StatusCode.OK);
            return response;
        } catch (RuntimeException e) {
            fail(span, e);
            throw e;
        } finally {
            span.end();
            ResearchOtelContext.restore(parentContext);
        }
    }

    private <T> T observe(String name, String operation, DeepResearchState state, Supplier<T> supplier) {
        Context parentContext = ResearchOtelContext.current();
        Span span = baseSpan("deep_research.stage " + name, operation, state, parentContext)
                .setAttribute("agent.stage", value(name))
                .startSpan();
        try (Scope ignored = ResearchOtelContext.makeCurrent(parentContext.with(span))) {
            T result = supplier.get();
            span.setAttribute("workflow.status", value(state == null ? null : state.getStatus()));
            span.setStatus(StatusCode.OK);
            return result;
        } catch (RuntimeException e) {
            fail(span, e);
            throw e;
        } finally {
            span.end();
            ResearchOtelContext.restore(parentContext);
        }
    }

    private io.opentelemetry.api.trace.SpanBuilder baseSpan(
            String spanName,
            String operation,
            DeepResearchState state,
            Context parentContext) {
        ResearchTraceMetadata metadata = state == null ? null : state.getTraceMetadata();
        return tracer().spanBuilder(spanName)
                .setParent(parentContext)
                .setAttribute("gen_ai.operation.name", operation)
                .setAttribute("research.id", value(metadata == null ? null : metadata.researchId()))
                .setAttribute("user.id", metadata == null || metadata.userId() == null ? 0L : metadata.userId())
                .setAttribute("model.id", value(metadata == null ? null : metadata.modelId()))
                .setAttribute("budget.level", value(metadata == null ? null : metadata.budgetLevel()))
                .setAttribute("agent.framework", value(metadata == null ? null : metadata.agentFramework()))
                .setAttribute("workflow.status", value(state == null ? null : state.getStatus()));
    }

    private static long messageCount(ResearchChatRequest request) {
        return request == null || request.messages() == null ? 0L : request.messages().size();
    }

    private static Tracer tracer() {
        return GlobalOpenTelemetry.getTracer("deep-research.workflow");
    }

    private static boolean isAgentscopeNative(DeepResearchState state) {
        ResearchTraceMetadata metadata = state == null ? null : state.getTraceMetadata();
        return metadata != null && "agentscope-java".equals(metadata.agentFramework());
    }

    private static String renderMessages(List<ResearchMessage> messages) {
        if (messages == null || messages.isEmpty()) {
            return "";
        }
        StringBuilder builder = new StringBuilder();
        for (ResearchMessage message : messages) {
            builder.append(message.role()).append(": ").append(value(message.text())).append('\n');
        }
        return builder.toString();
    }

    private static void fail(Span span, RuntimeException e) {
        span.setStatus(StatusCode.ERROR, e.getMessage() == null ? "" : e.getMessage());
        span.recordException(e);
    }

    private static String value(String value) {
        return value == null ? "" : value;
    }

    public final class WorkflowScope implements AutoCloseable {
        private final Span span;
        private final Scope scope;
        private boolean completed;

        private WorkflowScope(Span span, Scope scope) {
            this.span = span;
            this.scope = scope;
        }

        public void complete(DeepResearchState state) {
            if (state != null) {
                span.setAttribute("workflow.status", value(state.getStatus()));
                span.setAttribute("gen_ai.usage.input_tokens",
                        state.getTotalInputTokens() == null ? 0L : state.getTotalInputTokens());
                span.setAttribute("gen_ai.usage.output_tokens",
                        state.getTotalOutputTokens() == null ? 0L : state.getTotalOutputTokens());
            }
            span.setStatus(StatusCode.OK);
            completed = true;
        }

        @Override
        public void close() {
            if (!completed) {
                span.setStatus(StatusCode.ERROR, "workflow closed before completion");
            }
            try {
                scope.close();
            } finally {
                span.end();
                ResearchOtelContext.clear();
            }
        }
    }
}
