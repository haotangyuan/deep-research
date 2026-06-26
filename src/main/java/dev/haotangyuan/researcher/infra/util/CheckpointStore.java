package dev.haotangyuan.researcher.infra.util;

import cn.hutool.core.util.StrUtil;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.haotangyuan.researcher.application.state.DeepResearchState;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.util.concurrent.TimeUnit;

/**
 * HITL 检查点存储——基于 Redis 序列化 DeepResearchState
 * @author: haotangyuan
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class CheckpointStore {

    private final StringRedisTemplate stringRedisTemplate;
    private final ObjectMapper objectMapper;

    private static final String CHECKPOINT_KEY = "research:{}:checkpoint";
    private static final long TTL_MINUTES = 30;

    /**
     * 保存 HITL 检查点状态到 Redis
     */
    public void save(String researchId, DeepResearchState state) {
        try {
            String key = StrUtil.format(CHECKPOINT_KEY, researchId);
            String json = objectMapper.writeValueAsString(state);
            stringRedisTemplate.opsForValue().set(key, json, TTL_MINUTES, TimeUnit.MINUTES);
            log.debug("Checkpoint 已保存 researchId={}", researchId);
        } catch (JsonProcessingException e) {
            log.error("Checkpoint 序列化失败 researchId={}", researchId, e);
        }
    }

    /**
     * 从 Redis 加载 HITL 检查点状态
     *
     * @return DeepResearchState 或 null（已过期/不存在）
     */
    public DeepResearchState load(String researchId) {
        String key = StrUtil.format(CHECKPOINT_KEY, researchId);
        String json = stringRedisTemplate.opsForValue().get(key);
        if (StrUtil.isBlank(json)) {
            log.debug("Checkpoint 不存在或已过期 researchId={}", researchId);
            return null;
        }
        try {
            return objectMapper.readValue(json, DeepResearchState.class);
        } catch (JsonProcessingException e) {
            log.error("Checkpoint 反序列化失败 researchId={}", researchId, e);
            return null;
        }
    }

    /**
     * 删除检查点（研究完成后清理）
     */
    public void remove(String researchId) {
        stringRedisTemplate.delete(StrUtil.format(CHECKPOINT_KEY, researchId));
        log.debug("Checkpoint 已删除 researchId={}", researchId);
    }
}
