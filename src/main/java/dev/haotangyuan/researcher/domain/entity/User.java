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
public class User {
    
    @TableId(type = IdType.AUTO)
    private Long id;
    private String username;
    private String password;
    private String googleId;
    private String avatarUrl;
    private LocalDateTime createTime;
    private LocalDateTime updateTime;
}
