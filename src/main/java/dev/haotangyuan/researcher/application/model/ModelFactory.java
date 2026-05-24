package dev.haotangyuan.researcher.application.model;

import dev.haotangyuan.researcher.domain.entity.Model;
import dev.haotangyuan.researcher.infra.exception.ResearchException;
import dev.langchain4j.model.chat.ChatModel;
import dev.langchain4j.model.chat.StreamingChatModel;
import dev.langchain4j.model.openai.OpenAiChatModel;
import dev.langchain4j.model.openai.OpenAiStreamingChatModel;
import lombok.Data;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * @author: haotangyuan
 */
@Component
@Data
@Slf4j
public class ModelFactory {

    private static final String GLOBAL_MODEL_TYPE = "GLOBAL";

    private final Map<String, ChatModel> chatModelCache = new ConcurrentHashMap<>();
    private final Map<String, StreamingChatModel> streamingChatModelCache = new ConcurrentHashMap<>();

    @Value("${llm.log.requests:false}")
    private boolean logRequestsEnabled;

    @Value("${llm.log.responses:false}")
    private boolean logResponsesEnabled;

    @Value("${llm.timeout:120}")
    private int timeout;

    public ChatModel createChatModel(Model model) {
        if (model == null || model.getId() == null) {
            throw new ResearchException("模型不应为空");
        }
        if (isGlobalModel(model)) {
            return chatModelCache.computeIfAbsent(model.getId(), key -> {
                log.info("初始化模型 {} ({})", model.getName(), model.getId());
                return buildChatModel(model);
            });
        }
        log.info("初始化自定义模型 {} ({})", model.getName(), model.getId());
        return buildChatModel(model);
    }

    public StreamingChatModel createStreamingChatModel(Model model) {
        if (model == null || model.getId() == null) {
            throw new ResearchException("模型不应为空");
        }
        if (isGlobalModel(model)) {
            return streamingChatModelCache.computeIfAbsent(model.getId(), key -> {
                log.info("初始化流式模型 {} ({})", model.getName(), model.getId());
                return buildStreamingChatModel(model);
            });
        }
        log.info("初始化自定义流式模型 {} ({})", model.getName(), model.getId());
        return buildStreamingChatModel(model);
    }
    
    private boolean isGlobalModel(Model model) {
        return model != null && GLOBAL_MODEL_TYPE.equalsIgnoreCase(model.getType());
    }

    private ChatModel buildChatModel(Model model) {
        return OpenAiChatModel.builder()
                .baseUrl(model.getBaseUrl())
                .apiKey(model.getApiKey())
                .modelName(model.getModel())
                .timeout(Duration.ofSeconds(timeout))
                .logRequests(logRequestsEnabled)
                .logResponses(logResponsesEnabled)
                .build();
    }

    private StreamingChatModel buildStreamingChatModel(Model model) {
        return OpenAiStreamingChatModel.builder()
                .baseUrl(model.getBaseUrl())
                .apiKey(model.getApiKey())
                .modelName(model.getModel())
                .timeout(Duration.ofSeconds(timeout))
                .logRequests(logRequestsEnabled)
                .logResponses(logResponsesEnabled)
                .build();
    }
}
