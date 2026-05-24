package dev.haotangyuan.researcher.infra.async;

import cn.hutool.core.date.DateUtil;
import dev.haotangyuan.researcher.infra.config.AsyncProp;
import dev.haotangyuan.researcher.infra.data.EventType;
import dev.haotangyuan.researcher.infra.exception.ResearchException;
import dev.haotangyuan.researcher.infra.util.EventPublisher;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.stereotype.Component;

import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;

/**
 * 研究任务执行器
 *
 * @author haotangyuan
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class ResearchTaskExecutor {

    private final AsyncProp asyncProp;
    private final EventPublisher eventPublisher;
    private ThreadPoolTaskExecutor executor;

    @PostConstruct
    public void init() {
        executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(asyncProp.getMaxPoolSize());
        executor.setMaxPoolSize(asyncProp.getMaxPoolSize());
        executor.setQueueCapacity(asyncProp.getQueueCapacity());
        executor.setThreadNamePrefix("research-");
        executor.setRejectedExecutionHandler(new ThreadPoolExecutor.AbortPolicy());
        executor.initialize();
        log.info("研究任务执行器初始化完成: maxPoolSize={}, queueCapacity={}",
                asyncProp.getMaxPoolSize(), asyncProp.getQueueCapacity());
    }

    /**
     * 提交研究任务，推送预计执行时间到 SSE
     */
    public void submit(String researchId, Runnable task) {
        int queueSize = executor.getThreadPoolExecutor().getQueue().size();
        int activeCount = executor.getActiveCount();
        String estimatedTime = calculateEstimatedTime(queueSize, activeCount);

        try {
            executor.execute(task);
            log.info("任务已提交，researchId={}, estimatedTime={}", researchId, estimatedTime);
            eventPublisher.publishTempEvent(researchId, EventType.QUEUE, "排队中：预计 " + estimatedTime + " 开始执行");
        } catch (RejectedExecutionException e) {
            log.warn("任务被拒绝，researchId={}, 队列已满", researchId);
            throw new ResearchException("系统繁忙，请稍后重试");
        }
    }

    private String calculateEstimatedTime(int queueSize, int activeCount) {
        if (activeCount < asyncProp.getMaxPoolSize()) {
            return DateUtil.format(DateUtil.date(), "HH:mm");
        }
        int position = queueSize + 1;
        int batch = (position + asyncProp.getMaxPoolSize() - 1) / asyncProp.getMaxPoolSize();
        int waitMinutes = batch * asyncProp.getTaskTimeoutMinutes();
        return DateUtil.format(DateUtil.offsetMinute(DateUtil.date(), waitMinutes), "HH:mm");
    }
}
