package dev.haotangyuan.researcher.application.tool.annotation;

import org.junit.jupiter.api.Test;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;
import java.util.Arrays;

import static org.assertj.core.api.Assertions.assertThat;

class ResearchToolMetadataTest {

    @Test
    void researchToolMetadataIsRuntimeMethodAnnotation() {
        assertThat(ResearchTool.class.getAnnotation(Retention.class).value())
                .isEqualTo(RetentionPolicy.RUNTIME);
        assertThat(ResearchTool.class.getAnnotation(Target.class).value())
                .containsExactly(ElementType.METHOD);
    }

    @Test
    void researchToolParamMetadataIsRuntimeParameterAnnotation() {
        assertThat(ResearchToolParam.class.getAnnotation(Retention.class).value())
                .isEqualTo(RetentionPolicy.RUNTIME);
        assertThat(Arrays.asList(ResearchToolParam.class.getAnnotation(Target.class).value()))
                .containsExactly(ElementType.PARAMETER);
    }
}
