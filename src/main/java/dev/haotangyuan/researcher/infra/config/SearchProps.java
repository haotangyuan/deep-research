package dev.haotangyuan.researcher.infra.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

/**
 * Search result processing configuration.
 */
@Data
@Configuration
@ConfigurationProperties(prefix = "research.search")
public class SearchProps {
    private int maxResultsPerQuery = 3;
    private int summaryTimeoutSeconds = 60;
    private int summaryRawContentMaxChars = 12000;
    private int summaryFallbackContentMaxChars = 1200;
    private boolean summaryCacheEnabled = true;
    private long summaryCacheTtlMinutes = 60;
    private int summaryCacheMaxEntries = 1024;
}
