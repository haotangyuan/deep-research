package dev.haotangyuan.researcher.infra.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

/**
 * JWT 配置
 * @author: haotangyuan
 */
@Data
@Configuration
@ConfigurationProperties(prefix = "jwt")
public class JwtProp {
    private String secret;
    private Long expiration = 10080L; // 7 days 单位分钟
}
