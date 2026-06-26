package dev.haotangyuan.researcher.interfaces.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import dev.haotangyuan.researcher.application.data.WorkflowStatus;
import dev.haotangyuan.researcher.application.state.DeepResearchState;
import dev.haotangyuan.researcher.application.workflow.AgentPipeline;
import dev.haotangyuan.researcher.domain.entity.ChatMessage;
import dev.haotangyuan.researcher.domain.entity.ResearchSession;
import dev.haotangyuan.researcher.domain.entity.WorkflowEvent;
import dev.haotangyuan.researcher.domain.entity.Model;
import dev.haotangyuan.researcher.application.model.ModelHandler;
import dev.haotangyuan.researcher.domain.mapper.ChatMessageMapper;
import dev.haotangyuan.researcher.domain.mapper.ResearchSessionMapper;
import dev.haotangyuan.researcher.infra.exception.ResearchException;
import dev.haotangyuan.researcher.interfaces.dto.req.ConfirmDirectionReqDTO;
import dev.haotangyuan.researcher.interfaces.dto.req.SendMessageReqDTO;
import dev.haotangyuan.researcher.interfaces.dto.resp.CreateResearchRespDTO;
import dev.haotangyuan.researcher.interfaces.dto.resp.ResearchMessageRespDTO;
import dev.haotangyuan.researcher.interfaces.dto.resp.ResearchStatusRespDTO;
import dev.haotangyuan.researcher.interfaces.dto.resp.SendMessageRespDTO;
import dev.haotangyuan.researcher.infra.config.BudgetProps;
import dev.haotangyuan.researcher.infra.config.AgentRuntimeProps;
import dev.haotangyuan.researcher.infra.data.TimelineItem;
import dev.haotangyuan.researcher.infra.observability.ResearchTraceMetadata;
import dev.haotangyuan.researcher.infra.util.CacheUtil;
import dev.haotangyuan.researcher.infra.util.CheckpointStore;
import dev.haotangyuan.researcher.infra.util.ResearchMessageConverter;
import dev.haotangyuan.researcher.interfaces.service.ResearchService;
import dev.haotangyuan.researcher.interfaces.service.ModelService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.stream.Collectors;

/**
 * @author: haotangyuan
 */
@Service
@RequiredArgsConstructor
public class ResearchServiceImpl implements ResearchService {

    private final ResearchSessionMapper researchSessionMapper;
    private final ChatMessageMapper chatMessageMapper;
    private final AgentPipeline agentPipeline;
    private final CacheUtil cacheUtil;
    private final ModelHandler modelHandler;
    private final BudgetProps budgetConfig;
    private final ModelService modelService;
    private final AgentRuntimeProps agentRuntimeProps;
    private final CheckpointStore checkpointStore;

    @Override
    public CreateResearchRespDTO createResearch(Long userId, Integer num) {
        LambdaQueryWrapper<ResearchSession> queryWrapper = Wrappers.lambdaQuery(ResearchSession.class)
                .eq(ResearchSession::getUserId, userId)
                .eq(ResearchSession::getStatus, WorkflowStatus.NEW);
        List<ResearchSession> researchSessionList = researchSessionMapper.selectList(queryWrapper);
        int oldNum;
        if (researchSessionList == null || researchSessionList.isEmpty()) {
            oldNum = 0;
        } else {
            oldNum = researchSessionList.size();
        }
        if (num > oldNum) {
            for (int i = 0; i < num - oldNum; i++) {
                ResearchSession researchSession = ResearchSession.builder()
                        .userId(userId)
                        .status(WorkflowStatus.NEW)
                        .createTime(LocalDateTime.now())
                        .updateTime(LocalDateTime.now())
                        .build();
                researchSessionMapper.insert(researchSession);
                researchSessionList.add(researchSession);
            }
        }
        List<String> researchIds = researchSessionList.stream()
                .sorted((o1, o2) -> o1.getCreateTime().compareTo(o2.getCreateTime()))
                .map(ResearchSession::getId)
                .limit(num)
                .collect(Collectors.toList());

        // 为新创建的研究缓存权限映射
        for (String researchId : researchIds) {
            cacheUtil.cacheResearchOwnership(researchId, userId);
        }

        return CreateResearchRespDTO.builder()
                .researchIds(researchIds)
                .build();
    }

