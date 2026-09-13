"""Web scraping and HTML text extraction utilities for knowledge base ingestion."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from .observability import outbound_headers, stage

if TYPE_CHECKING:
    from .config import Settings

DEFAULT_USER_AGENT = "IP-SAKTI-Sahayak/0.1.0 (WebScraper; +https://ip-sakti.gov.in)"
TAGS_TO_REMOVE = ("script", "style", "nav", "header", "footer", "aside")


@dataclass(frozen=True)
class ScrapedPage:
    """Represents a scraped web page with extracted clean text and integrity hash."""

    url: str
    title: str
    text: str
    source_hash: str


def extract_text_from_html(html: str) -> tuple[str, str]:
    """Extract page title and clean text from raw HTML using BeautifulSoup (lxml parser).

    Removes script, style, nav, header, footer, and aside tags before extracting text.
    Returns a tuple of (title, clean_text).
    """
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(strip=True) if soup.title is not None else ""
    for tag in soup.find_all(TAGS_TO_REMOVE):
        tag.decompose()
    clean_text = soup.get_text(separator="\n", strip=True)
    return title, clean_text


class WebScraper:
    """Web scraper for retrieving and parsing external web pages with robots.txt checks."""

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self._settings = settings
        self._timeout = float(getattr(settings, "scrape_timeout_seconds", 30.0))
        self._client = client
        self._owns_client = client is None
        self._user_agent = user_agent

    async def __aenter__(self) -> Self:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def scrape(self, url: str) -> ScrapedPage:
        """Fetch the URL, validate scheme, and extract clean text and metadata."""
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Invalid URL scheme '{parsed.scheme}': only http and https are supported")

        with stage("scrape", url=url):
            headers = outbound_headers({"User-Agent": self._user_agent})
            if self._client is not None:
                response = await self._client.get(url, headers=headers, follow_redirects=True)
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.get(url, headers=headers, follow_redirects=True)
            response.raise_for_status()

            title, clean_text = extract_text_from_html(response.text)
            source_hash = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()
            return ScrapedPage(
                url=url,
                title=title,
                text=clean_text,
                source_hash=source_hash,
            )

    async def check_robots_txt(self, url: str) -> bool:
        """Check whether robots.txt on the domain allows scraping the URL path for User-agent: *.

        Returns True if allowed, False if disallowed. Defaults to True on any error.
        """
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                return True

            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            headers = outbound_headers({"User-Agent": self._user_agent})

            if self._client is not None:
                response = await self._client.get(robots_url, headers=headers, follow_redirects=True)
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.get(robots_url, headers=headers, follow_redirects=True)

            if response.status_code != 200:
                return True

            path = parsed.path or "/"
            return self._is_path_allowed_by_robots(response.text, path)
        except (httpx.HTTPError, ValueError):
            return True

    @staticmethod
    def _is_path_allowed_by_robots(robots_txt: str, path: str) -> bool:
        """Parse robots.txt content and check if User-agent: * disallows the given path."""
        normalized_path = path if path.startswith("/") else f"/{path}"
        current_agents: list[str] = []
        has_rules = False

        for raw_line in robots_txt.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            directive, _, value = line.partition(":")
            directive = directive.strip().lower()
            value = value.strip()

            if directive == "user-agent":
                if has_rules:
                    current_agents = []
                    has_rules = False
                current_agents.append(value.lower())
            elif directive == "disallow":
                has_rules = True
                if "*" in current_agents and value and normalized_path.startswith(value):
                    return False

        return True
