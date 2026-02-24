"""
Web search tool using DuckDuckGo Instant Answer API.
No API key required.
"""

import time
import httpx
from nanobot.tools.base import BaseTool, ToolResult


class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "Search the web for current information, facts, documentation, or news. "
        "Use when you need information beyond your training data."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to look up",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (1-10)",
                "default": 5,
            },
        },
        "required": ["query"],
    }

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout

    async def run(self, query: str, max_results: int = 5, **kwargs) -> ToolResult:
        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    "https://api.duckduckgo.com/",
                    params={
                        "q": query,
                        "format": "json",
                        "no_html": "1",
                        "skip_disambig": "1",
                    },
                )
                response.raise_for_status()
                data = response.json()

            results = []

            if data.get("Abstract"):
                results.append(
                    f"SUMMARY: {data['Abstract']}\nSOURCE: {data.get('AbstractURL', '')}"
                )

            for topic in data.get("RelatedTopics", [])[:max_results]:
                if isinstance(topic, dict) and topic.get("Text"):
                    results.append(f"- {topic['Text']}")
                    if len(results) >= max_results:
                        break

            if data.get("Infobox"):
                box = data["Infobox"]
                if box.get("content"):
                    facts = [
                        f"{item.get('label', '')}: {item.get('value', '')}"
                        for item in box["content"][:5]
                        if item.get("label") and item.get("value")
                    ]
                    if facts:
                        results.append("KEY FACTS:\n" + "\n".join(facts))

            if not results:
                output = f"No results found for: '{query}'"
            else:
                output = f"Search results for '{query}':\n\n" + "\n\n".join(results)

            return ToolResult(
                tool_name=self.name,
                success=True,
                output=output,
                raw=data,
                duration_seconds=time.time() - start,
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output=f"Search failed: {e}",
                error=str(e),
                duration_seconds=time.time() - start,
            )
