package dev.haotangyuan.researcher.infra.client;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.haotangyuan.researcher.infra.config.TavilyProp;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import okhttp3.*;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Client for Tavily Search API
 * @author: haotangyuan
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class TavilyClient {
    private final TavilyProp tavilyConfig;
    private final OkHttpClient httpClient = new OkHttpClient();
    private final ObjectMapper objectMapper = new ObjectMapper();
    private final Map<SearchCacheKey, CacheEntry> searchCache = new ConcurrentHashMap<>();
    private final Map<SearchCacheKey, CompletableFuture<TavilyResponse>> inFlightSearches = new ConcurrentHashMap<>();
    private static final MediaType JSON = MediaType.parse("application/json");

    public TavilyResponse search(String query, int maxResults, String topic, boolean includeRawContent) {
        SearchCacheKey cacheKey = SearchCacheKey.of(query, maxResults, topic, includeRawContent);
        if (!tavilyConfig.isCacheEnabled()) {
            return doSearch(query, maxResults, topic, includeRawContent).response();
        }
        CacheEntry cached = searchCache.get(cacheKey);
        if (cached != null && !cached.isExpired()) {
            log.debug("Tavily search cache hit: query='{}', maxResults={}, topic='{}'",
                    query, maxResults, topic);
            return cached.response();
        }

        CompletableFuture<TavilyResponse> currentSearch = new CompletableFuture<>();
        CompletableFuture<TavilyResponse> existingSearch = inFlightSearches.putIfAbsent(cacheKey, currentSearch);
        if (existingSearch != null) {
            try {
                return existingSearch.join();
            } catch (CompletionException e) {
                log.warn("Tavily in-flight cache lookup failed for query='{}': {}", query, e.getMessage());
                return new TavilyResponse(List.of());
            }
        }

        try {
            SearchOutcome outcome = doSearch(query, maxResults, topic, includeRawContent);
            TavilyResponse response = outcome.response();
            if (outcome.cacheable()) {
                putCache(cacheKey, response);
            }
            currentSearch.complete(response);
            return response;
        } catch (RuntimeException e) {
            currentSearch.completeExceptionally(e);
            throw e;
        } finally {
            inFlightSearches.remove(cacheKey, currentSearch);
        }
    }

    private SearchOutcome doSearch(String query, int maxResults, String topic, boolean includeRawContent) {
        try {
            TavilyRequest request = new TavilyRequest(
                query, maxResults, topic, includeRawContent
            );
            
            String json = objectMapper.writeValueAsString(request);
            RequestBody body = RequestBody.create(json, JSON);
            
            Request httpRequest = new Request.Builder()
                .url(tavilyConfig.getBaseUrl() + "/search")
                .addHeader("Authorization", "Bearer " + tavilyConfig.getApiKey())
                .post(body)
                .build();
            
            log.debug("Tavily search: query='{}', maxResults={}, topic='{}'", query, maxResults, topic);
            
            try (Response response = httpClient.newCall(httpRequest).execute()) {
                if (!response.isSuccessful() || response.body() == null) {
                    log.error("Tavily API failed: code={}", response.code());
                    return SearchOutcome.notCacheable(new TavilyResponse(List.of()));
                }
                return SearchOutcome.cacheable(objectMapper.readValue(response.body().string(), TavilyResponse.class));
            }
        } catch (IOException e) {
            log.error("Tavily search failed for: {}", query, e);
            return SearchOutcome.notCacheable(new TavilyResponse(List.of()));
        }
    }

    private void putCache(SearchCacheKey cacheKey, TavilyResponse response) {
        long ttlMinutes = Math.max(1, tavilyConfig.getCacheTtlMinutes());
        long expiresAtMillis = System.currentTimeMillis() + ttlMinutes * 60_000L;
        searchCache.put(cacheKey, new CacheEntry(response, expiresAtMillis));
        pruneCache();
    }

    private void pruneCache() {
        int maxEntries = Math.max(1, tavilyConfig.getCacheMaxEntries());
        long now = System.currentTimeMillis();
        searchCache.entrySet().removeIf(entry -> entry.getValue().expiresAtMillis() <= now);
        if (searchCache.size() <= maxEntries) {
            return;
        }
        int removeCount = searchCache.size() - maxEntries;
        for (SearchCacheKey key : searchCache.keySet()) {
            if (removeCount-- <= 0) {
                break;
            }
            searchCache.remove(key);
        }
    }
    
    public record TavilyRequest(
        String query,
        @JsonProperty("max_results") int maxResults,
        String topic,
        @JsonProperty("include_raw_content") boolean includeRawContent
    ) {}
    
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record TavilyResponse(List<SearchResult> results) {}
    
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record SearchResult(
        String url,
        String title,
        String content,
        @JsonProperty("raw_content") String rawContent,
        Double score
    ) {}

    private record SearchCacheKey(
            String query,
            int maxResults,
            String topic,
            boolean includeRawContent) {

        private static SearchCacheKey of(
                String query,
                int maxResults,
                String topic,
                boolean includeRawContent) {
            return new SearchCacheKey(
                    normalize(query),
                    maxResults,
                    normalize(topic == null || topic.isBlank() ? "general" : topic),
                    includeRawContent);
        }

        private static String normalize(String value) {
            return value == null ? "" : value.trim().replaceAll("\\s+", " ").toLowerCase(Locale.ROOT);
        }
    }

    private record CacheEntry(TavilyResponse response, long expiresAtMillis) {
        private boolean isExpired() {
            return expiresAtMillis <= System.currentTimeMillis();
        }
    }

    private record SearchOutcome(TavilyResponse response, boolean cacheable) {
        private static SearchOutcome cacheable(TavilyResponse response) {
            return new SearchOutcome(response, true);
        }

        private static SearchOutcome notCacheable(TavilyResponse response) {
            return new SearchOutcome(response, false);
        }
    }
}
