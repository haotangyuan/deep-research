package dev.haotangyuan.researcher.infra.exception;

/**
 * @author: haotangyuan
 */
public class UserException extends RuntimeException {

    public UserException(String message) {
        super(message);
    }

    public UserException(String message, Throwable cause) {
        super(message, cause);
    }
}
