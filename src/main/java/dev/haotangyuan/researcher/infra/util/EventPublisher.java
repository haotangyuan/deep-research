package dev.haotangyuan.researcher.infra.util;

import dev.haotangyuan.researcher.infra.data.TimelineItem;
import dev.haotangyuan.researcher.infra.sse.SseHub;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

/**
 * @author: haotangyuan
 */
@Component
@RequiredArgsConstructor
public class EventPublisher {

    private final CacheUtil cacheUtil;
    private final SseHub sseHub;

    /**
     * 发布消息 (用户/助手对话)
     */
    public TimelineItem publishMessage(String researchId, String role, String content) {
        TimelineItem item = cacheUtil.saveMessage(researchId, role, content);
        sseHub.sendTimelineItem(researchId, item);
        return item;
    }

    /**
     * 发布事件 (工作流事件)
     */
    public Long publishEvent(String researchId, String type, String title, String content, Long parentEventId) {
        // 截断 title 防止超过数据库字段长度 (VARCHAR 512)
        String safeTitle = title != null && title.length() > 200 ? title.substring(0, 200) + "..." : title;
        TimelineItem item = cacheUtil.saveEvent(researchId, type, safeTitle, content, parentEventId);
        sseHub.sendTimelineItem(researchId, item);
        return item.getEvent().getId();
    }

    /**
     * 发布事件 (无父事件)
     */
    public Long publishEvent(String researchId, String type, String title, String content) {
        return publishEvent(researchId, type, title, content, null);
    }

    /**
     * 发布报告流 (流式输出)
     */
    public void publishReportStream(String researchId, String partialText) {
        sseHub.sendReportStream(researchId, partialText);
    }

    /**
     * 发布临时事件（缓存 + SSE，不持久化）
     */
    public void publishTempEvent(String researchId, String type, String title) {
        TimelineItem item = cacheUtil.saveTempEvent(researchId, type, title);
        sseHub.sendTimelineItem(researchId, item);
    }
}
