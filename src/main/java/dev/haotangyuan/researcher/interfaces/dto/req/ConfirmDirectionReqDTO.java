package dev.haotangyuan.researcher.interfaces.dto.req;

import lombok.Getter;

/**
 * 研究方向确认请求 DTO
 * @author: haotangyuan
 */
@Getter
public class ConfirmDirectionReqDTO {
    /** 操作类型: APPROVE 确认方向并开始研究, REVISE 修改方向 */
    private String action;
    /** 修改意见 (REVISE 时可选) */
    private String feedback;
}
