package dev.haotangyuan.researcher.application.tool.detail;

import dev.haotangyuan.researcher.application.tool.annotation.SupervisorTool;
import dev.langchain4j.agent.tool.Tool;

/**
 * @author: haotangyuan
 */
@SupervisorTool
public class ResearchCompleteTool {
    @Tool("Tool for indicating that the research process is complete.")
    public String researchComplete() {
        return "Research process marked complete.";
    }
}
