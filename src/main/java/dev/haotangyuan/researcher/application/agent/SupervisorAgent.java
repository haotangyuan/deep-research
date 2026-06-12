package dev.haotangyuan.researcher.application.agent;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.JsonNode;
import cn.hutool.core.date.DateUtil;
import cn.hutool.core.util.StrUtil;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchAgentRequest;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchMemory;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatResponse;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchMessage;
import dev.haotangyuan.researcher.application.data.WorkflowStatus;
import dev.haotangyuan.researcher.application.model.ModelHandler;
import dev.haotangyuan.researcher.application.state.DeepResearchState;
import dev.haotangyuan.researcher.infra.data.EventType;
import dev.haotangyuan.researcher.infra.exception.WorkflowException;
import dev.haotangyuan.researcher.infra.observability.ResearchOtelContext;
import dev.haotangyuan.researcher.infra.observability.ResearchObservation;
import dev.haotangyuan.researcher.infra.util.EventPublisher;
import dev.haotangyuan.researcher.infra.util.JsonOutputParser;
import io.opentelemetry.context.Context;
import io.opentelemetry.context.Scope;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import static dev.haotangyuan.researcher.application.prompt.SupervisorPrompts.RESEARCH_TASK_PLANNER_PROMPT;

/**
 * @author: haotangyuan
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class SupervisorAgent {
    private final ModelHandler modelHandler;
    private final ObjectMapper objectMapper;
    private final ResearcherAgent researcherAgent;
    private final EventPublisher eventPublisher;
    private final ResearchObservation researchObservation;

    public void run(DeepResearchState state) {
        state.setStatus(WorkflowStatus.IN_RESEARCH);
        Long supervisorEventId = eventPublisher.publishEvent(state.getResearchId(),
                EventType.SUPERVISOR, "开始规划研究路线...", state.getResearchBrief());
        state.setCurrentSupervisorEventId(supervisorEventId);
        AgentAbility agent = AgentAbility.builder()
                .memory(new ResearchMemory(100))
                .chatClient(modelHandler.getChatClient(state.getResearchId()))
                .build();
        List<ResearchTask> tasks = planResearchTasks(agent, state);
        List<ResearchResult> results = executeResearchTasks(tasks, state);
        summarizeSupervisorResults(results, state);
    }

    private List<ResearchTask> planResearchTasks(AgentAbility agent, DeepResearchState state) {
        ResearchMessage systemMessage = ResearchMessage.system(
                StrUtil.format(RESEARCH_TASK_PLANNER_PROMPT, Map.of(
                        "date", DateUtil.today(),
                        "max_concurrent_research_units", state.getBudget().getMaxConcurrentUnits(),
                        "max_researcher_iterations", state.getBudget().getMaxConductCount()
                )));
        List<ResearchMessage> messages = List.of(systemMessage, ResearchMessage.user(state.getResearchBrief()));
        ResearchChatResponse response = agent.getChatClient().runAgent(ResearchAgentRequest.textOnly(
                "SupervisorAgent",
                null,
                messages,
                state.traceContext()));
        state.addTokenUsage(response.tokenUsage());
        agent.getMemory().add(response.aiMessage());
        List<ResearchTask> tasks = parseResearchTasks(response.aiMessage().text(), state);
        eventPublisher.publishEvent(state.getResearchId(), EventType.SUPERVISOR,
                "已拆解研究任务", formatTaskList(tasks), state.getCurrentSupervisorEventId());
        state.getSupervisorNotes().add("## 研究任务拆解\n\n" + formatTaskList(tasks));
        return tasks;
    }

    private List<ResearchTask> parseResearchTasks(String responseText, DeepResearchState state) {
        int maxConductCount = Math.max(1, state.getBudget().getMaxConductCount());
        try {
            JsonNode root = objectMapper.readTree(JsonOutputParser.extractObject(responseText));
            JsonNode taskNodes = root.get("researchTasks");
            if (taskNodes == null || !taskNodes.isArray()) {
                return fallbackResearchTasks(state);
            }
            List<ResearchTask> tasks = new ArrayList<>();
            for (JsonNode taskNode : taskNodes) {
                if (tasks.size() >= maxConductCount) {
                    break;
                }
                String title = textValue(taskNode, "title");
                String researchTopic = textValue(taskNode, "researchTopic");
                if (researchTopic.isBlank()) {
                    continue;
                }
                if (title.isBlank()) {
                    title = "研究任务 " + (tasks.size() + 1);
                }
                tasks.add(new ResearchTask(tasks.size(), title, researchTopic));
            }
            if (tasks.isEmpty()) {
                return fallbackResearchTasks(state);
            }
            return tasks;
        } catch (Exception e) {
            log.warn("Failed to parse supervisor research tasks, fallback to single task: {}", e.getMessage());
            return fallbackResearchTasks(state);
        }
    }

    private List<ResearchTask> fallbackResearchTasks(DeepResearchState state) {
        return List.of(new ResearchTask(0, "综合研究", state.getResearchBrief()));
    }

    private List<ResearchResult> executeResearchTasks(List<ResearchTask> tasks, DeepResearchState state) {
        int parallelism = Math.max(1, Math.min(tasks.size(), state.getBudget().getMaxConcurrentUnits()));
        ExecutorService executor = Executors.newFixedThreadPool(parallelism);
        Context parentContext = ResearchOtelContext.current();
        try {
            List<CompletableFuture<ResearchResult>> futures = tasks.stream()
                    .map(task -> CompletableFuture.supplyAsync(
                            () -> withOtelContext(parentContext, () -> executeResearchTask(task, state)),
                            executor))
                    .toList();
            CompletableFuture.allOf(futures.toArray(CompletableFuture[]::new)).join();
            return futures.stream()
                    .map(CompletableFuture::join)
                    .sorted(Comparator.comparingInt(ResearchResult::index))
                    .toList();
        } catch (CompletionException e) {
            Throwable cause = e.getCause() == null ? e : e.getCause();
            if (cause instanceof WorkflowException workflowException) {
                throw workflowException;
            }
            throw new WorkflowException("Parallel research execution failed", cause);
        } finally {
            executor.shutdownNow();
        }
    }

    private ResearchResult executeResearchTask(ResearchTask task, DeepResearchState state) {
        if (!reserveConductSlot(state)) {
            log.warn("conductResearch count limit reached: {}/{}",
                    state.getConductCount(), state.getBudget().getMaxConductCount());
            return new ResearchResult(task.index(), task.title(), task.researchTopic(), "已达到研究任务配额限制", null);
        }

        Long planEventId = eventPublisher.publishEvent(state.getResearchId(), EventType.SUPERVISOR,
                "正在研究: " + task.title(), task.researchTopic(), state.getCurrentSupervisorEventId());
        DeepResearchState branchState = state.forkForResearch(task.researchTopic(), planEventId);

        String result = researchObservation.observeManualTool("conductResearch", "SupervisorAgent", state,
                () -> researcherAgent.run(branchState));
        return new ResearchResult(task.index(), task.title(), task.researchTopic(), result, branchState);
    }

    private void summarizeSupervisorResults(List<ResearchResult> results, DeepResearchState state) {
        for (ResearchResult result : results) {
            if (result.branchState() != null) {
                state.mergeTokenUsageFrom(result.branchState());
            }
            state.getSupervisorNotes().add(formatResearchResult(result));
        }
        state.setSupervisorIterations(state.getSupervisorIterations() + results.size() + 1);
        eventPublisher.publishEvent(state.getResearchId(), EventType.SUPERVISOR,
                "研究资料收集完成", "共完成 " + results.size() + " 个研究任务，准备生成最终报告",
                state.getCurrentSupervisorEventId());
    }

    private boolean reserveConductSlot(DeepResearchState state) {
        synchronized (state) {
            int current = state.getConductCount() == null ? 0 : state.getConductCount();
            if (current >= state.getBudget().getMaxConductCount()) {
                return false;
            }
            state.setConductCount(current + 1);
            return true;
        }
    }

    private ResearchResult withOtelContext(Context context, java.util.function.Supplier<ResearchResult> supplier) {
        try (Scope ignored = ResearchOtelContext.makeCurrent(context)) {
            return supplier.get();
        } finally {
            ResearchOtelContext.restore(context);
        }
    }

    private String formatTaskList(List<ResearchTask> tasks) {
        StringBuilder builder = new StringBuilder();
        for (ResearchTask task : tasks) {
            builder.append(task.index() + 1)
                    .append(". ")
                    .append(task.title())
                    .append("\n")
                    .append(task.researchTopic())
                    .append("\n\n");
        }
        return builder.toString().trim();
    }

    private String formatResearchResult(ResearchResult result) {
        return StrUtil.format("""
                ## {title}

                <research_topic>
                {topic}
                </research_topic>

                <research_findings>
                {findings}
                </research_findings>
                """, Map.of(
                "title", result.title(),
                "topic", result.researchTopic(),
                "findings", result.findings() == null ? "" : result.findings()));
    }

    private static String textValue(JsonNode node, String fieldName) {
        JsonNode value = node.get(fieldName);
        return value == null || value.isNull() ? "" : value.asText("").trim();
    }

    private record ResearchTask(int index, String title, String researchTopic) {
    }

    private record ResearchResult(
            int index,
            String title,
            String researchTopic,
            String findings,
            DeepResearchState branchState) {
    }
}
