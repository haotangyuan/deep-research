from __future__ import annotations

from .runtime import ResearchToolParameter, ResearchToolSpec


THINK_TOOL = ResearchToolSpec(
    name="thinkTool",
    description="""Tool for strategic reflection on research progress and decision-making.

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
""",
    parameters=[
        ResearchToolParameter(
            name="reflection",
            description="Detailed reflection on progress, findings, gaps, and next steps",
            required=True,
            type="string",
        ),
    ],
)

TAVILY_SEARCH_TOOL = ResearchToolSpec(
    name="tavilySearch",
    description="""Fetch results from Tavily search API with content summarization.

Use this tool to search the web for information relevant to your research topic.
Provide a specific, well-formed search query to get the best results.
""",
    parameters=[
        ResearchToolParameter("query", "A specific search query to execute.", True, "string"),
        ResearchToolParameter("maxResults", "Maximum number of results to return. Default is 3.", False, "integer"),
        ResearchToolParameter("topic", "Topic: general, news, or finance. Default is general.", False, "string"),
    ],
)

CONDUCT_RESEARCH_TOOL = ResearchToolSpec(
    name="conductResearch",
    description="Tool for delegating a research task to a specialized sub-agent.",
    parameters=[
        ResearchToolParameter(
            "researchTopic",
            "The topic to research. Should be a single topic described in high detail.",
            True,
            "string",
        ),
    ],
)

RESEARCH_COMPLETE_TOOL = ResearchToolSpec(
    name="researchComplete",
    description="Tool for indicating that the research process is complete.",
    parameters=[],
)

RESEARCHER_STAGE_TOOLS = [THINK_TOOL, TAVILY_SEARCH_TOOL]
SUPERVISOR_STAGE_TOOLS = [THINK_TOOL, CONDUCT_RESEARCH_TOOL, RESEARCH_COMPLETE_TOOL]


async def execute_simple_tool(tool_name: str, arguments: dict) -> str:
    if tool_name == "thinkTool":
        return "Reflection recorded: " + str(arguments.get("reflection") or "")
    if tool_name == "conductResearch":
        return "Research delegated: " + str(arguments.get("researchTopic") or "")
    if tool_name == "researchComplete":
        return "Research process marked complete."
    if tool_name == "tavilySearch":
        return "Search delegated: " + str(arguments.get("query") or "")
    return ""
