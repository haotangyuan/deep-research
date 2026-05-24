package dev.haotangyuan.researcher.application.model;

import dev.haotangyuan.researcher.domain.entity.Model;
import dev.langchain4j.model.chat.ChatModel;
import dev.langchain4j.model.chat.StreamingChatModel;
import org.springframework.stereotype.Component;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * @author: haotangyuan
 */
@Component
public class ModelHandler {
    private final ModelFactory modelFactory;
    private final Map<String, ChatModel> modelPool = new ConcurrentHashMap<>();
    private final Map<String, StreamingChatModel> streamingModelPool = new ConcurrentHashMap<>();

    public ModelHandler(ModelFactory modelFactory) {
        this.modelFactory = modelFactory;
    }

    public ChatModel getModel(String researchId) {
        return modelPool.get(researchId);
    }

    public StreamingChatModel getStreamModel(String researchId) {
        return streamingModelPool.get(researchId);
    }

    public void addModel(String researchId, Model model) {
        ChatModel chatModel = modelFactory.createChatModel(model);
        StreamingChatModel streamingChatModel = modelFactory.createStreamingChatModel(model);
        modelPool.put(researchId, chatModel);
        streamingModelPool.put(researchId, streamingChatModel);
    }

    public void removeModel(String researchId) {
        modelPool.remove(researchId);
        streamingModelPool.remove(researchId);
    }
}
