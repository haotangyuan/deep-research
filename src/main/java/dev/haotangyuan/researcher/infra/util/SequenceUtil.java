package dev.haotangyuan.researcher.infra.util;

import dev.haotangyuan.researcher.domain.mapper.ChatMessageMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * @author: haotangyuan
 */
@Component
@RequiredArgsConstructor
public class SequenceUtil {

    private final ChatMessageMapper chatMessageMapper;

    // 0 为起始，即无
    private final Map<String, AtomicLong> sseSequences = new ConcurrentHashMap<>();

    public int next(String researchId) {
        AtomicLong counter = sseSequences.computeIfAbsent(researchId, k -> {
            Integer maxSeq = chatMessageMapper.selectMaxSequenceByResearchId(researchId);
            return new AtomicLong(maxSeq == null ? 0L : maxSeq);
        });
        long value = counter.incrementAndGet();
        return (int) value;
    }

    public int current(String researchId) {
        AtomicLong counter = sseSequences.get(researchId);
        return counter == null ? 0 : (int) counter.get();
    }

    public void reset(String researchId) {
        sseSequences.remove(researchId);
    }
}
