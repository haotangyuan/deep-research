package dev.haotangyuan.researcher.domain.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import dev.haotangyuan.researcher.domain.entity.Model;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * @author: haotangyuan
 */
@Mapper
public interface ModelMapper extends BaseMapper<Model> {
    
    @Select("""
            SELECT * FROM model 
            WHERE type = 'GLOBAL' OR (type = 'USER' AND user_id = #{userId})
            ORDER BY type ASC, create_time DESC
            """)
    List<Model> selectAvailableModels(@Param("userId") Long userId);
}
