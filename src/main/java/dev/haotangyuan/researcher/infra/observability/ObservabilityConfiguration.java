package dev.haotangyuan.researcher.infra.observability;

import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.api.OpenTelemetry;
import io.opentelemetry.api.common.AttributeKey;
import io.opentelemetry.api.common.Attributes;
import io.opentelemetry.exporter.otlp.http.trace.OtlpHttpSpanExporter;
import io.opentelemetry.sdk.OpenTelemetrySdk;
import io.opentelemetry.sdk.resources.Resource;
import io.opentelemetry.sdk.trace.SdkTracerProvider;
import io.opentelemetry.sdk.trace.export.BatchSpanProcessor;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.lang.reflect.Method;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

@Component
@RequiredArgsConstructor
@Slf4j
public class ObservabilityConfiguration {
    private static final AtomicBoolean GLOBAL_OTEL_SET = new AtomicBoolean(false);

    private final ResearchObservabilityProps props;
    private SdkTracerProvider tracerProvider;

    @PostConstruct
    public void initialize() {
        initializeOpenTelemetry();
        initializeStudioIfRequested();
    }

    private OpenTelemetry initializeOpenTelemetry() {
        if (!props.isExportEnabled()) {
            log.info("Deep Research observability export is disabled");
            return GlobalOpenTelemetry.get();
        }
        var exporterBuilder = OtlpHttpSpanExporter.builder()
                .setEndpoint(props.resolvedEndpoint());
        for (Map.Entry<String, String> header : props.exportHeaders().entrySet()) {
            exporterBuilder.addHeader(header.getKey(), header.getValue());
        }
        tracerProvider = SdkTracerProvider.builder()
                .setResource(Resource.getDefault().merge(Resource.create(Attributes.of(
                        AttributeKey.stringKey("service.name"), "deep-research"))))
                .addSpanProcessor(BatchSpanProcessor.builder(exporterBuilder.build()).build())
                .build();
        OpenTelemetrySdk sdk = OpenTelemetrySdk.builder()
                .setTracerProvider(tracerProvider)
                .build();
        if (GLOBAL_OTEL_SET.compareAndSet(false, true)) {
            try {
                GlobalOpenTelemetry.set(sdk);
            } catch (IllegalStateException e) {
                log.warn("Global OpenTelemetry was already initialized; using the existing global instance");
            }
        } else {
            log.warn("Global OpenTelemetry was already initialized; using the existing global instance");
        }
        log.info("Deep Research observability export enabled: provider={}, endpoint={}",
                props.getProvider(), props.resolvedEndpoint());
        return sdk;
    }

    private void initializeStudioIfRequested() {
        if (!props.getStudio().isEnabled()) {
            return;
        }
        try {
            Class<?> managerClass = Class.forName("io.agentscope.core.studio.StudioManager");
            Object builder = managerClass.getMethod("init").invoke(null);
            invokeIfPresent(builder, "studioUrl", props.getStudio().getUrl());
            invokeIfPresent(builder, "project", props.getStudio().getProject());
            invokeIfPresent(builder, "runName", "deep-research-" + System.currentTimeMillis());
            Object initialized = builder.getClass().getMethod("initialize").invoke(builder);
            invokeIfPresent(initialized, "block");
            log.info("AgentScope Studio initialized for project {}", props.getStudio().getProject());
        } catch (ClassNotFoundException e) {
            log.warn("AgentScope Studio classes are not available in the current agentscope-java dependency");
        } catch (Exception e) {
            log.warn("AgentScope Studio initialization failed; research execution will continue", e);
        }
    }

    private static void invokeIfPresent(Object target, String methodName, Object... args) throws Exception {
        if (target == null) {
            return;
        }
        for (Method method : target.getClass().getMethods()) {
            if (method.getName().equals(methodName) && method.getParameterCount() == args.length) {
                method.invoke(target, args);
                return;
            }
        }
    }

    @PreDestroy
    public void shutdown() {
        if (tracerProvider != null) {
            tracerProvider.shutdown();
        }
    }

    static void resetForTests() {
        GLOBAL_OTEL_SET.set(false);
    }
}
