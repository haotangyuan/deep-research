package dev.haotangyuan.researcher.application.state;

import java.util.List;
import java.util.LinkedHashMap;
import java.util.Map;

import dev.haotangyuan.researcher.application.agent.runtime.ResearchMessage;
import dev.haotangyuan.researcher.application.schema.ScopeSchema;
import dev.haotangyuan.researcher.infra.client.TavilyClient;
import dev.haotangyuan.researcher.infra.config.BudgetProps;
import dev.haotangyuan.researcher.infra.observability.ResearchTraceMetadata;
import lombok.Builder;
import lombok.Data;

/**
 * State for deep research workflow
 * @author: haotangyuan
 */
@Data
@Builder
public class DeepResearchState {

    // === 基础信息 ===
    private String researchId;
    private List<ResearchMessage> chatHistory;  // 包含历史消息 + 本次消息
    private String status;
    private ResearchTraceMetadata traceMetadata;

    // === Scope 阶段产物 ===
    private ScopeSchema.ClarifyWithUserSchema clarifyWithUserSchema;
    private ScopeSchema.ResearchQuestion researchQuestion;
    private String researchBrief;

    // === Budget 配置 ===
    private BudgetProps.BudgetLevel budget;  // 持有配置对象
    
    // === Supervisor 阶段 ===
    private Integer supervisorIterations; // 当前迭代次数
    private Integer conductCount;         // 当前 conductResearch 调用次数
    private List<String> supervisorNotes;

    // === Researcher 阶段 ===
    private String researchTopic;
    private Integer researcherIterations; // 当前迭代次数
    private Integer searchCount;          // 当前 tavilySearch 调用次数
    private List<String> researcherNotes;
    private String compressedResearch;

    // === Search 阶段 ===
    private String query;
    private Integer maxResults;
    private String topic;
    private Map<String, TavilyClient.SearchResult> searchResults;
    private List<String> searchNotes;

    // === Report 阶段 ===
    private String report;

    // === 事件层级追踪 (用于 parentEventId) ===
    private Long currentScopeEventId;
    private Long currentSupervisorEventId;
    private Long currentResearchEventId;
    private Long currentSearchEventId;

    // === Token 统计 ===
    private Long totalInputTokens;
    private Long totalOutputTokens;

    public Map<String, Object> traceContext() {
        Map<String, Object> context = new LinkedHashMap<>();
        if (traceMetadata == null) {
            if (researchId != null) {
                context.put("research.id", researchId);
            }
            return context;
        }
        putIfPresent(context, "research.id", traceMetadata.researchId());
        putIfPresent(context, "user.id", traceMetadata.userId());
        putIfPresent(context, "model.id", traceMetadata.modelId());
        putIfPresent(context, "budget.level", traceMetadata.budgetLevel());
        putIfPresent(context, "agent.framework", traceMetadata.agentFramework());
        return context;
    }

    private static void putIfPresent(Map<String, Object> context, String key, Object value) {
        if (value != null) {
            context.put(key, value);
        }
    }
}
