package dev.haotangyuan.researcher.infra.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

/**
 * Google OAuth2 配置
 * @author: haotangyuan
 */
@Data
@Configuration
@ConfigurationProperties(prefix = "google")
public class GoogleProp {
    private String clientId;
    private String clientSecret;
    private String redirectUri;
}
