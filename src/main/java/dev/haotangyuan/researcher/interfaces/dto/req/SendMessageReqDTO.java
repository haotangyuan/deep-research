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
    private String hitlMode;   // HITL模式: NONE 或 DIRECTION_ONLY，默认 DIRECTION_ONLY
}
