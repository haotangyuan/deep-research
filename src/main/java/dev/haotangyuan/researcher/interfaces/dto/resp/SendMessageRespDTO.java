package dev.haotangyuan.researcher.interfaces.dto.resp;

import lombok.Builder;
import lombok.Data;


/**
 * @author: haotangyuan
 */
@Data
@Builder
public class SendMessageRespDTO {
    private String id;
    private String content;
}
