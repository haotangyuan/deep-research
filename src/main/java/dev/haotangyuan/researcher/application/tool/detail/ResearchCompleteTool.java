package dev.haotangyuan.researcher.application.tool.detail;

import dev.haotangyuan.researcher.application.tool.annotation.ResearchTool;
import dev.haotangyuan.researcher.application.tool.annotation.SupervisorTool;

/**
 * @author: haotangyuan
 */
@SupervisorTool
public class ResearchCompleteTool {
    @ResearchTool(name = "researchComplete", description = "Tool for indicating that the research process is complete.")
    public String researchComplete() {
        return "Research process marked complete.";
    }
}
