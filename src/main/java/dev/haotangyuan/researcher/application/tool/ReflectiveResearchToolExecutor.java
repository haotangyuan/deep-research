package dev.haotangyuan.researcher.application.tool;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolCall;
import dev.haotangyuan.researcher.application.tool.annotation.ResearchToolParam;
import dev.haotangyuan.researcher.infra.exception.WorkflowException;

import java.lang.reflect.Method;
import java.lang.reflect.Parameter;

class ReflectiveResearchToolExecutor implements ResearchToolExecutor {
    private final Object toolBean;
    private final Method method;
    private final ObjectMapper objectMapper = new ObjectMapper();

    ReflectiveResearchToolExecutor(Object toolBean, Method method) {
        this.toolBean = toolBean;
        this.method = method;
    }

    @Override
    public String execute(ResearchToolCall toolCall) {
        try {
            Object[] args = resolveArguments(toolCall);
            Object result = method.invoke(toolBean, args);
            return result == null ? "" : result.toString();
        } catch (Exception e) {
            throw new WorkflowException("Failed to execute tool " + toolCall.name(), e);
        }
    }

    private Object[] resolveArguments(ResearchToolCall toolCall) throws Exception {
        Parameter[] parameters = method.getParameters();
        Object[] args = new Object[parameters.length];
        JsonNode root = objectMapper.readTree(
                toolCall.arguments() == null || toolCall.arguments().isBlank() ? "{}" : toolCall.arguments());
        for (int i = 0; i < parameters.length; i++) {
            ResearchToolParam metadata = parameters[i].getAnnotation(ResearchToolParam.class);
            JsonNode value = metadata == null ? null : root.get(metadata.name());
            args[i] = value == null || value.isNull()
                    ? null
                    : objectMapper.convertValue(value, parameters[i].getType());
        }
        return args;
    }
}
