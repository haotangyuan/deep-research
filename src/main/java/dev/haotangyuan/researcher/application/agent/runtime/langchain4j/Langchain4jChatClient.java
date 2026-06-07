package dev.haotangyuan.researcher.application.agent.runtime.langchain4j;

import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatClient;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatRequest;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatResponse;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchMessage;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchTokenUsage;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolCall;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolParameter;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolSpec;
import dev.haotangyuan.researcher.application.agent.runtime.ToolChoiceMode;
import dev.langchain4j.agent.tool.ToolExecutionRequest;
import dev.langchain4j.agent.tool.ToolSpecification;
import dev.langchain4j.data.message.AiMessage;
import dev.langchain4j.data.message.SystemMessage;
import dev.langchain4j.data.message.ToolExecutionResultMessage;
import dev.langchain4j.data.message.UserMessage;
import dev.langchain4j.model.chat.ChatModel;
import dev.langchain4j.model.chat.request.ChatRequest;
import dev.langchain4j.model.chat.request.ToolChoice;
import dev.langchain4j.model.chat.request.json.JsonObjectSchema;
import dev.langchain4j.model.chat.response.ChatResponse;
import dev.langchain4j.model.output.TokenUsage;

import java.util.ArrayList;
import java.util.List;

public class Langchain4jChatClient implements ResearchChatClient {
    private final ChatModel chatModel;

    public Langchain4jChatClient(ChatModel chatModel) {
        this.chatModel = chatModel;
    }

    @Override
    public ResearchChatResponse chat(ResearchChatRequest request) {
        ChatRequest.Builder builder = ChatRequest.builder()
                .messages(toLangchainMessages(request.messages()));
        if (!request.toolSpecifications().isEmpty()) {
            builder.toolSpecifications(toLangchainToolSpecs(request.toolSpecifications()));
        }
        if (request.toolChoice() == ToolChoiceMode.REQUIRED) {
            builder.toolChoice(ToolChoice.REQUIRED);
        }
        ChatResponse response = chatModel.chat(builder.build());
        return toResearchResponse(response);
    }

    public static List<dev.langchain4j.data.message.ChatMessage> toLangchainMessages(
            List<ResearchMessage> messages
    ) {
        List<dev.langchain4j.data.message.ChatMessage> converted = new ArrayList<>();
        for (ResearchMessage message : messages) {
            if (message.role() == ResearchMessage.Role.USER) {
                converted.add(UserMessage.from(nonNullText(message.text())));
            } else if (message.role() == ResearchMessage.Role.ASSISTANT) {
                converted.add(AiMessage.from(nonNullText(message.text()), toLangchainToolCalls(message.toolCalls())));
            } else if (message.role() == ResearchMessage.Role.SYSTEM) {
                converted.add(SystemMessage.from(nonNullText(message.text())));
            } else if (message.role() == ResearchMessage.Role.TOOL) {
                converted.add(ToolExecutionResultMessage.from(
                        message.toolCallId(), message.toolName(), nonNullText(message.text())));
            }
        }
        return converted;
    }

    public static List<ToolSpecification> toLangchainToolSpecs(List<ResearchToolSpec> specs) {
        return specs.stream()
                .map(Langchain4jChatClient::toLangchainToolSpec)
                .toList();
    }

    public static ResearchChatResponse toResearchResponse(ChatResponse response) {
        AiMessage aiMessage = response.aiMessage();
        ResearchMessage message = ResearchMessage.assistant(
                nonNullText(aiMessage.text()),
                toResearchToolCalls(aiMessage.toolExecutionRequests()));
        TokenUsage usage = response.tokenUsage();
        ResearchTokenUsage tokenUsage = usage == null
                ? ResearchTokenUsage.zero()
                : new ResearchTokenUsage(
                        usage.inputTokenCount() == null ? 0L : usage.inputTokenCount(),
                        usage.outputTokenCount() == null ? 0L : usage.outputTokenCount());
        return new ResearchChatResponse(
                message,
                tokenUsage,
                response.finishReason() == null ? null : response.finishReason().name());
    }

    private static ToolSpecification toLangchainToolSpec(ResearchToolSpec spec) {
        JsonObjectSchema.Builder parameters = JsonObjectSchema.builder();
        List<String> required = new ArrayList<>();
        for (ResearchToolParameter parameter : spec.parameters()) {
            addProperty(parameters, parameter);
            if (parameter.required()) {
                required.add(parameter.name());
            }
        }
        parameters.required(required);
        return ToolSpecification.builder()
                .name(spec.name())
                .description(spec.description())
                .parameters(parameters.build())
                .build();
    }

    private static void addProperty(JsonObjectSchema.Builder parameters, ResearchToolParameter parameter) {
        Class<?> type = parameter.type();
        if (type == Integer.class || type == int.class || type == Long.class || type == long.class) {
            parameters.addIntegerProperty(parameter.name(), parameter.description());
        } else if (type == Boolean.class || type == boolean.class) {
            parameters.addBooleanProperty(parameter.name(), parameter.description());
        } else if (type == Double.class || type == double.class || type == Float.class || type == float.class) {
            parameters.addNumberProperty(parameter.name(), parameter.description());
        } else {
            parameters.addStringProperty(parameter.name(), parameter.description());
        }
    }

    private static List<ToolExecutionRequest> toLangchainToolCalls(List<ResearchToolCall> calls) {
        return calls.stream()
                .map(call -> ToolExecutionRequest.builder()
                        .id(call.id())
                        .name(call.name())
                        .arguments(call.arguments())
                        .build())
                .toList();
    }

    private static List<ResearchToolCall> toResearchToolCalls(List<ToolExecutionRequest> calls) {
        if (calls == null) {
            return List.of();
        }
        return calls.stream()
                .map(call -> new ResearchToolCall(call.id(), call.name(), call.arguments()))
                .toList();
    }

    private static String nonNullText(String text) {
        return text == null ? "" : text;
    }
}
