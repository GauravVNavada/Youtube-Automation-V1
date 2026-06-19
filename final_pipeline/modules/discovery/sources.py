from __future__ import annotations

from dataclasses import dataclass
import html
import json
import re
import urllib.parse
import urllib.request


USER_AGENT = "DesktopAppPlaygroundGrowth/0.1 (no-key research; local app)"


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str


def search_duckduckgo(query: str, max_results: int = 5, timeout: float = 8.0) -> list[SearchResult]:
    params = urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(
        f"https://html.duckduckgo.com/html/?{params}",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
    return _parse_duckduckgo_html(body, max_results)


def search_reddit(query: str, max_results: int = 5, timeout: float = 8.0) -> list[SearchResult]:
    params = urllib.parse.urlencode({"q": query, "sort": "relevance", "t": "year", "limit": max_results})
    request = urllib.request.Request(
        f"https://www.reddit.com/search.json?{params}",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace"))
    results: list[SearchResult] = []
    for child in data.get("data", {}).get("children", [])[:max_results]:
        item = child.get("data", {})
        title = _clean_text(item.get("title", ""))
        if not title:
            continue
        permalink = str(item.get("permalink") or "")
        url = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else str(item.get("url") or "")
        snippet = _clean_text(item.get("selftext", ""))[:280] or str(item.get("subreddit_name_prefixed") or "reddit")
        results.append(SearchResult(title=title, url=url, snippet=snippet, source="reddit"))
    return results


def search_wikimedia(query: str, max_results: int = 5, timeout: float = 8.0) -> list[SearchResult]:
    params = urllib.parse.urlencode(
        {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": query,
            "srlimit": max_results,
            "srprop": "snippet",
        }
    )
    request = urllib.request.Request(
        f"https://en.wikipedia.org/w/api.php?{params}",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace"))
    results: list[SearchResult] = []
    for item in data.get("query", {}).get("search", [])[:max_results]:
        title = _clean_text(item.get("title", ""))
        if not title:
            continue
        url = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
        results.append(SearchResult(title=title, url=url, snippet=_clean_text(item.get("snippet", "")), source="wikipedia"))
    return results


def _parse_duckduckgo_html(body: str, max_results: int) -> list[SearchResult]:
    results: list[SearchResult] = []
    blocks = re.findall(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>(.*?)(?=<a[^>]+class="result__a"|$)',
        body,
        re.S,
    )
    for raw_url, raw_title, tail in blocks[:max_results]:
        title = _clean_text(raw_title)
        if not title:
            continue
        snippet_match = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', tail, re.S)
        snippet = _clean_text(snippet_match.group(1)) if snippet_match else ""
        results.append(SearchResult(title=title, url=_decode_duckduckgo_url(raw_url), snippet=snippet, source="duckduckgo"))
    return results


def _decode_duckduckgo_url(value: str) -> str:
    unescaped = html.unescape(value)
    parsed = urllib.parse.urlparse(unescaped)
    redirect = urllib.parse.parse_qs(parsed.query).get("uddg", [""])[0]
    return urllib.parse.unquote(redirect) if redirect else unescaped


def _clean_text(value: str) -> str:
    if not value:
        return ""
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value)))
    return " ".join(text.split())
