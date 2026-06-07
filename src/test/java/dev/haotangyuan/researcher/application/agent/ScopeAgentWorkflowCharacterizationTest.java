package dev.haotangyuan.researcher.application.agent;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.haotangyuan.researcher.application.data.WorkflowStatus;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchMessage;
import dev.haotangyuan.researcher.application.agent.runtime.AgentFramework;
import dev.haotangyuan.researcher.application.agent.runtime.AgentRuntime;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatClient;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatRequest;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatResponse;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchTokenUsage;
import dev.haotangyuan.researcher.application.model.ModelHandler;
import dev.haotangyuan.researcher.application.state.DeepResearchState;
import dev.haotangyuan.researcher.domain.entity.Model;
import dev.haotangyuan.researcher.infra.data.TimelineItem;
import dev.haotangyuan.researcher.infra.util.EventPublisher;
import org.junit.jupiter.api.Test;

import java.util.ArrayDeque;
import java.util.List;
import java.util.Queue;

import static org.assertj.core.api.Assertions.assertThat;

class ScopeAgentWorkflowCharacterizationTest {

    @Test
    void stopsForClarificationAndPublishesAssistantQuestion() {
        ModelHandler modelHandler = modelHandlerWithResponses(
                response("{\"needClarification\":true,\"question\":\"Which market?\",\"verification\":null}", 11, 5)
        );
        RecordingEventPublisher eventPublisher = new RecordingEventPublisher();
        ScopeAgent scopeAgent = new ScopeAgent(modelHandler, new ObjectMapper(), eventPublisher);
        DeepResearchState state = stateWithUserMessage("research-1", "Analyze AI");

        scopeAgent.run(state);

        assertThat(state.getStatus()).isEqualTo(WorkflowStatus.NEED_CLARIFICATION);
        assertThat(state.getClarifyWithUserSchema().needClarification()).isTrue();
        assertThat(state.getClarifyWithUserSchema().question()).isEqualTo("Which market?");
        assertThat(state.getResearchBrief()).isNull();
        assertThat(state.getTotalInputTokens()).isEqualTo(11L);
        assertThat(state.getTotalOutputTokens()).isEqualTo(5L);
        assertThat(eventPublisher.messages).contains("research-1|assistant|Which market?");
    }

    @Test
    void writesResearchBriefWhenClarificationIsNotNeeded() {
        ModelHandler modelHandler = modelHandlerWithResponses(
                response("{\"needClarification\":false,\"question\":null,\"verification\":\"Ready to research\"}", 7, 3),
                response("{\"researchBrief\":\"Research AI adoption in healthcare\"}", 13, 8)
        );
        RecordingEventPublisher eventPublisher = new RecordingEventPublisher();
        ScopeAgent scopeAgent = new ScopeAgent(modelHandler, new ObjectMapper(), eventPublisher);
        DeepResearchState state = stateWithUserMessage("research-2", "Analyze AI adoption");

        scopeAgent.run(state);

        assertThat(state.getStatus()).isEqualTo(WorkflowStatus.IN_SCOPE);
        assertThat(state.getClarifyWithUserSchema().needClarification()).isFalse();
        assertThat(state.getResearchBrief()).isEqualTo("Research AI adoption in healthcare");
        assertThat(state.getResearchQuestion().researchBrief()).isEqualTo("Research AI adoption in healthcare");
        assertThat(state.getTotalInputTokens()).isEqualTo(20L);
        assertThat(state.getTotalOutputTokens()).isEqualTo(11L);
    }

    @Test
    void failsWhenClarificationJsonCannotBeParsed() {
        ModelHandler modelHandler = modelHandlerWithResponses(
                response("not-json", 5, 2)
        );
        RecordingEventPublisher eventPublisher = new RecordingEventPublisher();
        ScopeAgent scopeAgent = new ScopeAgent(modelHandler, new ObjectMapper(), eventPublisher);
        DeepResearchState state = stateWithUserMessage("research-3", "Analyze AI");

        scopeAgent.run(state);

        assertThat(state.getStatus()).isEqualTo(WorkflowStatus.FAILED);
        assertThat(state.getResearchBrief()).isNull();
        assertThat(state.getTotalInputTokens()).isEqualTo(5L);
        assertThat(state.getTotalOutputTokens()).isEqualTo(2L);
    }

    private static DeepResearchState stateWithUserMessage(String researchId, String content) {
        return DeepResearchState.builder()
                .researchId(researchId)
                .chatHistory(List.of(ResearchMessage.user(content)))
                .totalInputTokens(0L)
                .totalOutputTokens(0L)
                .build();
    }

    private static ModelHandler modelHandlerWithResponses(ResearchChatResponse... responses) {
        return new FakeModelHandler(new FakeChatClient(responses));
    }

    private static ResearchChatResponse response(String text, int inputTokens, int outputTokens) {
        return new ResearchChatResponse(
                ResearchMessage.assistant(text),
                new ResearchTokenUsage(inputTokens, outputTokens),
                null);
    }

    private static final class FakeChatClient implements ResearchChatClient {
        private final Queue<ResearchChatResponse> responses;

        private FakeChatClient(ResearchChatResponse... responses) {
            this.responses = new ArrayDeque<>(List.of(responses));
        }

        @Override
        public ResearchChatResponse chat(ResearchChatRequest request) {
            return responses.remove();
        }
    }

    private static final class FakeModelHandler extends ModelHandler {
        private final ResearchChatClient chatClient;

        private FakeModelHandler(ResearchChatClient chatClient) {
            super(new FakeRuntime(chatClient));
            this.chatClient = chatClient;
        }

        @Override
        public ResearchChatClient getChatClient(String researchId) {
            return chatClient;
        }
    }

    private static final class FakeRuntime implements AgentRuntime {
        private final ResearchChatClient chatClient;

        private FakeRuntime(ResearchChatClient chatClient) {
            this.chatClient = chatClient;
        }

        @Override
        public AgentFramework framework() {
            return AgentFramework.LANGCHAIN4J;
        }

        @Override
        public ResearchChatClient createChatClient(Model model) {
            return chatClient;
        }
    }

    private static final class RecordingEventPublisher extends EventPublisher {
        private final List<String> messages = new java.util.ArrayList<>();
        private long nextEventId = 1L;

        private RecordingEventPublisher() {
            super(null, null);
        }

        @Override
        public Long publishEvent(String researchId, String type, String title, String content, Long parentEventId) {
            return nextEventId++;
        }

        @Override
        public Long publishEvent(String researchId, String type, String title, String content) {
            return publishEvent(researchId, type, title, content, null);
        }

        @Override
        public TimelineItem publishMessage(String researchId, String role, String content) {
            messages.add(researchId + "|" + role + "|" + content);
            return null;
        }
    }
}
