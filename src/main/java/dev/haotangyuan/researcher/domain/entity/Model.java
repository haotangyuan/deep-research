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
public class Model {
    
    @TableId(value = "id", type = IdType.ASSIGN_UUID)
    private String id;
    private String type;
    private Long userId;
    private String name;
    private String model;
    private String baseUrl;
    private String apiKey;
    private LocalDateTime createTime;
    private LocalDateTime updateTime;
}
