package dev.haotangyuan.researcher.application.agent.runtime.agentscope;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolCall;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolParameter;
import dev.haotangyuan.researcher.infra.observability.ResearchOtelContext;
import io.agentscope.core.message.TextBlock;
import io.agentscope.core.message.ToolResultBlock;
import io.agentscope.core.tool.AgentTool;
import io.agentscope.core.tool.ToolCallParam;
import io.agentscope.core.tool.Toolkit;
import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.StatusCode;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.context.Context;
import io.opentelemetry.context.Scope;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

class AgentscopeToolkitAdapter {
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    private static final String INSTRUMENTATION_NAME = "io.agentscope";

    Toolkit toToolkit(List<AgentscopeToolBinding> bindings) {
        Toolkit toolkit = new Toolkit();
        if (bindings == null) {
            return toolkit;
        }
        for (AgentscopeToolBinding binding : bindings) {
            toolkit.registerAgentTool(new ResearchAgentTool(binding));
        }
        return toolkit;
    }

    private static class ResearchAgentTool implements AgentTool {
        private final AgentscopeToolBinding binding;

        private ResearchAgentTool(AgentscopeToolBinding binding) {
            this.binding = binding;
        }

        @Override
        public String getName() {
            return binding.spec().name();
        }

        @Override
        public String getDescription() {
            return binding.spec().description();
        }

        @Override
        public Map<String, Object> getParameters() {
            return toJsonSchema(binding.spec().parameters());
        }

        @Override
        public Mono<ToolResultBlock> callAsync(ToolCallParam param) {
            return Mono.deferContextual(view -> Mono.fromSupplier(() -> {
                Context parentContext = ResearchOtelContext.current(view);
                String id = param.getToolUseBlock() == null ? null : param.getToolUseBlock().getId();
                String arguments = toArgumentsJson(param);
                Span span = tracer().spanBuilder("execute_tool " + getName())
                        .setParent(parentContext)
                        .setAttribute("gen_ai.operation.name", "execute_tool")
                        .setAttribute("tool.name", getName())
                        .setAttribute("agent.stage", nullToEmpty(binding.stageName()))
                        .setAttribute("gen_ai.tool.call.count", 1L)
                        .setAttribute("gen_ai.tool.call.id", nullToEmpty(id))
                        .startSpan();
                setRuntimeAttributes(span, binding.runtimeContext());
                try (Scope ignored = ResearchOtelContext.makeCurrent(parentContext.with(span))) {
                    String result = binding.executor().apply(new ResearchToolCall(id, getName(), arguments));
                    span.setStatus(StatusCode.OK);
                    return ToolResultBlock.of(
                            id,
                            getName(),
                            TextBlock.builder().text(result == null ? "" : result).build());
                } catch (RuntimeException e) {
                    span.setStatus(StatusCode.ERROR, e.getMessage() == null ? "" : e.getMessage());
                    span.recordException(e);
                    throw e;
                } finally {
                    span.end();
                    ResearchOtelContext.restore(parentContext);
                }
            }).subscribeOn(Schedulers.boundedElastic()));
        }
    }

    private static Tracer tracer() {
        return GlobalOpenTelemetry.getTracer(INSTRUMENTATION_NAME);
    }

    private static void setRuntimeAttributes(Span span, Map<String, Object> runtimeContext) {
        if (runtimeContext == null) {
            return;
        }
        set(span, "research.id", runtimeContext.get("research.id"));
        set(span, "user.id", runtimeContext.get("user.id"));
        set(span, "model.id", runtimeContext.get("model.id"));
        set(span, "budget.level", runtimeContext.get("budget.level"));
        set(span, "agent.framework", runtimeContext.get("agent.framework"));
    }

    private static void set(Span span, String key, Object value) {
        if (value != null) {
            span.setAttribute(key, value.toString());
        }
    }

    private static String nullToEmpty(String value) {
        return value == null ? "" : value;
    }

    private static String toArgumentsJson(ToolCallParam param) {
        if (param.getToolUseBlock() != null && param.getToolUseBlock().getContent() != null) {
            return param.getToolUseBlock().getContent();
        }
        try {
            return OBJECT_MAPPER.writeValueAsString(param.getInput() == null ? Map.of() : param.getInput());
        } catch (JsonProcessingException e) {
            return "{}";
        }
    }

    private static Map<String, Object> toJsonSchema(List<ResearchToolParameter> parameters) {
        Map<String, Object> schema = new LinkedHashMap<>();
        Map<String, Object> properties = new LinkedHashMap<>();
        List<String> required = new ArrayList<>();
        for (ResearchToolParameter parameter : parameters) {
            properties.put(parameter.name(), toJsonSchemaProperty(parameter));
            if (parameter.required()) {
                required.add(parameter.name());
            }
        }
        schema.put("type", "object");
        schema.put("properties", properties);
        if (!required.isEmpty()) {
            schema.put("required", required);
        }
        return schema;
    }

    private static Map<String, Object> toJsonSchemaProperty(ResearchToolParameter parameter) {
        Map<String, Object> property = new LinkedHashMap<>();
        property.put("type", jsonType(parameter.type()));
        property.put("description", parameter.description());
        return property;
    }

    private static String jsonType(Class<?> type) {
        if (type == Integer.class || type == int.class || type == Long.class || type == long.class) {
            return "integer";
        }
        if (type == Boolean.class || type == boolean.class) {
            return "boolean";
        }
        if (type == Double.class || type == double.class || type == Float.class || type == float.class) {
            return "number";
        }
        return "string";
    }
}
