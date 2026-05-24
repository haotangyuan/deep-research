package dev.haotangyuan.researcher.infra.common;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * @author: haotangyuan
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class Result<T> {
    /**
     * 业务状态码，0 表示成功，-1 表示失败
     */
    private int code;

    /**
     * 提示信息
     */
    private String message;

    /**
     * 返回数据
     */
    private T data;
}
