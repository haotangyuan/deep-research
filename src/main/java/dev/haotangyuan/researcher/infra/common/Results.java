package dev.haotangyuan.researcher.infra.common;


/**
 * @author: haotangyuan
 */
public final class Results {

    private Results() {}

    /**
     * 成功返回，默认 code = 0，message = "success"
     */
    public static <T> Result<T> success(T data) {
        return success(data, "success");
    }

    /**
     * 成功返回，需要添加返回数据和提示信息
     */
    public static <T> Result<T> success(T data, String message) {
        return Result.<T>builder()
                .code(0)
                .message(message)
                .data(data)
                .build();
    }

    public static <T> Result<T> failure(RuntimeException runtimeException) {
        return failure(runtimeException.getMessage());
    }

    /**
     * 失败返回，使用默认错误码 -1
     */
    public static <T> Result<T> failure(String message) {
        return failure(-1, message);
    }

    /**
     * 失败返回，需要指定错误码和错误信息。
     */
    public static <T> Result<T> failure(int code, String message) {
        return Result.<T>builder()
                .code(code)
                .message(message)
                .build();
    }
}
