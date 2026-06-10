package dev.haotangyuan.researcher.application.agent;

import cn.hutool.core.date.DateUtil;
import cn.hutool.core.util.StrUtil;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchAgentRequest;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatRequest;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchChatResponse;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchMemory;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchMessage;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchTokenUsage;
import dev.haotangyuan.researcher.infra.data.EventType;
import dev.haotangyuan.researcher.application.model.ModelHandler;
import dev.haotangyuan.researcher.infra.util.EventPublisher;
import dev.haotangyuan.researcher.infra.util.JsonOutputParser;
import dev.haotangyuan.researcher.application.schema.SummarySchema;
import dev.haotangyuan.researcher.application.state.DeepResearchState;
import dev.haotangyuan.researcher.infra.client.TavilyClient;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.HashMap;
import java.util.Map;

import static dev.haotangyuan.researcher.application.prompt.SearchPrompts.SUMMARIZE_WEBPAGE_PROMPT;

/**
 * Search Agent - performs web search and content summarization
 * @author: haotangyuan
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class SearchAgent {
    private final ModelHandler modelHandler;
    private final TavilyClient tavilyClient;
    private final ObjectMapper objectMapper;
    private final EventPublisher eventPublisher;
    
    public String run(DeepResearchState state) {
        Long searchEventId = eventPublisher.publishEvent(state.getResearchId(), EventType.SEARCH,
                "正在搜索: " + state.getQuery(), null, state.getCurrentResearchEventId());
        state.setCurrentSearchEventId(searchEventId);
        
        AgentAbility agent = AgentAbility.builder()
                .memory(new ResearchMemory(100))
                .chatClient(modelHandler.getChatClient(state.getResearchId()))
                .build();
            
        plan(state);
        action(agent, state);
        return summarize(agent, state);
    }
    
    private void plan(DeepResearchState state) {
        // execute Tavily search
        TavilyClient.TavilyResponse response = tavilyClient.search(
            state.getQuery(),
            state.getMaxResults(),
            state.getTopic(),
            true
        );
        
        if (response.results().isEmpty()) {
            log.warn("No search results for: {}", state.getQuery());
            return;
        }
        
        // 利用 URL 去重
        Map<String, TavilyClient.SearchResult> uniqueResults = new HashMap<>();
        for (TavilyClient.SearchResult result : response.results()) {
            if (result.url() != null && !uniqueResults.containsKey(result.url())) {
                uniqueResults.put(result.url(), result);
            }
        }
        
        state.setSearchResults(uniqueResults);
        eventPublisher.publishEvent(state.getResearchId(), EventType.SEARCH,
                "找到 " + uniqueResults.size() + " 个相关结果", null, state.getCurrentSearchEventId());
    }
    
    private void action(AgentAbility agent, DeepResearchState state) {
        // 空值判断
        if (state.getSearchResults().isEmpty()) {
            log.warn("No search results to process");
            return;
        }
        
        // 处理并总结结果
        for (TavilyClient.SearchResult result : state.getSearchResults().values()) {
            String content = result.rawContent() != null && !result.rawContent().isEmpty()
                ? result.rawContent()
                : result.content();
            
            if (content != null && content.length() > 500) {
                try {
                    SummarySchema summary = summarizeWebpage(agent, state, content);
                    Map<String, String> params = new HashMap<>();
                    params.put("title", result.title());
                    params.put("url", result.url());
                    params.put("summary", summary.getSummary() != null ? summary.getSummary() : "");
                    params.put("key_excerpts", summary.getKeyExcerpts() != null ? summary.getKeyExcerpts() : "");
                    String formatted = StrUtil.format(
                        "[{title}]\nURL: {url}\n<summary>{summary}</summary>\n<key_excerpts>{key_excerpts}</key_excerpts>",
                        params
                    );
                    state.getSearchNotes().add(formatted);
                } catch (Exception e) {
                    log.warn("Failed to summarize {}: {}", result.url(), e.getMessage());
                    Map<String, String> params = new HashMap<>();
                    params.put("title", result.title());
                    params.put("url", result.url());
                    params.put("content", result.content() != null ? result.content() : "");
                    state.getSearchNotes().add(StrUtil.format("[{title}]\nURL: {url}\n{content}", params));
                }
            } else {
                Map<String, String> params = new HashMap<>();
                params.put("title", result.title());
                params.put("url", result.url());
                params.put("content", content != null ? content : "");
                state.getSearchNotes().add(StrUtil.format("[{title}]\nURL: {url}\n{content}", params));
            }
        }
    }
    
    private SummarySchema summarizeWebpage(AgentAbility agent, DeepResearchState state, String webpageContent) {
        try {
            String prompt = StrUtil.format(SUMMARIZE_WEBPAGE_PROMPT, Map.of(
                "webpage_content", webpageContent,
                "date", DateUtil.today()
            ));
            
            ResearchChatResponse chatResponse = agent.getChatClient().runAgent(
                    ResearchAgentRequest.textOnly(
                            "SearchAgent",
                            "",
                            List.of(ResearchMessage.user(prompt)),
                            state.traceContext()));
            addTokenUsage(state, chatResponse.tokenUsage());
            return objectMapper.readValue(JsonOutputParser.extractObject(chatResponse.aiMessage().text()), SummarySchema.class);
            
        } catch (Exception e) {
            log.error("Webpage summarization failed", e);
            SummarySchema fallback = new SummarySchema();
            fallback.setSummary(webpageContent.substring(0, Math.min(1000, webpageContent.length())));
            fallback.setKeyExcerpts("");
            return fallback;
        }
    }
    
    private String summarize(AgentAbility agent, DeepResearchState state) {
        if (state.getSearchNotes().isEmpty()) {
            return "No search results found for: " + state.getQuery();
        }
        eventPublisher.publishEvent(state.getResearchId(), EventType.SEARCH,
                "已分析并整理搜索结果", null, state.getCurrentSearchEventId());
        
        StringBuilder output = new StringBuilder();
        output.append(StrUtil.format("Search results for query: '{query}'\n\n",
                Map.of("query", state.getQuery())));
        
        int num = 1;
        for (String result : state.getSearchNotes()) {
            output.append(StrUtil.format("\n--- SOURCE {index} ---\n",
                    Map.of("index", num++)));
            output.append(result);
            output.append("\n").append("-".repeat(80)).append("\n");
        }
        
        return output.toString();
    }

    private void addTokenUsage(DeepResearchState state, ResearchTokenUsage tokenUsage) {
        state.setTotalInputTokens(state.getTotalInputTokens() + tokenUsage.inputTokenCount());
        state.setTotalOutputTokens(state.getTotalOutputTokens() + tokenUsage.outputTokenCount());
    }
}
