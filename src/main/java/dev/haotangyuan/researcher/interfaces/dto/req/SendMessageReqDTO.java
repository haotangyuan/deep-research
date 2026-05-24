package dev.haotangyuan.researcher.interfaces.dto.req;

import lombok.Getter;

/**
 * @author: haotangyuan
 */
@Getter
public class SendMessageReqDTO {
    private String content;
    private String modelId;
    private String budget;     // 研究预算级别: MEDIUM, HIGH, ULTRA
}
