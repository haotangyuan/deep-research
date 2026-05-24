package dev.haotangyuan.researcher.infra.exception;

/**
 * Model related exception
 * @author: haotangyuan
 */
public class ModelException extends RuntimeException {
    
    public ModelException(String message) {
        super(message);
    }
    
    public ModelException(String message, Throwable cause) {
        super(message, cause);
    }
}
