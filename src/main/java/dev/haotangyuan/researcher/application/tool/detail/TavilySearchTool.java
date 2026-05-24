package dev.haotangyuan.researcher.application.tool.detail;

import dev.haotangyuan.researcher.application.tool.annotation.ResearcherTool;
import dev.langchain4j.agent.tool.P;
import dev.langchain4j.agent.tool.Tool;

/**
 * Tavily web search tool specification for researcher agent.
 * Actual execution is handled by SearchAgent in ResearcherAgent.action()
 * @author: haotangyuan
 */
@ResearcherTool
public class TavilySearchTool {
    
    @Tool("""
            Fetch results from Tavily search API with content summarization.
            
            Use this tool to search the web for information relevant to your research topic.
            Provide a specific, well-formed search query to get the best results.
            
            Best practices for search queries:
            - Be specific and use relevant keywords
            - Include important context or qualifiers (e.g., "2024", "latest", "comparison")
            - For factual questions, phrase as a question
            - For research topics, use descriptive phrases
            
            Examples:
            - "climate change impact on Arctic ice 2024"
            - "comparison of electric vehicle batteries lithium vs solid state"
            - "What are the latest breakthroughs in quantum computing?"
            """
    )
    public String tavilySearch(
            @P(value = "A specific search query to execute. Should be clear, focused, and relevant to the research topic.",
                    required = true)
            String query,
            @P(value = "Maximum number of results to return. Default is 3.",
                    required = false)
            Integer maxResults,
            @P(value = "Topic to filter results by: 'general', 'news', or 'finance'. Default is 'general'.",
                    required = false)
            String topic
    ) {
        return "Search delegated: " + query;
    }
}
