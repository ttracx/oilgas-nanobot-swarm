"""
HTTP fetch tool — lets agents retrieve web pages, APIs, or docs.
"""

import time
import re
import httpx
from nanobot.tools.base import BaseTool, ToolResult

MAX_CONTENT_CHARS = 8000


def _strip_html(html: str) -> str:
    text = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
    text = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


class HttpFetchTool(BaseTool):
    name = "http_fetch"
    description = (
        "Fetch content from a URL — web pages, REST APIs, JSON endpoints, or docs. "
        "Returns plain text content up to 8000 characters."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch",
            },
            "method": {
                "type": "string",
                "enum": ["GET", "POST"],
                "default": "GET",
            },
            "headers": {
                "type": "object",
                "description": "Optional HTTP headers",
                "default": {},
            },
            "body": {
                "type": "string",
                "description": "Request body for POST requests",
            },
        },
        "required": ["url"],
    }

    def __init__(self, timeout: float = 60.0):
        self.timeout = timeout

    async def run(
        self,
        url: str,
        method: str = "GET",
        headers: dict | None = None,
        body: str | None = None,
        **kwargs,
    ) -> ToolResult:
        start = time.time()

        blocked_prefixes = ("file://", "ftp://")
        if any(url.startswith(p) for p in blocked_prefixes):
            return ToolResult(
                tool_name=self.name,
                success=False,
                output=f"Blocked URL scheme: {url}",
                error="blocked_scheme",
            )

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers={"User-Agent": "NeuralQuantum-Nanobot/1.0"},
            ) as client:
                if method == "POST":
                    resp = await client.post(url, content=body, headers=headers or {})
                else:
                    resp = await client.get(url, headers=headers or {})

                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")

                if "json" in content_type:
                    text = resp.text
                elif "html" in content_type:
                    text = _strip_html(resp.text)
                else:
                    text = resp.text

                truncated = len(text) > MAX_CONTENT_CHARS
                text = text[:MAX_CONTENT_CHARS]
                if truncated:
                    text += f"\n\n[Content truncated at {MAX_CONTENT_CHARS} chars]"

                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output=f"URL: {url}\nStatus: {resp.status_code}\n\n{text}",
                    raw={"status": resp.status_code, "content_type": content_type},
                    duration_seconds=time.time() - start,
                )

        except httpx.HTTPStatusError as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output=f"HTTP {e.response.status_code}: {url}",
                error=str(e),
                duration_seconds=time.time() - start,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output=f"Fetch failed: {e}",
                error=str(e),
                duration_seconds=time.time() - start,
            )