    @Override
    public List<ResearchStatusRespDTO> getResearchList(Long userId) {
        LambdaQueryWrapper<ResearchSession> queryWrapper = Wrappers.lambdaQuery(ResearchSession.class)
                .eq(ResearchSession::getUserId, userId)
                .orderByDesc(ResearchSession::getUpdateTime);
        List<ResearchSession> sessions = researchSessionMapper.selectList(queryWrapper);

        return sessions.stream().map(session -> ResearchStatusRespDTO.builder()
            .id(session.getId())
            .status(session.getStatus())
            .title(session.getTitle())
            .modelId(session.getModelId())
            .budget(session.getBudget())
            .startTime(session.getStartTime())
            .completeTime(session.getCompleteTime())
            .totalInputTokens(session.getTotalInputTokens())
            .totalOutputTokens(session.getTotalOutputTokens())
            .build()).collect(Collectors.toList());
    }

    @Override
    public ResearchStatusRespDTO getResearchStatus(Long userId, String researchId) {
        if (!cacheUtil.verifyResearchOwnership(researchId, userId)) {
            throw new ResearchException("研究任务不存在或无权限访问");
        }

        ResearchSession researchSession = researchSessionMapper.selectById(researchId);
        if (researchSession == null) {
            throw new ResearchException("研究任务不存在");
        }
        return ResearchStatusRespDTO.builder()
                .id(researchSession.getId())
                .status(researchSession.getStatus())
                .title(researchSession.getTitle())
                .modelId(researchSession.getModelId())
                .budget(researchSession.getBudget())
                .startTime(researchSession.getStartTime())
                .completeTime(researchSession.getCompleteTime())
                .totalInputTokens(researchSession.getTotalInputTokens())
                .totalOutputTokens(researchSession.getTotalOutputTokens())
                .build();
    }

    @Override
    public ResearchMessageRespDTO getResearchMessages(Long userId, String researchId) {
        if (!cacheUtil.verifyResearchOwnership(researchId, userId)) {
            throw new ResearchException("研究任务不存在或无权限访问");
        }

        ResearchSession researchSession = researchSessionMapper.selectById(researchId);
        if (researchSession == null) {
            throw new ResearchException("研究任务不存在");
        }

        // 使用缓存获取 Timeline
        List<TimelineItem> timeline = cacheUtil.getTimeline(researchId, 0);
        List<ChatMessage> messages = timeline.stream()
                .filter(t -> "message".equals(t.getKind()))
                .map(TimelineItem::getMessage)
                .toList();
        List<WorkflowEvent> events = timeline.stream()
                .filter(t -> "event".equals(t.getKind()))
                .map(TimelineItem::getEvent)
                .toList();

        return ResearchMessageRespDTO.builder()
                .id(researchSession.getId())
                .status(researchSession.getStatus())
                .messages(messages)
                .events(events)
                .startTime(researchSession.getStartTime())
                .updateTime(researchSession.getUpdateTime())
                .completeTime(researchSession.getCompleteTime())
                .totalInputTokens(researchSession.getTotalInputTokens())
                .totalOutputTokens(researchSession.getTotalOutputTokens())
                .build();
    }

