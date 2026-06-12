package dev.haotangyuan.researcher.infra.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

/**
 * Configuration properties for Tavily API
 * @author: haotangyuan
 */
@Configuration
@ConfigurationProperties(prefix = "tavily")
@Data
public class TavilyProp {
    private String apiKey;
    private String baseUrl;
    private boolean cacheEnabled = true;
    private long cacheTtlMinutes = 60;
    private int cacheMaxEntries = 512;
}
