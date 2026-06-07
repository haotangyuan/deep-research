package dev.haotangyuan.researcher.infra.observability;

import java.util.Optional;

public final class ResearchTraceSanitizer {
    private ResearchTraceSanitizer() {
    }

    public static Optional<String> summarize(String value, ResearchObservabilityProps props) {
        if (props == null || !props.isCaptureInputOutput() || value == null || value.isBlank()) {
            return Optional.empty();
        }
        String sanitized = value
                .replaceAll("(?i)authorization\\s*[:=]\\s*\\S+", "authorization=[redacted]")
                .replaceAll("(?i)(api[_-]?key|secret|token)\\s*[:=]\\s*\\S+", "$1=[redacted]");
        int max = props.getInputOutputMaxChars();
        if (max <= 0 || sanitized.length() <= max) {
            return Optional.of(sanitized);
        }
        return Optional.of(sanitized.substring(0, max));
    }
}
