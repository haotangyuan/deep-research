package dev.haotangyuan.researcher.infra.data;

import dev.haotangyuan.researcher.domain.entity.ChatMessage;
import dev.haotangyuan.researcher.domain.entity.WorkflowEvent;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * @author: haotangyuan
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class TimelineItem {
    private String kind;
    private String researchId;
    private Integer sequenceNo;
    private ChatMessage message;
    private WorkflowEvent event;
}
