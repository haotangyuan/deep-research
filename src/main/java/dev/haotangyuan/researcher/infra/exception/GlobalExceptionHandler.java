package dev.haotangyuan.researcher.infra.exception;

import dev.haotangyuan.researcher.infra.common.Result;
import dev.haotangyuan.researcher.infra.common.Results;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * 全局异常处理器
 * @author haotangyuan
 */
@RestControllerAdvice
@Slf4j
public class GlobalExceptionHandler {

    @ExceptionHandler(ResearchException.class)
    public Result<Void> handleResearchException(ResearchException e) {
        log.warn("ResearchException: {}", e.getMessage());
        return Results.failure(e);
    }

    @ExceptionHandler(UserException.class)
    public Result<Void> handleUserException(UserException e) {
        log.warn("UserException: {}", e.getMessage());
        return Results.failure(e);
    }

    @ExceptionHandler(ModelException.class)
    public Result<Void> handleModelException(ModelException e) {
        log.warn("ModelException: {}", e.getMessage());
        return Results.failure(e);
    }

    @ExceptionHandler(Exception.class)
    public Result<Void> handleException(Exception e) {
        log.error("Unexpected exception", e);
        return Results.failure("执行异常");
    }
}
