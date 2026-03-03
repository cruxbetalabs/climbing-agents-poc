"""Web scraping tools for external climbing data sources.

Architecture note:
  Each source has:
    search_url(query)  → URL to retrieve search results
    parse_links(html)  → extract candidate profile URLs from search HTML
    parse_data(html)   → extract structured data from a profile page

Currently implemented sources:
  - climbing_history  (https://climbing-history.org)
"""

import logging
import re
from tools.registry import registry, ToolResult

log = logging.getLogger(__name__)


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
        """Extract climber profile page URLs from a search result page."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        seen: set[str] = set()
        links: list[str] = []
        for tag in soup.find_all("a", href=re.compile(r"^/climber/\d+/")):
            # Strip fragments (#section) and normalise
            path = tag["href"].split("#")[0].rstrip("/")
            url = self.base + path
            if url not in seen:
                seen.add(url)
                links.append(url)
        return links

    def parse_data(self, html: str) -> dict:
        """Extract structured athlete data from a climber profile page."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        data: dict = {}

        # Name — h1, strip trailing page suffix like "More 1"
        h1 = soup.find("h1")
        if h1:
            raw = h1.get_text(separator=" ", strip=True)
            data["name"] = re.sub(r"\s+More\s+\d+.*", "", raw).strip()

        # Bio — the first substantial paragraph after the "Quick Info" heading
        for heading in soup.find_all(
            lambda t: t.name in ("h4", "h3", "p", "span")
            and "quick info" in t.get_text(strip=True).lower()
        ):
            parent = heading.find_parent()
            if parent:
                bio = parent.get_text(separator=" ", strip=True)
                # Only keep if there's actual content beyond the heading text
                if len(bio) > 80:
                    # Cap and clean up whitespace
                    data["bio"] = re.sub(r"\s{2,}", " ", bio)[:1200]
                    break

        # Social / external links
        social_patterns = {
            "instagram": "instagram.com",
            "youtube": "youtube.com",
            "8a_nu": "8a.nu",
            "ifsc": "ifsc.results.info",
            "wikipedia": "wikipedia.org",
        }
        social: dict[str, str] = {}
        for tag in soup.find_all("a", href=True):
            href: str = tag["href"]
            for key, pattern in social_patterns.items():
                if pattern in href and key not in social:
                    social[key] = href
        if social:
            data["social_links"] = social

        # Rankings / list memberships (e.g. "Strongest Male Sport Climbers - #1")
        rankings = []
        for tag in soup.find_all("a", href=re.compile(r"^/list/")):
            text = tag.get_text(strip=True)
            if text:
                rankings.append(text)
        if rankings:
            data["rankings"] = rankings[:10]

        return data


# Registry of available sources
_sources: dict[str, ClimberDataSource] = {
    "climbing_history": ClimbingHistorySource(),
}


async def _fetch(url: str) -> str:
    """Fetch a URL with aiohttp. Returns HTML text, or empty string on failure."""
    import aiohttp

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; climbing-agents-poc/1.0; "
            "+https://github.com/crux-beta-labs/climbing-agents-poc)"
        )
    }
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.text()
                log.warning("_fetch %s returned HTTP %s", url, resp.status)
                return ""
    except Exception as exc:
        log.warning("_fetch %s failed: %s", url, exc)
        return ""


# ─────────────────────────────────────────────
# Tool: get_climber_info
# ─────────────────────────────────────────────


@registry.register(
    schema={
        "type": "function",
        "function": {
            "name": "get_climber_info",
            "description": (
                "Look up publicly available information about a professional climber, "
                "such as their ape index (arm span), height, nationality, and competition results. "
                "Data is sourced from climbing-history.org. "
                "ALWAYS call this tool — never answer from a prior response in session history, "
                "as data may have changed. Use when the user asks about a specific climber."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Full name of the climber, e.g. 'Colin Duffy'",
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
    }
)
async def get_climber_info(name: str, source: str = "climbing_history") -> ToolResult:
    src = _sources.get(source)
    if src is None:
        return ToolResult(
            data=None, status="error", message=f"Unknown source: {source}"
        )

    # Step 1: search
    search_html = await _fetch(src.search_url(name))

    # Step 2: extract profile links
    links = src.parse_links(search_html)

    if not links:
        return ToolResult(
            data={"name": name, "source": src.name},
            status="empty",
            message=f"No climber profile found for '{name}' on {src.name}.",
        )

    # Step 3: fetch profile page and parse
    profile_html = await _fetch(links[0])
    data = src.parse_data(profile_html)
    data["name"] = name
    data["source"] = src.name
    data["profile_url"] = links[0]

    return ToolResult(data=data, status="ok" if data else "empty")
