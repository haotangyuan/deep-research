package dev.haotangyuan.researcher.application.tool;

import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolParameter;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolSpec;
import dev.haotangyuan.researcher.application.tool.annotation.ResearcherTool;
import dev.haotangyuan.researcher.application.tool.annotation.ResearchTool;
import dev.haotangyuan.researcher.application.tool.annotation.ResearchToolParam;
import dev.haotangyuan.researcher.application.tool.annotation.SupervisorTool;
import org.springframework.context.ApplicationContext;
import org.springframework.stereotype.Component;

import java.lang.annotation.Annotation;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Registry for project-owned tool metadata. Tools are grouped by stage based on marker annotations.
 * @author: haotangyuan
 */
@Component
public class ToolRegistry {

    private final Map<String, ResearchToolExecutor> toolExecutors = new ConcurrentHashMap<>();
    private final Map<String, List<ResearchToolSpec>> toolSpecificationsByStage = new ConcurrentHashMap<>();

    public ToolRegistry(ApplicationContext applicationContext) {
        registerStage(applicationContext, SupervisorTool.class);
        registerStage(applicationContext, ResearcherTool.class);
    }

    private void registerStage(ApplicationContext applicationContext, Class<? extends Annotation> markerAnnotation) {
        Map<String, Object> beansWithAnnotation = applicationContext.getBeansWithAnnotation(markerAnnotation);
        if (beansWithAnnotation.isEmpty()) {
            return;
        }

        String stageName = markerAnnotation.getSimpleName();
        List<ResearchToolSpec> specifications = new ArrayList<>();

        for (Object toolBean : beansWithAnnotation.values()) {
            for (Method method : toolBean.getClass().getMethods()) {
                if (!method.isAnnotationPresent(ResearchTool.class)) {
                    continue;
                }

                ResearchToolSpec specification = toolSpecificationFrom(method);
                specifications.add(specification);
                toolExecutors.putIfAbsent(specification.name(), new ReflectiveResearchToolExecutor(toolBean, method));
            }
        }

        toolSpecificationsByStage.put(stageName, Collections.unmodifiableList(specifications));
    }

    public List<ResearchToolSpec> getToolSpecifications(String stageName) {
        return toolSpecificationsByStage.getOrDefault(stageName, Collections.emptyList());
    }

    public ResearchToolExecutor getExecutor(String toolName) {
        return toolExecutors.get(toolName);
    }

    private ResearchToolSpec toolSpecificationFrom(Method method) {
        ResearchTool tool = method.getAnnotation(ResearchTool.class);
        List<ResearchToolParameter> parameters = new ArrayList<>();
        for (java.lang.reflect.Parameter parameter : method.getParameters()) {
            ResearchToolParam metadata = parameter.getAnnotation(ResearchToolParam.class);
            if (metadata == null) {
                continue;
            }
            parameters.add(new ResearchToolParameter(
                    metadata.name(),
                    metadata.description(),
                    metadata.required(),
                    parameter.getType()));
        }
        return new ResearchToolSpec(tool.name(), tool.description(), parameters);
    }
}
