package dev.haotangyuan.researcher.application.tool.detail;

import dev.haotangyuan.researcher.application.tool.annotation.ResearchTool;
import dev.haotangyuan.researcher.application.tool.annotation.ResearchToolParam;
import dev.haotangyuan.researcher.application.tool.annotation.SupervisorTool;

/**
 * @author: haotangyuan
 */
@SupervisorTool
public class ConductResearchTool {
    
    @ResearchTool(name = "conductResearch", description = "Tool for delegating a research task to a specialized sub-agent.")
    public String conductResearch(
            @ResearchToolParam(
                    name = "researchTopic",
                    description = "The topic to research. Should be a single topic described in high detail (at least a paragraph).",
                    required = true)
            String researchTopic
    ) {
        return "Research delegated: " + researchTopic;
    }
}
