package dev.haotangyuan.researcher.application.agent.runtime.agentscope;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchMessage;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolCall;
import io.agentscope.core.message.ContentBlock;
import io.agentscope.core.message.Msg;
import io.agentscope.core.message.MsgRole;
import io.agentscope.core.message.TextBlock;
import io.agentscope.core.message.ToolResultBlock;
import io.agentscope.core.message.ToolUseBlock;
import lombok.extern.slf4j.Slf4j;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

@Slf4j
class AgentscopeMessageConverter {
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {
    };

    private AgentscopeMessageConverter() {
    }

    static List<Msg> toAgentscopeMessages(List<ResearchMessage> messages) {
        List<Msg> converted = new ArrayList<>();
        for (ResearchMessage message : messages) {
            converted.add(toAgentscopeMessage(message));
        }
        return converted;
    }

    static ResearchMessage toResearchMessage(Msg message) {
        return ResearchMessage.assistant(
                extractText(message.getContent()),
                extractToolCalls(message.getContent()));
    }

    static String extractText(List<ContentBlock> content) {
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

    static List<ResearchToolCall> extractToolCalls(List<ContentBlock> content) {
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
