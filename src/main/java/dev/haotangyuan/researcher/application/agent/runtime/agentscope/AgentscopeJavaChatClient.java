package dev.haotangyuan.researcher.application.agent.runtime.agentscope;

import dev.haotangyuan.researcher.application.agent.runtime.ResearchAgentRequest;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatClient;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatRequest;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatResponse;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchMessage;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchTokenUsage;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolParameter;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolSpec;
import dev.haotangyuan.researcher.application.agent.runtime.ToolChoiceMode;
import dev.haotangyuan.researcher.infra.observability.ResearchOtelContext;
import dev.haotangyuan.researcher.infra.observability.ResearchObservation;
import io.agentscope.core.ReActAgent;
import io.agentscope.core.agent.RuntimeContext;
import io.agentscope.core.message.Msg;
import io.agentscope.core.model.ChatResponse;
import io.agentscope.core.model.ChatUsage;
import io.agentscope.core.model.GenerateOptions;
import io.agentscope.core.model.Model;
import io.agentscope.core.model.ToolChoice;
import io.agentscope.core.model.ToolSchema;
import io.agentscope.core.tool.Toolkit;
import io.opentelemetry.context.Context;
import io.opentelemetry.context.Scope;
import lombok.extern.slf4j.Slf4j;
import reactor.core.publisher.Flux;

import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Slf4j
public class AgentscopeJavaChatClient implements ResearchChatClient {
    private final Model model;
    private final Duration timeout;
    private final ResearchObservation researchObservation;
    private final AgentscopeStageAgentFactory agentFactory;
    private final AgentscopeToolkitAdapter toolkitAdapter;

    public AgentscopeJavaChatClient(Model model, Duration timeout, ResearchObservation researchObservation) {
        this.model = model;
        this.timeout = timeout;
        this.researchObservation = researchObservation;
        this.agentFactory = new AgentscopeStageAgentFactory();
        this.toolkitAdapter = new AgentscopeToolkitAdapter();
    }

    @Override
    public ResearchChatResponse chat(ResearchChatRequest request) {
        return researchObservation.observeModelCall(
                model.getModelName(),
                "agentscope-java",
                request,
                () -> doChat(request));
    }

    @Override
    public ResearchChatResponse runAgent(ResearchAgentRequest request) {
        Context callerContext = ResearchOtelContext.current();
        UsageCollectingModel usageCollectingModel = new UsageCollectingModel(model);
        Toolkit toolkit = toolkitAdapter.toToolkit(request.toolSpecifications().stream()
                .map(spec -> new AgentscopeToolBinding(
                        spec,
                        request.toolExecutor(),
                        request.stageName(),
                        request.runtimeContext()))
                .toList());
        List<ResearchMessage> inputMessages = nonSystemMessages(request.messages());
        ReActAgent agent = agentFactory.create(new AgentscopeStageAgentDefinition(
                request.stageName(),
                mergedSystemPrompt(request),
                usageCollectingModel,
                toolkit,
                List.of(new FixedOtelTracingMiddleware(), new AgentscopeTraceContextMiddleware()),
                request.maxIterations(),
                agentTimeout(request)));
        try {
            try (Scope ignored = ResearchOtelContext.makeCurrent(callerContext)) {
                agent.streamEvents(
                                AgentscopeMessageConverter.toAgentscopeMessages(inputMessages),
                                toRuntimeContext(request))
                        .collectList()
                        .block(agentTimeout(request));
            }
        } finally {
            ResearchOtelContext.restore(callerContext);
        }
        Msg reply = lastAssistantMessage(agent);
        if (reply == null) {
            return new ResearchChatResponse(ResearchMessage.assistant(""), ResearchTokenUsage.zero(), null);
        }
        return new ResearchChatResponse(
                AgentscopeMessageConverter.toResearchMessage(reply),
                usageCollectingModel.usage(),
                null);
    }

    private static Msg lastAssistantMessage(ReActAgent agent) {
        List<Msg> context = agent.getAgentState().getContext();
        for (int i = context.size() - 1; i >= 0; i--) {
            Msg msg = context.get(i);
            if (msg.getRole() == io.agentscope.core.message.MsgRole.ASSISTANT) {
                return msg;
            }
        }
        return null;
    }

    private ResearchChatResponse doChat(ResearchChatRequest request) {
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

    private static RuntimeContext toRuntimeContext(ResearchAgentRequest request) {
        RuntimeContext context = RuntimeContext.builder()
                .sessionId(stringContext(request, "research.id"))
                .userId(stringContext(request, "user.id"))
                .build();
        request.runtimeContext().forEach(context::put);
        return context;
    }

    private static String mergedSystemPrompt(ResearchAgentRequest request) {
        List<String> prompts = new ArrayList<>();
        if (request.systemPrompt() != null && !request.systemPrompt().isBlank()) {
            prompts.add(request.systemPrompt());
        }
        request.messages().stream()
                .filter(message -> message.role() == ResearchMessage.Role.SYSTEM)
                .map(ResearchMessage::text)
                .filter(text -> text != null && !text.isBlank())
                .forEach(prompts::add);
        return String.join("\n\n", prompts);
    }

    private static List<ResearchMessage> nonSystemMessages(List<ResearchMessage> messages) {
        return messages.stream()
                .filter(message -> message.role() != ResearchMessage.Role.SYSTEM)
                .toList();
    }

    private static String stringContext(ResearchAgentRequest request, String key) {
        Object value = request.runtimeContext().get(key);
        return value == null ? null : value.toString();
    }

    static Duration agentTimeout(Duration modelTimeout, int maxIterations) {
        return modelTimeout.multipliedBy(Math.max(1, maxIterations));
    }

    private Duration agentTimeout(ResearchAgentRequest request) {
        Object requestTimeoutSeconds = request.runtimeContext().get("llm.timeout.seconds");
        if (requestTimeoutSeconds != null) {
            try {
                long seconds = Long.parseLong(requestTimeoutSeconds.toString());
                if (seconds > 0) {
                    return Duration.ofSeconds(seconds);
                }
            } catch (NumberFormatException e) {
                log.warn("Invalid llm.timeout.seconds value: {}", requestTimeoutSeconds);
            }
        }
        return agentTimeout(timeout, request.maxIterations());
    }

    public static List<Msg> toAgentscopeMessages(List<ResearchMessage> messages) {
        return AgentscopeMessageConverter.toAgentscopeMessages(messages);
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
                AgentscopeMessageConverter.extractText(response.getContent()),
                AgentscopeMessageConverter.extractToolCalls(response.getContent()));
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

    private static class UsageCollectingModel implements Model {
        private final Model delegate;
        private int inputTokens;
        private int outputTokens;

        private UsageCollectingModel(Model delegate) {
            this.delegate = delegate;
        }

        @Override
        public Flux<ChatResponse> stream(List<Msg> messages, List<ToolSchema> toolSchemas, GenerateOptions options) {
            return delegate.stream(messages, toolSchemas, options)
                    .doOnNext(response -> {
                        ChatUsage usage = response.getUsage();
                        if (usage != null) {
                            inputTokens += usage.getInputTokens();
                            outputTokens += usage.getOutputTokens();
                        }
                    });
        }

        @Override
        public String getModelName() {
            return delegate.getModelName();
        }

        private ResearchTokenUsage usage() {
            return new ResearchTokenUsage(inputTokens, outputTokens);
        }
    }

}
