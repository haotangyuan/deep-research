package dev.haotangyuan.researcher.application.state;

import java.util.List;
import java.util.Map;

import dev.haotangyuan.researcher.application.schema.ScopeSchema;
import dev.haotangyuan.researcher.infra.client.TavilyClient;
import dev.haotangyuan.researcher.infra.config.BudgetProps;
import dev.langchain4j.data.message.ChatMessage;
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
    private List<ChatMessage> chatHistory;  // 包含历史消息 + 本次消息
    private String status;

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
}
