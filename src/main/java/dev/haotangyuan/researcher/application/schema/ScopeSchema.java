package dev.haotangyuan.researcher.application.schema;

import com.fasterxml.jackson.annotation.JsonProperty;
import dev.langchain4j.model.output.structured.Description;

/**
 * @author: haotangyuan
 */
public class ScopeSchema {

    public record ClarifyWithUserSchema(
            @JsonProperty(required = true)
            @Description("Whether the user needs to be asked a clarifying question.")
            boolean needClarification,

            @Description("A question to ask the user to clarify the report scope")
            String question,

            @Description("Verify message that we will start research after the user has provided the necessary information.")
            String verification
    ) {
    }

    public record ResearchQuestion(
            @JsonProperty(required = true)
            @Description("A research question that will be used to guide the research.")
            String researchBrief
    ) {
    }
}
