package dev.haotangyuan.researcher.application.agent.runtime.agentscope;

import dev.haotangyuan.researcher.infra.observability.ResearchOtelContext;
import io.agentscope.core.agent.Agent;
import io.agentscope.core.event.AgentEvent;
import io.agentscope.core.event.AgentStartEvent;
import io.agentscope.core.event.ModelCallEndEvent;
import io.agentscope.core.middleware.ActingInput;
import io.agentscope.core.middleware.AgentInput;
import io.agentscope.core.middleware.MiddlewareBase;
import io.agentscope.core.middleware.ModelCallInput;
import io.agentscope.core.model.Model;
import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanBuilder;
import io.opentelemetry.api.trace.StatusCode;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.context.Context;
import io.opentelemetry.context.Scope;
import reactor.core.publisher.Flux;

import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Function;

/**
 * 修复版 OtelTracingMiddleware，解决 Reactor 异步边界上子 span 丢失父 span 关联的问题。
 *
 * <p>AgentScope v2 原生 middleware 产生的 span 名称保持不变：
 * {@code invoke_agent <name>}、{@code chat <model>}、{@code execute_tool <name>}。
 * 本实现只修正上下文生命周期：每个 span 使用当前 OTel context 作为显式 parent，
 * 并把新 context 写入 Reactor context，供后续模型/工具/子 agent span 继续继承。
 */
public class FixedOtelTracingMiddleware implements MiddlewareBase {

    private static final String INSTRUMENTATION_NAME = "io.agentscope";

    private Tracer getTracer() {
        return GlobalOpenTelemetry.getTracer(INSTRUMENTATION_NAME);
    }

    @Override
    public Flux<AgentEvent> onAgent(
            Agent agent, AgentInput input, Function<AgentInput, Flux<AgentEvent>> next) {
        return Flux.deferContextual(
                view -> withSpan(
                        getTracer().spanBuilder("invoke_agent " + agent.getName())
                                .setAttribute("gen_ai.operation.name", "invoke_agent")
                                .setAttribute("gen_ai.agent.name", agent.getName())
                                .setAttribute(
                                        "gen_ai.agent.id",
                                        agent.getAgentId() != null ? agent.getAgentId() : "")
                                .setAttribute(
                                        "gen_ai.request.messages.count",
                                        (long) input.msgs().size()),
                        ResearchOtelContext.current(view),
                        span -> {
                    AtomicReference<String> replyIdRef = new AtomicReference<>();
                    return next.apply(input)
                            .doOnNext(
                                    event -> {
                                        if (event instanceof AgentStartEvent rse) {
                                            replyIdRef.set(rse.getReplyId());
                                        }
                                    })
                            .doFinally(
                                    signal -> {
                                        setReplyIdIfPresent(span, replyIdRef.get());
                                        if (!signal.name().equals("ON_ERROR")) {
                                            span.setStatus(StatusCode.OK);
                                        }
                                    });
                        }));
    }

    @Override
    public Flux<AgentEvent> onModelCall(
            Agent agent, ModelCallInput input, Function<ModelCallInput, Flux<AgentEvent>> next) {
        return Flux.deferContextual(
                view -> {
                    Model model = input.model();
                    String modelName = model != null ? model.getModelName() : "unknown";
                    return withSpan(
                            getTracer().spanBuilder("chat " + modelName)
                                    .setAttribute("gen_ai.operation.name", "chat")
                                    .setAttribute("gen_ai.request.model", modelName)
                                    .setAttribute(
                                            "gen_ai.request.messages.count",
                                            (long) input.messages().size())
                                    .setAttribute(
                                            "gen_ai.request.tools.count",
                                            input.tools() != null
                                                    ? (long) input.tools().size()
                                                    : 0L),
                            ResearchOtelContext.current(view),
                            span -> next.apply(input)
                                    .doOnNext(
                                            event -> {
                                                if (event instanceof ModelCallEndEvent mce) {
                                                    setModelResponseAttributes(span, mce);
                                                }
                                            })
                                    .doFinally(signal -> {
                                        if (!signal.name().equals("ON_ERROR")) {
                                            span.setStatus(StatusCode.OK);
                                        }
                                    }));
                });
    }

    @Override
    public Flux<AgentEvent> onActing(
            Agent agent, ActingInput input, Function<ActingInput, Flux<AgentEvent>> next) {
        return next.apply(input);
    }

    private Flux<AgentEvent> withSpan(
            SpanBuilder builder,
            Context parentContext,
            Function<Span, Flux<AgentEvent>> next) {
        Context parent = parentContext == null ? Context.current() : parentContext;
        Span span = builder.setParent(parent).startSpan();
        Context spanContext = parent.with(span);
        Scope scope = ResearchOtelContext.makeCurrent(spanContext);
        return next.apply(span)
                .contextWrite(context -> context.put(
                        ResearchOtelContext.REACTOR_CONTEXT_KEY, spanContext))
                .doOnError(e -> {
                    span.setStatus(StatusCode.ERROR, e.getMessage() == null ? "" : e.getMessage());
                    span.recordException(e);
                })
                .doFinally(signal -> {
                    try {
                        scope.close();
                    } finally {
                        span.end();
                        ResearchOtelContext.restore(parent);
                    }
                });
    }

    private static void setReplyIdIfPresent(Span span, String replyId) {
        if (replyId != null) {
            span.setAttribute("agentscope.agent.reply_id", replyId);
        }
    }

    private static void setModelResponseAttributes(Span span, ModelCallEndEvent event) {
        if (event.getUsage() != null) {
            var usage = event.getUsage();
            span.setAttribute("gen_ai.usage.input_tokens", (long) usage.getInputTokens());
            span.setAttribute("gen_ai.usage.output_tokens", (long) usage.getOutputTokens());
        }
    }
}
