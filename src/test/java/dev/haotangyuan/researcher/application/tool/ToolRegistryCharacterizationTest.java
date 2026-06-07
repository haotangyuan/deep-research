package dev.haotangyuan.researcher.application.tool;

import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolSpec;
import dev.haotangyuan.researcher.application.tool.annotation.ResearcherTool;
import dev.haotangyuan.researcher.application.tool.annotation.SupervisorTool;
import dev.haotangyuan.researcher.application.tool.detail.ConductResearchTool;
import dev.haotangyuan.researcher.application.tool.detail.ResearchCompleteTool;
import dev.haotangyuan.researcher.application.tool.detail.TavilySearchTool;
import dev.haotangyuan.researcher.application.tool.detail.ThinkTool;
import org.junit.jupiter.api.Test;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class ToolRegistryCharacterizationTest {

    @Test
    void registersCurrentSupervisorAndResearcherToolNamesByStage() {
        try (AnnotationConfigApplicationContext context = new AnnotationConfigApplicationContext()) {
            context.register(ThinkTool.class);
            context.register(ConductResearchTool.class);
            context.register(ResearchCompleteTool.class);
            context.register(TavilySearchTool.class);
            context.refresh();

            ToolRegistry registry = new ToolRegistry(context);

            assertThat(toolNames(registry.getToolSpecifications(SupervisorTool.class.getSimpleName())))
                    .containsExactlyInAnyOrder("thinkTool", "conductResearch", "researchComplete");
            assertThat(toolNames(registry.getToolSpecifications(ResearcherTool.class.getSimpleName())))
                    .containsExactlyInAnyOrder("thinkTool", "tavilySearch");
            assertThat(registry.getExecutor("thinkTool")).isNotNull();
            assertThat(registry.getExecutor("conductResearch")).isNotNull();
            assertThat(registry.getExecutor("researchComplete")).isNotNull();
            assertThat(registry.getExecutor("tavilySearch")).isNotNull();
        }
    }

    private static List<String> toolNames(List<ResearchToolSpec> specifications) {
        return specifications.stream()
                .map(ResearchToolSpec::name)
                .toList();
    }
}
