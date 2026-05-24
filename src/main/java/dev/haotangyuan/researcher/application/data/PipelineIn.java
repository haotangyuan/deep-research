package dev.haotangyuan.researcher.application.data;

import lombok.Builder;
import lombok.Data;

/**
 * @author: haotangyuan
 */
@Data
@Builder
public class PipelineIn {
    private String researchId;
    private Integer userId;
    private String content;
}
