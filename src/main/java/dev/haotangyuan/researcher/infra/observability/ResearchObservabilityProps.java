package dev.haotangyuan.researcher.infra.observability;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;

@Configuration
@ConfigurationProperties(prefix = "research.observability")
public class ResearchObservabilityProps {
    private boolean enabled = false;
    private String provider = "none";
    private String endpoint = "";
    private Map<String, String> headers = new LinkedHashMap<>();
    private boolean captureInputOutput = false;
    private int inputOutputMaxChars = 500;
    private Langfuse langfuse = new Langfuse();
    private Studio studio = new Studio();

    public boolean isExportEnabled() {
        return enabled && !resolvedEndpoint().isBlank();
    }

    public String resolvedEndpoint() {
        if (endpoint != null && !endpoint.isBlank()) {
            return endpoint.trim();
        }
        if (isLangfuseProvider()) {
            return "https://cloud.langfuse.com/api/public/otel/v1/traces";
        }
        return "";
    }

    public Map<String, String> exportHeaders() {
        Map<String, String> resolved = new LinkedHashMap<>();
        if (headers != null) {
            resolved.putAll(headers);
        }
        if (isLangfuseProvider() && langfuse.hasCredentials()) {
            String credential = langfuse.publicKey + ":" + langfuse.secretKey;
            String encoded = Base64.getEncoder().encodeToString(credential.getBytes(StandardCharsets.UTF_8));
            resolved.put("Authorization", "Basic " + encoded);
            resolved.put("x-langfuse-ingestion-version", langfuse.ingestionVersion);
        }
        return resolved;
    }

    public boolean isLangfuseProvider() {
        return "langfuse".equals(normalizedProvider()) || langfuse.hasCredentials();
    }

    private String normalizedProvider() {
        return provider == null ? "" : provider.trim().toLowerCase(Locale.ROOT);
    }

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public String getProvider() {
        return provider;
    }

    public void setProvider(String provider) {
        this.provider = provider;
    }

    public String getEndpoint() {
        return endpoint;
    }

    public void setEndpoint(String endpoint) {
        this.endpoint = endpoint;
    }

    public Map<String, String> getHeaders() {
        return headers;
    }

    public void setHeaders(Map<String, String> headers) {
        this.headers = headers == null ? new LinkedHashMap<>() : new LinkedHashMap<>(headers);
    }

    public boolean isCaptureInputOutput() {
        return captureInputOutput;
    }

    public void setCaptureInputOutput(boolean captureInputOutput) {
        this.captureInputOutput = captureInputOutput;
    }

    public int getInputOutputMaxChars() {
        return inputOutputMaxChars;
    }

    public void setInputOutputMaxChars(int inputOutputMaxChars) {
        this.inputOutputMaxChars = Math.max(0, inputOutputMaxChars);
    }

    public Langfuse getLangfuse() {
        return langfuse;
    }

    public void setLangfuse(Langfuse langfuse) {
        this.langfuse = langfuse == null ? new Langfuse() : langfuse;
    }

    public Studio getStudio() {
        return studio;
    }

    public void setStudio(Studio studio) {
        this.studio = studio == null ? new Studio() : studio;
    }

    public static class Langfuse {
        private String publicKey = "";
        private String secretKey = "";
        private String ingestionVersion = "4";

        boolean hasCredentials() {
            return publicKey != null && !publicKey.isBlank()
                    && secretKey != null && !secretKey.isBlank();
        }

        public String getPublicKey() {
            return publicKey;
        }

        public void setPublicKey(String publicKey) {
            this.publicKey = publicKey;
        }

        public String getSecretKey() {
            return secretKey;
        }

        public void setSecretKey(String secretKey) {
            this.secretKey = secretKey;
        }

        public String getIngestionVersion() {
            return ingestionVersion;
        }

        public void setIngestionVersion(String ingestionVersion) {
            this.ingestionVersion = ingestionVersion == null || ingestionVersion.isBlank()
                    ? "4"
                    : ingestionVersion;
        }
    }

    public static class Studio {
        private boolean enabled = false;
        private String url = "http://localhost:3000";
        private String project = "DeepResearch";

        public boolean isEnabled() {
            return enabled;
        }

        public void setEnabled(boolean enabled) {
            this.enabled = enabled;
        }

        public String getUrl() {
            return url;
        }

        public void setUrl(String url) {
            this.url = url;
        }

        public String getProject() {
            return project;
        }

        public void setProject(String project) {
            this.project = project;
        }
    }
}
