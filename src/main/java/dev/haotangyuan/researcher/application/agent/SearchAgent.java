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
import dev.haotangyuan.researcher.infra.config.SearchProps;
import dev.haotangyuan.researcher.infra.util.EventPublisher;
import dev.haotangyuan.researcher.infra.util.JsonOutputParser;
import dev.haotangyuan.researcher.application.schema.SummarySchema;
import dev.haotangyuan.researcher.application.state.DeepResearchState;
import dev.haotangyuan.researcher.infra.client.TavilyClient;
import dev.haotangyuan.researcher.infra.observability.ResearchOtelContext;
import io.opentelemetry.context.Context;
import io.opentelemetry.context.Scope;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

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
    private final SearchProps searchProps;
    private final Map<SummaryCacheKey, SummaryCacheEntry> summaryCache = new ConcurrentHashMap<>();
    private final Map<SummaryCacheKey, CompletableFuture<SummarySchema>> inFlightSummaries = new ConcurrentHashMap<>();
    
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
        Map<String, TavilyClient.SearchResult> uniqueResults = new LinkedHashMap<>();
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
        if (state.getSearchResults() == null || state.getSearchResults().isEmpty()) {
            log.warn("No search results to process");
            return;
        }

        List<TavilyClient.SearchResult> results = new ArrayList<>(state.getSearchResults().values());
        int parallelism = Math.max(1, Math.min(results.size(), 4));
        ExecutorService executor = Executors.newFixedThreadPool(parallelism);
        Context parentContext = ResearchOtelContext.current();
        try {
            List<CompletableFuture<String>> futures = results.stream()
                    .map(result -> {
                        String fallback = formatContent(result, result.content());
                        return CompletableFuture.supplyAsync(
                                        () -> withOtelContext(parentContext, () -> summarizeResult(agent, state, result)),
                                        executor)
                                .completeOnTimeout(
                                        fallback,
                                        Math.max(5, searchProps.getSummaryTimeoutSeconds() + 5L),
                                        TimeUnit.SECONDS)
                                .exceptionally(e -> {
                                    log.warn("Search result processing fallback for {}: {}",
                                            result.url(), e.getMessage());
                                    return fallback;
                                });
                    })
                    .toList();
            List<String> notes = futures.stream()
                    .map(CompletableFuture::join)
                    .toList();
            state.getSearchNotes().addAll(notes);
        } finally {
            executor.shutdownNow();
        }
    }

    private String summarizeResult(AgentAbility agent, DeepResearchState state, TavilyClient.SearchResult result) {
        String content = result.rawContent() != null && !result.rawContent().isEmpty()
                ? result.rawContent()
                : result.content();

        if (content == null || content.length() <= 500) {
            return formatContent(result, content);
        }
        try {
            SummarySchema summary = summarizeWebpageWithCache(agent, state, result.url(), content);
            return formatSummary(result, summary);
        } catch (Exception e) {
            log.warn("Failed to summarize {}: {}", result.url(), e.getMessage());
            return formatContent(result, result.content());
        }
    }

    private String formatSummary(TavilyClient.SearchResult result, SummarySchema summary) {
        Map<String, String> params = Map.of(
                "title", nullToEmpty(result.title()),
                "url", nullToEmpty(result.url()),
                "summary", summary.getSummary() != null ? summary.getSummary() : "",
                "key_excerpts", summary.getKeyExcerpts() != null ? summary.getKeyExcerpts() : "");
        return StrUtil.format(
                "[{title}]\nURL: {url}\n<summary>{summary}</summary>\n<key_excerpts>{key_excerpts}</key_excerpts>",
                params);
    }

    private String formatContent(TavilyClient.SearchResult result, String content) {
        Map<String, String> params = Map.of(
                "title", nullToEmpty(result.title()),
                "url", nullToEmpty(result.url()),
                "content", content != null ? content : "");
        return StrUtil.format("[{title}]\nURL: {url}\n{content}", params);
    }

    private String withOtelContext(Context context, java.util.function.Supplier<String> supplier) {
        try (Scope ignored = ResearchOtelContext.makeCurrent(context)) {
            return supplier.get();
        } finally {
            ResearchOtelContext.restore(context);
        }
    }
    
    private SummarySchema summarizeWebpageWithCache(
            AgentAbility agent,
            DeepResearchState state,
            String url,
            String webpageContent) {
        if (!searchProps.isSummaryCacheEnabled()) {
            return summarizeWebpage(agent, state, webpageContent);
        }

        SummaryCacheKey cacheKey = SummaryCacheKey.of(url, webpageContent);
        SummaryCacheEntry cached = summaryCache.get(cacheKey);
        if (cached != null && !cached.isExpired()) {
            log.debug("Search summary cache hit: url='{}'", url);
            return cached.summary();
        }

        CompletableFuture<SummarySchema> currentSummary = new CompletableFuture<>();
        CompletableFuture<SummarySchema> existingSummary = inFlightSummaries.putIfAbsent(cacheKey, currentSummary);
        if (existingSummary != null) {
            return existingSummary.join();
        }

        try {
            SummarySchema summary = summarizeWebpage(agent, state, webpageContent);
            putSummaryCache(cacheKey, summary);
            currentSummary.complete(summary);
            return summary;
        } catch (RuntimeException e) {
            currentSummary.completeExceptionally(e);
            throw e;
        } finally {
            inFlightSummaries.remove(cacheKey, currentSummary);
        }
    }

    private SummarySchema summarizeWebpage(AgentAbility agent, DeepResearchState state, String webpageContent) {
        try {
            String boundedContent = truncate(webpageContent, Math.max(1000, searchProps.getSummaryRawContentMaxChars()));
            String prompt = StrUtil.format(SUMMARIZE_WEBPAGE_PROMPT, Map.of(
                "webpage_content", boundedContent,
                "date", DateUtil.today()
            ));

            Map<String, Object> runtimeContext = new LinkedHashMap<>(state.traceContext());
            runtimeContext.put("llm.timeout.seconds", Math.max(5, searchProps.getSummaryTimeoutSeconds()));
            
            ResearchChatResponse chatResponse = agent.getChatClient().runAgent(
                    ResearchAgentRequest.textOnly(
                            "SearchAgent",
                            "",
                            List.of(ResearchMessage.user(prompt)),
                            runtimeContext));
            addTokenUsage(state, chatResponse.tokenUsage());
            return objectMapper.readValue(JsonOutputParser.extractObject(chatResponse.aiMessage().text()), SummarySchema.class);
            
        } catch (Exception e) {
            log.error("Webpage summarization failed", e);
            SummarySchema fallback = new SummarySchema();
            fallback.setSummary(truncate(webpageContent, Math.max(300, searchProps.getSummaryFallbackContentMaxChars())));
            fallback.setKeyExcerpts("");
            return fallback;
        }
    }

    private void putSummaryCache(SummaryCacheKey cacheKey, SummarySchema summary) {
        long ttlMinutes = Math.max(1, searchProps.getSummaryCacheTtlMinutes());
        long expiresAtMillis = System.currentTimeMillis() + ttlMinutes * 60_000L;
        summaryCache.put(cacheKey, new SummaryCacheEntry(summary, expiresAtMillis));
        pruneSummaryCache();
    }

    private void pruneSummaryCache() {
        int maxEntries = Math.max(1, searchProps.getSummaryCacheMaxEntries());
        long now = System.currentTimeMillis();
        summaryCache.entrySet().removeIf(entry -> entry.getValue().expiresAtMillis() <= now);
        if (summaryCache.size() <= maxEntries) {
            return;
        }
        int removeCount = summaryCache.size() - maxEntries;
        for (SummaryCacheKey key : summaryCache.keySet()) {
            if (removeCount-- <= 0) {
                break;
            }
            summaryCache.remove(key);
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
        state.addTokenUsage(tokenUsage);
    }

    private static String nullToEmpty(String value) {
        return value == null ? "" : value;
    }

    private static String truncate(String value, int maxChars) {
        if (value == null || value.length() <= maxChars) {
            return value == null ? "" : value;
        }
        return value.substring(0, maxChars);
    }

    private record SummaryCacheKey(String url, int contentHash) {
        private static SummaryCacheKey of(String url, String content) {
            return new SummaryCacheKey(nullToEmpty(url).trim().toLowerCase(), nullToEmpty(content).hashCode());
        }
    }

    private record SummaryCacheEntry(SummarySchema summary, long expiresAtMillis) {
        private boolean isExpired() {
            return expiresAtMillis <= System.currentTimeMillis();
        }
    }
}
