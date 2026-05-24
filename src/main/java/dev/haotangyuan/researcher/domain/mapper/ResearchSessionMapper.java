package dev.haotangyuan.researcher.domain.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import dev.haotangyuan.researcher.domain.entity.ResearchSession;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/**
 * @author: haotangyuan
 */
@Mapper
public interface ResearchSessionMapper extends BaseMapper<ResearchSession> {

    @Select("SELECT * FROM research_session WHERE id = #{id} FOR UPDATE")
    ResearchSession selectByIdForUpdate(@Param("id") String id);

    @Update("""
            <script>
            UPDATE research_session
            SET status = #{status},
                update_time = NOW()
                <if test="setStartTime">, start_time = NOW()</if>
                <if test="setCompleteTime">, complete_time = NOW()</if>
                , total_input_tokens = COALESCE(total_input_tokens, 0) + #{inputTokens}
                , total_output_tokens = COALESCE(total_output_tokens, 0) + #{outputTokens}
            WHERE id = #{id}
            </script>
            """)
    void updateSession(@Param("id") String id, @Param("status") String status,
                       @Param("setStartTime") boolean setStartTime, @Param("setCompleteTime") boolean setCompleteTime,
                       @Param("inputTokens") long inputTokens, @Param("outputTokens") long outputTokens);

    // 后续支持历史研究继续研究
    @Update("""
            UPDATE research_session
            SET status = 'QUEUE', update_time = NOW()
            WHERE id = #{id} AND user_id = #{userId}
              AND status IN ('NEW', 'NEED_CLARIFICATION')
            """)
    int casUpdateToQueue(@Param("id") String id, @Param("userId") Long userId);

    // 首次发言时记录模型、预算和标题
    @Update("""
            <script>
            UPDATE research_session
            SET update_time = NOW()
            <if test="modelId != null">, model_id = #{modelId}</if>
            <if test="budget != null">, budget = #{budget}</if>
            <if test="title != null">, title = #{title}</if>
            WHERE id = #{id} AND model_id IS NULL
            </script>
            """)
    int setInfoIfNull(@Param("id") String id, @Param("modelId") String modelId, 
                                 @Param("budget") String budget, @Param("title") String title);

    @Select("""
            SELECT COUNT(*) FROM research_session 
            WHERE model_id = #{modelId} 
            AND status NOT IN ('COMPLETED', 'FAILED')
            """)
    int countActiveUsage(@Param("modelId") String modelId);
}
