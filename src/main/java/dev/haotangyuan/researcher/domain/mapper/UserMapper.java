package dev.haotangyuan.researcher.domain.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import dev.haotangyuan.researcher.domain.entity.User;
import org.apache.ibatis.annotations.Mapper;

/**
 * @author: haotangyuan
 */
@Mapper
public interface UserMapper extends BaseMapper<User> {
}
