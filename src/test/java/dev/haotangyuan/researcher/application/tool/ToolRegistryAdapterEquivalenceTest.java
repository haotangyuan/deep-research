package dev.haotangyuan.researcher.application.tool;

import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolParameter;
import dev.haotangyuan.researcher.application.agent.runtime.ResearchToolSpec;
import dev.haotangyuan.researcher.application.agent.runtime.agentscope.AgentscopeJavaChatClient;
import dev.haotangyuan.researcher.application.agent.runtime.langchain4j.Langchain4jChatClient;
import dev.haotangyuan.researcher.application.tool.annotation.ResearcherTool;
import dev.haotangyuan.researcher.application.tool.annotation.SupervisorTool;
import dev.haotangyuan.researcher.application.tool.detail.ConductResearchTool;
import dev.haotangyuan.researcher.application.tool.detail.ResearchCompleteTool;
import dev.haotangyuan.researcher.application.tool.detail.TavilySearchTool;
import dev.haotangyuan.researcher.application.tool.detail.ThinkTool;
import dev.langchain4j.agent.tool.ToolSpecification;
import io.agentscope.core.model.ToolSchema;
import org.junit.jupiter.api.Test;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class ToolRegistryAdapterEquivalenceTest {

    @Test
    void stageToolContractsConvertEquivalentlyForBothRuntimeAdapters() {
        try (AnnotationConfigApplicationContext context = new AnnotationConfigApplicationContext()) {
            context.register(ThinkTool.class);
            context.register(ConductResearchTool.class);
            context.register(ResearchCompleteTool.class);
            context.register(TavilySearchTool.class);
            context.refresh();

            ToolRegistry registry = new ToolRegistry(context);

            assertStageEquivalence(
                    registry.getToolSpecifications(SupervisorTool.class.getSimpleName()),
                    List.of("thinkTool", "conductResearch", "researchComplete"));
            assertStageEquivalence(
                    registry.getToolSpecifications(ResearcherTool.class.getSimpleName()),
                    List.of("thinkTool", "tavilySearch"));
        }
    }

    private static void assertStageEquivalence(List<ResearchToolSpec> neutralSpecs, List<String> expectedNames) {
        List<ToolSpecification> langchainSpecs = Langchain4jChatClient.toLangchainToolSpecs(neutralSpecs);
        List<ToolSchema> agentscopeSpecs = AgentscopeJavaChatClient.toAgentscopeToolSpecs(neutralSpecs);

        assertThat(neutralSpecs).extracting(ResearchToolSpec::name)
                .containsExactlyInAnyOrderElementsOf(expectedNames);
        assertThat(langchainSpecs).extracting(ToolSpecification::name)
                .containsExactlyInAnyOrderElementsOf(expectedNames);
        assertThat(agentscopeSpecs).extracting(ToolSchema::getName)
                .containsExactlyInAnyOrderElementsOf(expectedNames);

        for (ResearchToolSpec neutralSpec : neutralSpecs) {
            ToolSpecification langchainSpec = findLangchainSpec(langchainSpecs, neutralSpec.name());
            ToolSchema agentscopeSpec = findAgentscopeSpec(agentscopeSpecs, neutralSpec.name());

            assertThat(langchainSpec.description()).isEqualTo(neutralSpec.description());
            assertThat(agentscopeSpec.getDescription()).isEqualTo(neutralSpec.description());

            List<String> parameterNames = neutralSpec.parameters().stream()
                    .map(ResearchToolParameter::name)
                    .toList();
            List<String> requiredNames = neutralSpec.parameters().stream()
                    .filter(ResearchToolParameter::required)
                    .map(ResearchToolParameter::name)
                    .toList();

            assertThat(langchainSpec.parameters().properties().keySet())
                    .containsExactlyInAnyOrderElementsOf(parameterNames);
            assertThat(langchainSpec.parameters().required())
                    .containsExactlyInAnyOrderElementsOf(requiredNames);

            assertThat(agentscopeSpec.getParameters()).containsEntry("type", "object");
            @SuppressWarnings("unchecked")
            Map<String, Object> properties =
                    (Map<String, Object>) agentscopeSpec.getParameters().get("properties");
            assertThat(properties.keySet()).containsExactlyInAnyOrderElementsOf(parameterNames);
            @SuppressWarnings("unchecked")
            List<String> agentscopeRequired =
                    (List<String>) agentscopeSpec.getParameters().getOrDefault("required", List.of());
            assertThat(agentscopeRequired).containsExactlyInAnyOrderElementsOf(requiredNames);
        }
    }

    private static ToolSpecification findLangchainSpec(List<ToolSpecification> specs, String name) {
        return specs.stream()
                .filter(spec -> spec.name().equals(name))
                .findFirst()
                .orElseThrow();
    }

    private static ToolSchema findAgentscopeSpec(List<ToolSchema> specs, String name) {
        return specs.stream()
                .filter(spec -> spec.getName().equals(name))
                .findFirst()
                .orElseThrow();
    }
}
