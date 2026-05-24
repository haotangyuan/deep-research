package dev.haotangyuan.researcher.infra.sse;

import cn.hutool.core.collection.CollectionUtil;
import cn.hutool.core.util.NumberUtil;
import cn.hutool.core.util.StrUtil;
import dev.haotangyuan.researcher.infra.data.TimelineItem;
import dev.haotangyuan.researcher.infra.exception.ResearchException;
import dev.haotangyuan.researcher.infra.util.CacheUtil;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * @author: haotangyuan
 */
@Component
@Slf4j
@RequiredArgsConstructor
public class SseHub {

    private static final Long SSE_TIMEOUT_MS = 0L;
    private static final long HEARTBEAT_INTERVAL_MS = 30_000L;  // 30秒心跳

    // researchId -> (clientId -> emitter)
    private final Map<String, Map<String, SseEmitter>> researchEmitters = new ConcurrentHashMap<>();
    private final CacheUtil cacheUtil;
    private ScheduledExecutorService heartbeatScheduler;

    @PostConstruct
    public void init() {
        heartbeatScheduler = Executors.newSingleThreadScheduledExecutor();
        heartbeatScheduler.scheduleAtFixedRate(this::sendHeartbeat,
                HEARTBEAT_INTERVAL_MS, HEARTBEAT_INTERVAL_MS, TimeUnit.MILLISECONDS);
    }

    @PreDestroy
    public void destroy() {
        if (heartbeatScheduler != null) {
            heartbeatScheduler.shutdown();
        }
    }

    private void sendHeartbeat() {
        List<String[]> toRemove = new ArrayList<>();
        for (Map.Entry<String, Map<String, SseEmitter>> research : researchEmitters.entrySet()) {
            String researchId = research.getKey();
            for (Map.Entry<String, SseEmitter> client : research.getValue().entrySet()) {
                String clientId = client.getKey();
                SseEmitter emitter = client.getValue();
                try {
                    emitter.send(SseEmitter.event().comment("heartbeat"));
                } catch (IOException e) {
                    log.debug("心跳失败，移除连接 researchId={}, clientId={}", researchId, clientId);
                    toRemove.add(new String[]{researchId, clientId});
                }
            }
        }
        toRemove.forEach(pair -> remove(pair[0], pair[1]));
    }

    public SseEmitter connect(Long userId, String researchId, String clientId, String lastEventId) {
        if (!cacheUtil.verifyResearchOwnership(researchId, userId)) {
            throw new ResearchException("研究任务不存在或无权限访问");
        }
        SseEmitter emitter = new SseEmitter(SSE_TIMEOUT_MS);
        emitter.onCompletion(() -> remove(researchId, clientId));
        emitter.onTimeout(() -> remove(researchId, clientId));
        emitter.onError(ex -> remove(researchId, clientId));

        researchEmitters
                .computeIfAbsent(researchId, k -> new ConcurrentHashMap<>())
                .put(clientId, emitter);

        replayIfNeeded(userId, researchId, emitter, lastEventId);

        return emitter;
    }

    private void remove(String researchId, String clientId) {
        Map<String, SseEmitter> clients = researchEmitters.get(researchId);
        if(CollectionUtil.isEmpty(clients)) {
            return;
        }

        clients.remove(clientId);
        if (clients.isEmpty()) {
            researchEmitters.remove(researchId);
        }
    }

    public void sendTimelineItem(String researchId, TimelineItem item) {
        if (item == null || item.getSequenceNo() == null) {
            return;
        }
        String eventId = item.getSequenceNo().toString();
        Map<String, SseEmitter> clients = researchEmitters.get(researchId);
        if(CollectionUtil.isEmpty(clients)) {
            return;
        }

        for (Map.Entry<String, SseEmitter> entry : clients.entrySet()) {
            String clientId = entry.getKey();
            SseEmitter emitter = entry.getValue();
            if (emitter == null) {
                continue;
            }
            try {
                SseEmitter.SseEventBuilder builder = SseEmitter.event()
                        .id(eventId)
                        .name(item.getKind())
                        .data(item);
                emitter.send(builder);
            } catch (IOException e) {
                log.error("SSE 时间线推送失败，researchId={}, clientId={}", researchId, clientId, e);
                remove(researchId, clientId);
            }
        }
    }

    public void sendReportStream(String researchId, String partialText) {
        if (StrUtil.isEmptyIfStr(partialText)) {
            return;
        }
        Map<String, SseEmitter> clients = researchEmitters.get(researchId);
        if(CollectionUtil.isEmpty(clients)) {
            return;
        }

        for (Map.Entry<String, SseEmitter> entry : clients.entrySet()) {
            String clientId = entry.getKey();
            SseEmitter emitter = entry.getValue();
            if (emitter == null) {
                continue;
            }
            try {
                SseEmitter.SseEventBuilder builder = SseEmitter.event()
                        .name("report-stream")
                        .data(partialText);
                emitter.send(builder);
            } catch (IOException e) {
                log.error("SSE 报告流推送失败，researchId={}, clientId={}", researchId, clientId, e);
                remove(researchId, clientId);
            }
        }
    }

    private void replayIfNeeded(Long userId, String researchId, SseEmitter emitter, String lastEventId) {
        if (StrUtil.isEmptyIfStr(lastEventId)) {
            return;
        }

        Integer lastSeq = NumberUtil.parseInt(lastEventId.trim(), 0);

        List<TimelineItem> items = cacheUtil.getTimeline(researchId, lastSeq);
        if(CollectionUtil.isEmpty(items)) {
            return;
        }

        for (TimelineItem item : items) {
            try {
                String eventId = item.getSequenceNo().toString();
                SseEmitter.SseEventBuilder builder = SseEmitter.event()
                        .id(eventId)
                        .name(item.getKind())
                        .data(item);
                emitter.send(builder);
            } catch (IOException e) {
                log.error("重放失败 userId={}, researchId={}", userId, researchId, e);
                break;
            }
        }
    }

    public void complete(String researchId, String finalStatus) {
        Map<String, SseEmitter> clients = researchEmitters.get(researchId);
        if (CollectionUtil.isEmpty(clients)) {
            return;
        }
        for (Map.Entry<String, SseEmitter> entry : clients.entrySet()) {
            SseEmitter emitter = entry.getValue();
            try {
                emitter.send(SseEmitter.event()
                        .data("[DONE] " + finalStatus));
                emitter.complete();
            } catch (IOException e) {
                log.warn("SSE 结束失败", e);
            }
        }
    }
}

