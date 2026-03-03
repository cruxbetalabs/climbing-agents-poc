"""
Web scraping tools for external climbing data sources.

Architecture note:
  Each source has:
    search_url(query)  → URL to retrieve search results
    parse_links(html)  → extract candidate profile URLs from search HTML
    parse_data(html)   → extract structured data from a profile page

Currently implemented sources:
  - climbing_history  (https://climbing-history.org)

All network calls are currently NO-OP stubs returning mock data.
Replace the _fetch() call per tool to enable real scraping.
"""

import re
from tools.registry import registry, ToolResult


# ─────────────────────────────────────────────
# Generic pipeline abstraction
# ─────────────────────────────────────────────

class ClimberDataSource:
    name: str = ""

    def search_url(self, query: str) -> str:
        raise NotImplementedError

    def parse_links(self, html: str) -> list[str]:
        """Return candidate profile page URLs from search result HTML."""
        raise NotImplementedError

    def parse_data(self, html: str) -> dict:
        """Extract structured athlete data from a profile page."""
        raise NotImplementedError


class ClimbingHistorySource(ClimberDataSource):
    name = "climbing-history.org"
    base = "https://climbing-history.org"

    def search_url(self, query: str) -> str:
        from urllib.parse import quote
        return f"{self.base}/search?q={quote(query)}"

    def parse_links(self, html: str) -> list[str]:
        # Real impl: BeautifulSoup to find /climber/<id>/<slug> hrefs
        # Stub: return empty
        return []

    def parse_data(self, html: str) -> dict:
        # Real impl: parse ape index, height, weight, nationality, etc.
        # Stub: return empty
        return {}


# Registry of available sources
_sources: dict[str, ClimberDataSource] = {
    "climbing_history": ClimbingHistorySource(),
}


async def _fetch(url: str) -> str:
    """
    NO-OP stub. Replace with real HTTP fetch:
        async with aiohttp.ClientSession() as s:
            async with s.get(url) as r:
                return await r.text()
    """
    return ""


# ─────────────────────────────────────────────
# Tool: get_climber_info
# ─────────────────────────────────────────────

@registry.register(schema={
    "type": "function",
    "function": {
        "name": "get_climber_info",
        "description": (
            "Look up publicly available information about a professional climber, "
            "such as their ape index (arm span), height, nationality, and competition results. "
            "Data is sourced from climbing-history.org. "
            "Use this when the user asks 'how much does X climber span' or similar."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Full name of the climber, e.g. 'Colin Duffy'"
                },
                "source": {
                    "type": "string",
                    "enum": ["climbing_history"],
                    "description": "Data source to use. Default: climbing_history",
                },
            },
            "required": ["name"],
        },
    },
})
async def get_climber_info(name: str, source: str = "climbing_history") -> ToolResult:
    src = _sources.get(source)
    if src is None:
        return ToolResult(data=None, status="error", message=f"Unknown source: {source}")

    # Step 1: search
    search_html = await _fetch(src.search_url(name))

    # Step 2: extract profile links
    links = src.parse_links(search_html)

    if not links:
        # --- NO-OP MOCK DATA (until fetch is implemented) ---
        mock = {
            "name": name,
            "source": src.name,
            "note": "Live scraping not yet enabled. This is mock data.",
            "ape_index": "unknown",
            "height_cm": "unknown",
            "nationality": "unknown",
        }
        return ToolResult(data=mock, status="ok", message=f"Mock data for {name}.")

    # Step 3: fetch profile page and parse
    profile_html = await _fetch(links[0])
    data = src.parse_data(profile_html)
    data["name"] = name
    data["source"] = src.name
    data["profile_url"] = links[0]

    return ToolResult(data=data, status="ok" if data else "empty")
