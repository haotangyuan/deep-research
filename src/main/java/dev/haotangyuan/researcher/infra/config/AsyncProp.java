package dev.haotangyuan.researcher.infra.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * 异步任务配置属性
 *
 * @author haotangyuan
 */
@Data
@Component
@ConfigurationProperties(prefix = "research.async")
public class AsyncProp {
    /**
     * 最大并发数
     */
    private int maxPoolSize = 10;

    /**
     * 排队队列长度
     */
    private int queueCapacity = 50;

    /**
     * 预估单任务耗时
     */
    private int taskTimeoutMinutes = 3;
}
