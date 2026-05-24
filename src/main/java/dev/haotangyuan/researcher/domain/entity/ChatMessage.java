package dev.haotangyuan.researcher.domain.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * @author: haotangyuan
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ChatMessage {

    @TableId(value = "id", type = IdType.AUTO)
    private Long id;
    private String researchId;
    private String role; // user | assistant
    private String content;
    private Integer sequenceNo;
    private LocalDateTime createTime;
}