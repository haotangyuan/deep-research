package dev.haotangyuan.researcher.application.tool;

import dev.haotangyuan.researcher.application.tool.annotation.ResearcherTool;
import dev.haotangyuan.researcher.application.tool.annotation.SupervisorTool;
import dev.langchain4j.agent.tool.Tool;
import dev.langchain4j.agent.tool.ToolSpecification;
import dev.langchain4j.agent.tool.ToolSpecifications;
import dev.langchain4j.service.tool.DefaultToolExecutor;
import dev.langchain4j.service.tool.ToolExecutor;
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
 * Registry for all LangChain4j tools. Tools are grouped by stage based on marker annotations
 * @author: haotangyuan
 */
@Component
public class ToolRegistry {

    private final Map<String, ToolExecutor> toolExecutors = new ConcurrentHashMap<>();
    private final Map<String, List<ToolSpecification>> toolSpecificationsByStage = new ConcurrentHashMap<>();

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
        List<ToolSpecification> specifications = new ArrayList<>();

        for (Object toolBean : beansWithAnnotation.values()) {
            for (Method method : toolBean.getClass().getMethods()) {
                if (!method.isAnnotationPresent(Tool.class)) {
                    continue;
                }

                ToolSpecification specification = ToolSpecifications.toolSpecificationFrom(method);
                specifications.add(specification);
                toolExecutors.putIfAbsent(specification.name(), new DefaultToolExecutor(toolBean, method));
            }
        }

        toolSpecificationsByStage.put(stageName, Collections.unmodifiableList(specifications));
    }

    public List<ToolSpecification> getToolSpecifications(String stageName) {
        return toolSpecificationsByStage.getOrDefault(stageName, Collections.emptyList());
    }

    public ToolExecutor getExecutor(String toolName) {
        return toolExecutors.get(toolName);
    }
}