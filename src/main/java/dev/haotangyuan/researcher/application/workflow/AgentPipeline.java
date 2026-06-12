package dev.haotangyuan.researcher.application.workflow;

import dev.haotangyuan.researcher.application.agent.ScopeAgent;
import dev.haotangyuan.researcher.application.agent.SupervisorAgent;
import dev.haotangyuan.researcher.application.agent.ReportAgent;
import dev.haotangyuan.researcher.application.model.ModelHandler;
import dev.haotangyuan.researcher.infra.data.EventType;
import dev.haotangyuan.researcher.application.data.WorkflowStatus;
import dev.haotangyuan.researcher.application.state.DeepResearchState;
import dev.haotangyuan.researcher.domain.mapper.ResearchSessionMapper;
import dev.haotangyuan.researcher.infra.exception.WorkflowException;
import dev.haotangyuan.researcher.infra.observability.ResearchObservation;
import dev.haotangyuan.researcher.infra.sse.SseHub;
import dev.haotangyuan.researcher.infra.util.EventPublisher;
import dev.haotangyuan.researcher.infra.util.SequenceUtil;

import dev.haotangyuan.researcher.infra.async.QueuedAsync;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

/**
 * @author: haotangyuan
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class AgentPipeline {
    private final ScopeAgent scopeAgent;
    private final SupervisorAgent supervisorAgent;
    private final ReportAgent reportAgent;
    private final SequenceUtil sequenceUtil;
    private final SseHub sseHub;
    private final ResearchSessionMapper researchSessionMapper;
    private final EventPublisher eventPublisher;
    private final ModelHandler modelHandler;
    private final ResearchObservation researchObservation;

    @QueuedAsync
    public void run(DeepResearchState state) {
        String researchId = state.getResearchId();
        ResearchObservation.WorkflowScope workflowScope = researchObservation.startWorkflow(state);
        try {
            state.setStatus(WorkflowStatus.START);
            updateResearchSession(researchId, WorkflowStatus.START, state);

            // Phase 1: Scope - 确定研究范围和问题
            researchObservation.observeStage("ScopeAgent", state, () -> scopeAgent.run(state));

            String status = state.getStatus();
            if (WorkflowStatus.FAILED.equals(status)) {
                log.warn("Scope phase failed for researchId={}, status={} ", researchId, status);
                eventPublisher.publishEvent(researchId, EventType.ERROR, "范围分析失败", null);
                updateResearchSession(researchId, WorkflowStatus.FAILED, state);
                return;
            }
            if (WorkflowStatus.NEED_CLARIFICATION.equals(status)) {
                log.info("Scope phase requires clarification for researchId={}", researchId);
                updateResearchSession(researchId, WorkflowStatus.NEED_CLARIFICATION, state);
                return;
            }
            if (!WorkflowStatus.IN_SCOPE.equals(status)) {
                log.warn("Unexpected status after Scope phase for researchId={}, status={}", researchId, status);
                state.setStatus(WorkflowStatus.FAILED);
                eventPublisher.publishEvent(researchId, EventType.ERROR, "范围分析状态异常", "status=" + status);
                updateResearchSession(researchId, WorkflowStatus.FAILED, state);
                return;
            }
            updateResearchSession(researchId, WorkflowStatus.IN_SCOPE, state);

            // Phase 2: Supervisor - 执行研究并收集信息
            state.setStatus(WorkflowStatus.IN_RESEARCH);
            updateResearchSession(researchId, WorkflowStatus.IN_RESEARCH, state);
            researchObservation.observeStage("SupervisorAgent", state, () -> supervisorAgent.run(state));

            status = state.getStatus();
            if (WorkflowStatus.FAILED.equals(status)) {
                log.warn("Supervisor phase failed for researchId={}, status={}", researchId, status);
                eventPublisher.publishEvent(researchId, EventType.ERROR, "研究规划失败", null);
                updateResearchSession(researchId, WorkflowStatus.FAILED, state);
                return;
            }
            if (!WorkflowStatus.IN_RESEARCH.equals(status)) {
                log.warn("Unexpected status after Supervisor phase for researchId={}, status={}", researchId, status);
                state.setStatus(WorkflowStatus.FAILED);
                eventPublisher.publishEvent(researchId, EventType.ERROR, "研究规划状态异常", "status=" + status);
                updateResearchSession(researchId, WorkflowStatus.FAILED, state);
                return;
            }
            updateResearchSession(researchId, WorkflowStatus.IN_RESEARCH, state);

            // Phase 3: Report - 生成最终报告
            state.setStatus(WorkflowStatus.IN_REPORT);
            updateResearchSession(researchId, WorkflowStatus.IN_REPORT, state);
            researchObservation.observeStage("ReportAgent", state, () -> reportAgent.run(state));

            status = state.getStatus();
            if (WorkflowStatus.FAILED.equals(status)) {
                log.warn("Report phase failed for researchId={}, status={}", researchId, status);
                eventPublisher.publishEvent(researchId, EventType.ERROR, "报告生成失败", null);
                updateResearchSession(researchId, WorkflowStatus.FAILED, state);
                return;
            }
            if (!WorkflowStatus.IN_REPORT.equals(status)) {
                log.warn("Unexpected status after Report phase for researchId={}, status={}", researchId, status);
                state.setStatus(WorkflowStatus.FAILED);
                eventPublisher.publishEvent(researchId, EventType.ERROR, "报告生成状态异常", "status=" + status);
                updateResearchSession(researchId, WorkflowStatus.FAILED, state);
                return;
            }

            state.setStatus(WorkflowStatus.COMPLETED);
            updateResearchSession(researchId, WorkflowStatus.COMPLETED, state);
            log.info("Final report generated for researchId={}", researchId);
        } catch (WorkflowException e) {
            state.setStatus(WorkflowStatus.FAILED);
            eventPublisher.publishEvent(researchId, EventType.ERROR,
                    "研究过程中发生错误", null);
            updateResearchSession(researchId, WorkflowStatus.FAILED, state);
            log.error("Workflow failed for researchId={}, error={}", researchId, e.getMessage(), e);
        } catch (Exception e) {
            state.setStatus(WorkflowStatus.FAILED);
            eventPublisher.publishEvent(researchId, EventType.ERROR,
                    "系统错误，请稍后重试", null);
            updateResearchSession(researchId, WorkflowStatus.FAILED, state);
            log.error("Unexpected error for researchId={}", researchId, e);
        } finally {
            workflowScope.complete(state);
            workflowScope.close();
            try {
                sequenceUtil.reset(researchId);
                sseHub.complete(researchId, state.getStatus());
                modelHandler.removeModel(researchId);
            } catch (Exception cleanupError) {
                log.warn("Failed to clean up workflow resources for researchId={}", researchId, cleanupError);
            }
        }
    }

    private void updateResearchSession(String researchId, String status, DeepResearchState state) {
        boolean setStartTime = WorkflowStatus.START.equals(status);
        boolean setCompleteTime = WorkflowStatus.COMPLETED.equals(status)
                || WorkflowStatus.FAILED.equals(status)
                || WorkflowStatus.NEED_CLARIFICATION.equals(status);
        researchSessionMapper.updateSession(researchId, status, setStartTime, setCompleteTime,
                state.getTotalInputTokens(), state.getTotalOutputTokens());
    }
}
