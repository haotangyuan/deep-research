package dev.haotangyuan.researcher.application.agent.runtime.agentscope;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatClient;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatRequest;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatResponse;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchMessage;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchTokenUsage;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolCall;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolParameter;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolSpec;
import dev.haotangyuan.researcher.application.agent.runtime.ToolChoiceMode;
import io.agentscope.core.message.ContentBlock;
import io.agentscope.core.message.Msg;
import io.agentscope.core.message.MsgRole;
import io.agentscope.core.message.TextBlock;
import io.agentscope.core.message.ToolResultBlock;
import io.agentscope.core.message.ToolUseBlock;
import io.agentscope.core.model.ChatResponse;
import io.agentscope.core.model.ChatUsage;
import io.agentscope.core.model.GenerateOptions;
import io.agentscope.core.model.Model;
import io.agentscope.core.model.ToolChoice;
import io.agentscope.core.model.ToolSchema;
import lombok.extern.slf4j.Slf4j;

import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Slf4j
public class AgentscopeJavaChatClient implements ResearchChatClient {
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {
    };

    private final Model model;
    private final Duration timeout;

    public AgentscopeJavaChatClient(Model model, Duration timeout) {
        this.model = model;
        this.timeout = timeout;
    }

    @Override
    public ResearchChatResponse chat(ResearchChatRequest request) {
        ChatResponse response = model.stream(
                        toAgentscopeMessages(request.messages()),
                        toAgentscopeToolSpecs(request.toolSpecifications()),
                        toAgentscopeGenerateOptions(request.toolChoice()))
                .blockLast(timeout);
        if (response == null) {
            return new ResearchChatResponse(
                    ResearchMessage.assistant(""),
                    ResearchTokenUsage.zero(),
                    null);
        }
        return toResearchResponse(response, model.getModelName());
    }

    public static List<Msg> toAgentscopeMessages(List<ResearchMessage> messages) {
        List<Msg> converted = new ArrayList<>();
        for (ResearchMessage message : messages) {
            converted.add(toAgentscopeMessage(message));
        }
        return converted;
    }

    public static List<ToolSchema> toAgentscopeToolSpecs(List<ResearchToolSpec> specs) {
        return specs.stream()
                .map(AgentscopeJavaChatClient::toAgentscopeToolSpec)
                .toList();
    }

    public static GenerateOptions toAgentscopeGenerateOptions(ToolChoiceMode toolChoiceMode) {
        GenerateOptions.Builder builder = GenerateOptions.builder();
        if (toolChoiceMode == ToolChoiceMode.REQUIRED) {
            builder.toolChoice(new ToolChoice.Required());
        }
        return builder.build();
    }

    public static ResearchChatResponse toResearchResponse(ChatResponse response, String modelName) {
        ResearchMessage message = ResearchMessage.assistant(
                extractText(response.getContent()),
                extractToolCalls(response.getContent()));
        ChatUsage usage = response.getUsage();
        ResearchTokenUsage tokenUsage;
        if (usage == null) {
            log.warn("AgentScope Java response from model {} did not include token usage", modelName);
            tokenUsage = ResearchTokenUsage.zero();
        } else {
            tokenUsage = new ResearchTokenUsage(usage.getInputTokens(), usage.getOutputTokens());
        }
        return new ResearchChatResponse(message, tokenUsage, response.getFinishReason());
    }

    private static Msg toAgentscopeMessage(ResearchMessage message) {
        if (message.role() == ResearchMessage.Role.SYSTEM) {
            return Msg.builder()
                    .role(MsgRole.SYSTEM)
                    .textContent(nonNullText(message.text()))
                    .build();
        }
        if (message.role() == ResearchMessage.Role.USER) {
            return Msg.builder()
                    .role(MsgRole.USER)
                    .textContent(nonNullText(message.text()))
                    .build();
        }
        if (message.role() == ResearchMessage.Role.TOOL) {
            ToolResultBlock result = ToolResultBlock.of(
                    message.toolCallId(),
                    message.toolName(),
                    TextBlock.builder().text(nonNullText(message.text())).build());
            return Msg.builder()
                    .role(MsgRole.TOOL)
                    .content(result)
                    .build();
        }
        List<ContentBlock> content = new ArrayList<>();
        if (message.text() != null && !message.text().isEmpty()) {
            content.add(TextBlock.builder().text(message.text()).build());
        }
        for (ResearchToolCall toolCall : message.toolCalls()) {
            content.add(ToolUseBlock.builder()
                    .id(toolCall.id())
                    .name(toolCall.name())
                    .input(parseArguments(toolCall.arguments()))
                    .content(validJsonObjectOrNull(toolCall.arguments()))
                    .build());
        }
        return Msg.builder()
                .role(MsgRole.ASSISTANT)
                .content(content)
                .build();
    }

    private static ToolSchema toAgentscopeToolSpec(ResearchToolSpec spec) {
        return ToolSchema.builder()
                .name(spec.name())
                .description(spec.description())
                .parameters(toJsonSchema(spec.parameters()))
                .build();
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

    private static List<ResearchToolCall> extractToolCalls(List<ContentBlock> content) {
        if (content == null) {
            return List.of();
        }
        return content.stream()
                .filter(ToolUseBlock.class::isInstance)
                .map(ToolUseBlock.class::cast)
                .map(toolUse -> new ResearchToolCall(
                        toolUse.getId(),
                        toolUse.getName(),
                        argumentsToJson(toolUse)))
                .toList();
    }

    private static String argumentsToJson(ToolUseBlock toolUse) {
        if (toolUse.getContent() != null && isJsonObject(toolUse.getContent())) {
            return toolUse.getContent();
        }
        try {
            return OBJECT_MAPPER.writeValueAsString(toolUse.getInput());
        } catch (JsonProcessingException e) {
            log.warn("Failed to serialize AgentScope tool call arguments for {}", toolUse.getName(), e);
            return "{}";
        }
    }

    private static String extractText(List<ContentBlock> content) {
        if (content == null || content.isEmpty()) {
            return "";
        }
        List<String> parts = new ArrayList<>();
        for (ContentBlock block : content) {
            if (block instanceof TextBlock textBlock) {
                parts.add(textBlock.getText());
            } else if (block instanceof ToolResultBlock resultBlock) {
                String resultText = extractText(resultBlock.getOutput());
                if (!resultText.isEmpty()) {
                    parts.add(resultText);
                }
            }
        }
        return String.join("\n", parts);
    }

    private static Map<String, Object> parseArguments(String arguments) {
        if (!isJsonObject(arguments)) {
            return Map.of();
        }
        try {
            return OBJECT_MAPPER.readValue(arguments, MAP_TYPE);
        } catch (JsonProcessingException e) {
            return Map.of();
        }
    }

    private static String validJsonObjectOrNull(String arguments) {
        return isJsonObject(arguments) ? arguments : null;
    }

    private static boolean isJsonObject(String arguments) {
        if (arguments == null || arguments.isBlank()) {
            return false;
        }
        String trimmed = arguments.trim();
        if (!trimmed.startsWith("{") || !trimmed.endsWith("}")) {
            return false;
        }
        try {
            OBJECT_MAPPER.readValue(trimmed, MAP_TYPE);
            return true;
        } catch (JsonProcessingException e) {
            return false;
        }
    }

    private static String nonNullText(String text) {
        return text == null ? "" : text;
    }
}
