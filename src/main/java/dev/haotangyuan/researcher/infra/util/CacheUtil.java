package dev.haotangyuan.researcher.infra.util;

import cn.hutool.core.collection.CollectionUtil;
import cn.hutool.core.util.StrUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.haotangyuan.researcher.domain.entity.ChatMessage;
import dev.haotangyuan.researcher.domain.entity.WorkflowEvent;
import dev.haotangyuan.researcher.domain.entity.ResearchSession;
import dev.haotangyuan.researcher.domain.mapper.ChatMessageMapper;
import dev.haotangyuan.researcher.domain.mapper.WorkflowEventMapper;
import dev.haotangyuan.researcher.domain.mapper.ResearchSessionMapper;
import dev.haotangyuan.researcher.infra.data.TimelineItem;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ZSetOperations;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

/**
 * @author: haotangyuan
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class CacheUtil {

    private final ChatMessageMapper chatMessageMapper;
    private final WorkflowEventMapper workflowEventMapper;
    private final ResearchSessionMapper researchSessionMapper;
    private final SequenceUtil sequenceUtil;
    private final StringRedisTemplate stringRedisTemplate;
    private final ObjectMapper objectMapper;

    private static final String KIND_MESSAGE = "message";
    private static final String KIND_EVENT = "event";
    private static final String TIMELINE_KEY = "research:{}:timeline";
    private static final long TIMELINE_TTL_MINUTES = 30;

    // 用户研究集合：user:{userId}:researches -> Set<researchId>
    private static final String USER_RESEARCHES_KEY = "user:{}:researches";

    public TimelineItem saveMessage(String researchId, String role, String content) {
        int seq = sequenceUtil.next(researchId);
        ChatMessage message = ChatMessage.builder()
                .researchId(researchId)
                .role(role)
                .content(content)
                .sequenceNo(seq)
                .createTime(LocalDateTime.now())
                .build();
        chatMessageMapper.insert(message);
        TimelineItem item = TimelineItem.builder()
                .kind(KIND_MESSAGE)
                .researchId(researchId)
                .sequenceNo(seq)
                .message(message)
                .build();
        writeToRedis(researchId, List.of(item));
        return item;
    }

    public TimelineItem saveEvent(String researchId, String type,
                                    String title, String content, Long parentEventId) {
        int seq = sequenceUtil.next(researchId);
        WorkflowEvent event = WorkflowEvent.builder()
                .researchId(researchId)
                .type(type)
                .title(title)
                .content(content)
                .parentEventId(parentEventId)
                .sequenceNo(seq)
                .createTime(LocalDateTime.now())
                .build();
        workflowEventMapper.insert(event);
        TimelineItem item = TimelineItem.builder()
                .kind(KIND_EVENT)
                .researchId(researchId)
                .sequenceNo(seq)
                .event(event)
                .build();
        writeToRedis(researchId, List.of(item));
        return item;
    }

    /**
     * 保存临时事件排队信息，用于前端显示排队状态，seq = -1
     */
    public TimelineItem saveTempEvent(String researchId, String type, String title) {
        WorkflowEvent event = WorkflowEvent.builder()
                .researchId(researchId)
                .type(type)
                .title(title)
                .sequenceNo(-1)
                .createTime(LocalDateTime.now())
                .build();
        TimelineItem item = TimelineItem.builder()
                .kind(KIND_EVENT)
                .researchId(researchId)
                .sequenceNo(-1)
                .event(event)
                .build();
        writeToRedis(researchId, List.of(item));
        return item;
    }

    public List<TimelineItem> getTimeline(String researchId, int lastSeq) {
        List<TimelineItem> redisItems = readFromRedis(researchId, lastSeq + 1, Integer.MAX_VALUE);
        if (!redisItems.isEmpty()) {
            return redisItems;
        }
        List<TimelineItem> all = loadFromDb(researchId);
        writeToRedis(researchId, all);
        // lastSeq == 0 表示从头开始
        if (lastSeq == 0) {
            return all;
        }
        return all.stream()
                .filter(item -> item.getSequenceNo() > lastSeq)
                .collect(Collectors.toList());
    }

    private void writeToRedis(String researchId, List<TimelineItem> items) {
        if (CollectionUtil.isEmpty(items)) {
            return;
        }
        String key = StrUtil.format(TIMELINE_KEY, researchId);
        Set<ZSetOperations.TypedTuple<String>> tuples = new HashSet<>();
        for (TimelineItem item : items) {
            String value = serialize(item);
            if (value != null) {
                tuples.add(ZSetOperations.TypedTuple.of(value, (double) item.getSequenceNo()));
            }
        }
        if (!tuples.isEmpty()) {
            stringRedisTemplate.opsForZSet().add(key, tuples);
            stringRedisTemplate.expire(key, TIMELINE_TTL_MINUTES, TimeUnit.MINUTES);
        }
    }

    private List<TimelineItem> readFromRedis(String researchId, int minSeq, int maxSeq) {
        String key = StrUtil.format(TIMELINE_KEY, researchId);
        Set<String> values = stringRedisTemplate.opsForZSet().rangeByScore(key, minSeq, maxSeq);
        if (CollectionUtil.isEmpty(values)) {
            return new ArrayList<>();
        }
        stringRedisTemplate.expire(key, TIMELINE_TTL_MINUTES, TimeUnit.MINUTES);
        return values.stream()
                .map(this::deserialize)
                .filter(Objects::nonNull)
                .sorted(Comparator.comparing(TimelineItem::getSequenceNo))
                .collect(Collectors.toList());
    }

    private List<TimelineItem> loadFromDb(String researchId) {
        LambdaQueryWrapper<ChatMessage> messageQuery = Wrappers.lambdaQuery(ChatMessage.class)
                .eq(ChatMessage::getResearchId, researchId);
        LambdaQueryWrapper<WorkflowEvent> eventQuery = Wrappers.lambdaQuery(WorkflowEvent.class)
                .eq(WorkflowEvent::getResearchId, researchId);
        List<ChatMessage> messages = chatMessageMapper.selectList(messageQuery);
        List<WorkflowEvent> events = workflowEventMapper.selectList(eventQuery);
        List<TimelineItem> all = new ArrayList<>();
        messages.stream()
            .map(m -> TimelineItem.builder()
                    .kind(KIND_MESSAGE)
                    .researchId(researchId)
                    .sequenceNo(m.getSequenceNo())
                    .message(m)
                    .build())
            .forEach(all::add);
        events.stream()
            .map(e -> TimelineItem.builder()
                    .kind(KIND_EVENT)
                    .researchId(researchId)
                    .sequenceNo(e.getSequenceNo())
                    .event(e)
                    .build())
            .forEach(all::add);
        all.sort(Comparator.comparing(TimelineItem::getSequenceNo));
        return all;
    }

    private String serialize(TimelineItem item) {
        try {
            return objectMapper.writeValueAsString(item);
        } catch (JsonProcessingException e) {
            log.error("TimelineItem 序列化 JSON 失败", e);
            return null;
        }
    }

    private TimelineItem deserialize(String json) {
        try {
            return objectMapper.readValue(json, TimelineItem.class);
        } catch (Exception e) {
            log.error("JSON 反序列化为 TimelineItem 失败 json={}", json, e);
            return null;
        }
    }

    /**
     * 验证 researchId 是否属于 userId
     */
    public boolean verifyResearchOwnership(String researchId, Long userId) {
        String key = StrUtil.format(USER_RESEARCHES_KEY, userId);
        Boolean isMember = stringRedisTemplate.opsForSet().isMember(key, researchId);
        
        if (Boolean.TRUE.equals(isMember)) {
            return true;
        }

        // 缓存未命中，回源 DB 兜底
        LambdaQueryWrapper<ResearchSession> queryWrapper = Wrappers.lambdaQuery(ResearchSession.class)
                .eq(ResearchSession::getId, researchId)
                .eq(ResearchSession::getUserId, userId);
        ResearchSession session = researchSessionMapper.selectOne(queryWrapper);

        if (session != null) {
            stringRedisTemplate.opsForSet().add(key, researchId);
            log.debug("权限验证成功，已缓存 userId={}, researchId={}", userId, researchId);
            return true;
        }

        log.debug("权限验证失败 userId={}, researchId={}", userId, researchId);
        return false;
    }

    /**
     * 缓存研究的所有权关系
     */
    public void cacheResearchOwnership(String researchId, Long userId) {
        String key = StrUtil.format(USER_RESEARCHES_KEY, userId);
        stringRedisTemplate.opsForSet().add(key, researchId);
        log.debug("缓存权限映射 userId={}, researchId={}", userId, researchId);
    }
}
