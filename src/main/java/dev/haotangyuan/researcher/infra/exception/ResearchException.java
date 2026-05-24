package dev.haotangyuan.researcher.infra.exception;

/**
 * @author: haotangyuan
 */
public class ResearchException extends RuntimeException {

    public ResearchException(String message) {
        super(message);
    }

    public ResearchException(String message, Throwable cause) {
        super(message, cause);
    }
}
