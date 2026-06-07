package dev.haotangyuan.researcher.infra.util;

/**
 * Extracts a JSON object from model text responses that may include prose or
 * Markdown fences around the structured payload.
 */
public final class JsonOutputParser {
    private JsonOutputParser() {
    }

    public static String extractObject(String text) {
        if (text == null) {
            throw new IllegalArgumentException("JSON output is null");
        }
        int start = text.indexOf('{');
        if (start < 0) {
            throw new IllegalArgumentException("JSON object start not found");
        }

        boolean inString = false;
        boolean escaping = false;
        int depth = 0;
        for (int i = start; i < text.length(); i++) {
            char ch = text.charAt(i);
            if (escaping) {
                escaping = false;
                continue;
            }
            if (ch == '\\' && inString) {
                escaping = true;
                continue;
            }
            if (ch == '"') {
                inString = !inString;
                continue;
            }
            if (inString) {
                continue;
            }
            if (ch == '{') {
                depth++;
            } else if (ch == '}') {
                depth--;
                if (depth == 0) {
                    return text.substring(start, i + 1);
                }
            }
        }
        throw new IllegalArgumentException("JSON object end not found");
    }
}