    @Override
    public SendMessageRespDTO sendMessage(Long userId, String researchId, SendMessageReqDTO sendMessageReqDTO) {
        // CAS 更新状态，幂等处理
        int affected = researchSessionMapper.casUpdateToQueue(researchId, userId);
        if (affected == 0) {
            throw new ResearchException("启动研究异常");
        }
        
        ResearchSession session = researchSessionMapper.selectById(researchId);
        if (session == null) {
            throw new ResearchException("研究不存在");
        }
        if (!userId.equals(session.getUserId())) {
            throw new ResearchException("无权访问此研究");
        }
        
        String modelId = session.getModelId();
        String budget = session.getBudget();

        // 新会话
        if (modelId == null) {
            if (sendMessageReqDTO.getModelId() == null || sendMessageReqDTO.getModelId().isBlank()) {
                throw new ResearchException("模型不应为空");
            }
            modelId = sendMessageReqDTO.getModelId();
            String title = sendMessageReqDTO.getContent().length() > 20
                ? sendMessageReqDTO.getContent().substring(0, 20)
                : sendMessageReqDTO.getContent();
            budget = sendMessageReqDTO.getBudget();
            if (budget == null || budget.isBlank()) {
                budget = "HIGH";
            }
            researchSessionMapper.setInfoIfNull(researchId, modelId, budget, title);
        }

        Model model = modelService.getModelById(userId, modelId);

        // 注册模型
        modelHandler.addModel(researchId, model);
        
        BudgetProps.BudgetLevel budgetLevel = budgetConfig.getLevel(budget);

        // HITL 模式，默认 DIRECTION_ONLY
        String hitlMode = sendMessageReqDTO.getHitlMode();
        if (hitlMode == null || hitlMode.isBlank()) {
            hitlMode = "DIRECTION_ONLY";
        }

        // 保存用户消息
        cacheUtil.saveMessage(researchId, "user", sendMessageReqDTO.getContent());

        // 查询历史消息并转换为 langchain4j ChatMessage
        LambdaQueryWrapper<ChatMessage> historyQuery = Wrappers.lambdaQuery(ChatMessage.class)
                .eq(ChatMessage::getResearchId, researchId)
                .orderByAsc(ChatMessage::getSequenceNo);
        List<ChatMessage> dbMessages = chatMessageMapper.selectList(historyQuery);
        
        var chatHistory = ResearchMessageConverter.fromDbMessages(dbMessages);

        // 构建 state 并启动研究流程
        DeepResearchState state = DeepResearchState.builder()
                .researchId(researchId)
                .chatHistory(chatHistory)
                .status(WorkflowStatus.QUEUE)
                .traceMetadata(new ResearchTraceMetadata(
                        researchId,
                        userId,
                        modelId,
                        budget,
                        agentRuntimeProps.framework().propertyValue()))
                // Budget 配置
                .budget(budgetLevel)
                // Supervisor 阶段
                .supervisorIterations(0)
                .conductCount(0)
                .supervisorNotes(new ArrayList<>())
                // Researcher 阶段
                .researcherIterations(0)
                .searchCount(0)
                .researcherNotes(new ArrayList<>())
                // Search 阶段
                .searchResults(new HashMap<>())
                .searchNotes(new ArrayList<>())
                // Token 统计
                .totalInputTokens(0L)
                .totalOutputTokens(0L)
                // HITL 配置
                .hitlMode(hitlMode)
                .skipScopePhase(false)
                .build();
        agentPipeline.run(state);

        return SendMessageRespDTO.builder()
                .id(researchId)
                .content("已接受任务")
                .build();
    }

    @Override
    public SendMessageRespDTO confirmDirection(Long userId, String researchId,
                                                ConfirmDirectionReqDTO reqDTO) {
        // CAS 更新状态，保证幂等
        int affected = researchSessionMapper.casConfirmDirection(researchId, userId);
        if (affected == 0) {
            throw new ResearchException("确认操作失败，当前状态不允许确认");
        }

        // 从 Redis 恢复 DeepResearchState
        DeepResearchState savedState = checkpointStore.load(researchId);
        if (savedState == null) {
            throw new ResearchException("会话已过期，请重新发起研究");
        }

        ResearchSession session = researchSessionMapper.selectById(researchId);

        // 重新注册模型（finally 块中已移除）
        Model model = modelService.getModelById(userId, session.getModelId());
        modelHandler.addModel(researchId, model);

        String action = reqDTO.getAction();
        if ("APPROVE".equals(action)) {
            // 用户确认方向，跳过 ScopeAgent 直接进入 Supervisor
            cacheUtil.saveMessage(researchId, "user", "确认研究方向，开始执行研究");
            savedState.setSkipScopePhase(true);
            savedState.setStatus(WorkflowStatus.QUEUE);
        } else {
            // REVISE：用户修改方向，带上反馈重新执行 ScopeAgent
            String feedback = reqDTO.getFeedback();
            String msg = feedback != null && !feedback.isBlank()
                    ? "修改意见: " + feedback : "请重新调整研究方向";
            cacheUtil.saveMessage(researchId, "user", msg);
            savedState.setSkipScopePhase(false);
            savedState.setHitlFeedback(feedback);
            savedState.setStatus(WorkflowStatus.QUEUE);
            savedState.setResearchBrief(null); // 清空旧的，让 ScopeAgent 重新生成
        }

        // 恢复 pipeline 执行
        agentPipeline.run(savedState);

        return SendMessageRespDTO.builder()
                .id(researchId)
                .content("APPROVE".equals(action) ? "研究方向已确认，开始执行研究"
                        : "已收到修改意见，重新分析研究方向")
                .build();
    }

    @Override
    public SendMessageRespDTO cancelResearch(Long userId, String researchId) {
        int affected = researchSessionMapper.cancelResearch(researchId, userId);
        if (affected == 0) {
            throw new ResearchException("取消失败，研究已完成或不存在");
        }
        cacheUtil.saveMessage(researchId, "user", "用户取消了本次研究");
        cacheUtil.saveMessage(researchId, "assistant", "研究已取消");
        return SendMessageRespDTO.builder()
                .id(researchId)
                .content("研究已取消")
                .build();
    }
}
