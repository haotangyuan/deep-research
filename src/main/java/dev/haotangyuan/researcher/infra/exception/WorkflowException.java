package dev.haotangyuan.researcher.infra.exception;

/**
 * @author: haotangyuan
 */
public class WorkflowException extends RuntimeException {

    public WorkflowException(String message) {
        super(message);
    }

    public WorkflowException(String message, Throwable cause) {
        super(message, cause);
    }
}
