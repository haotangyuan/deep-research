package dev.haotangyuan.researcher.domain.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import dev.haotangyuan.researcher.domain.entity.WorkflowEvent;
import org.apache.ibatis.annotations.Mapper;

/**
 * @author: haotangyuan
 */
@Mapper
public interface WorkflowEventMapper extends BaseMapper<WorkflowEvent> {
}
