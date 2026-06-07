package dev.haotangyuan.researcher.application.tool.detail;

import dev.haotangyuan.researcher.application.tool.annotation.ResearcherTool;
import dev.haotangyuan.researcher.application.tool.annotation.ResearchTool;
import dev.haotangyuan.researcher.application.tool.annotation.ResearchToolParam;
import dev.haotangyuan.researcher.application.tool.annotation.SupervisorTool;

/**
 * @author: haotangyuan
 */
@ResearcherTool
@SupervisorTool
public class ThinkTool {
    @ResearchTool(name = "thinkTool", description = """
            Tool for strategic reflection on research progress and decision-making.
            
            Use this tool after each search to analyze results and plan next steps systematically.
            This creates a deliberate pause in the research workflow for quality decision-making.
        
            When to use:
            - After receiving search results: What key information did I find?
            - Before deciding next steps: Do I have enough to answer comprehensively?
            - When assessing research gaps: What specific information am I still missing?
            - Before concluding research: Can I provide a complete answer now?
        
            Reflection should address:
            1. Analysis of current findings - What concrete information have I gathered?
            2. Gap assessment - What crucial information is still missing?
            3. Quality evaluation - Do I have sufficient evidence/examples for a good answer?
            4. Strategic decision - Should I continue searching or provide my answer?
            """
    )
    public String thinkTool(
            @ResearchToolParam(
                    name = "reflection",
                    description = "Detailed reflection on progress, findings, gaps, and next steps",
                    required = true)
            String reflection
    ) {
        return "Reflection recorded: " + reflection;
    }
}
