package dev.haotangyuan.researcher.infra.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

import java.util.Map;

/**
 * Budget 配置类
 * @author: haotangyuan
 */
@Data
@Configuration
@ConfigurationProperties(prefix = "research.budget")
public class BudgetProps {

    private Map<String, BudgetLevel> levels;

    @Data
    public static class BudgetLevel {
        // Supervisor 最大 conductResearch 调用次数
        private int maxConductCount;
        // Researcher 最大 webSearch 调用次数
        private int maxSearchCount;
        // 最大并行研究单元数
        private int maxConcurrentUnits;
    }

    public BudgetLevel getLevel(String level) {
        return levels.get(level.toUpperCase());
    }
}
