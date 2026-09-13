"""Automated discovery of candidate legal-corpus sources.

This module NEVER writes to the trusted, retrievable corpus (`corpus_documents`). It
only ever produces `corpus_staging` rows with status='pending_review'. Promotion into
the retrievable corpus is a separate, `legal_reviewer`-gated action taken through
`/admin/corpus-staging/{id}/promote`, mirroring the PR-review model described in
docs/corpus-governance.md. Treat everything here as "found a lead", not "verified law".

Two discovery strategies compose:
  1. Seed crawl (zero-config): start from a short list of manually verified official
     domains/pages (discovery_seeds.yaml), follow same-domain links, and keep only
     pages inside the topic's allowed domains.
  2. Search provider (optional): a pluggable live web-search API (e.g. Brave Search)
     for open-ended queries beyond the seed list. Off by default; enable by
     configuring an API key. Every result is still filtered by the topic's domain
     allowlist and still lands in the same pending-review staging table.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlparse

import httpx
import yaml

from .observability import outbound_headers, stage
from .scraper import WebScraper

DEFAULT_SEEDS_PATH = Path(__file__).with_name("discovery_seeds.yaml")
MAX_LINKS_PER_START_URL = 25
DEFAULT_MAX_CANDIDATES_PER_TOPIC = 8


@dataclass(frozen=True)
class DiscoveryTopic:
    name: str
    jurisdiction: Literal["IN", "INTL"]
    allowed_domains: tuple[str, ...] = ()
    start_urls: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceCandidate:
    url: str
    title: str
    topic: str
    jurisdiction: Literal["IN", "INTL"]
    discovered_via: Literal["seed_start_url", "seed_crawl", "search_provider"]


@dataclass(frozen=True)
class StagedCandidate:
    id: int
    url: str
    title: str
    topic: str
    jurisdiction: Literal["IN", "INTL"]
    body_text: str
    source_hash: str
    status: Literal["pending_review", "promoted", "rejected"]


@dataclass
class DiscoveryStats:
    candidates_found: int = 0
    staged: int = 0
    duplicate: int = 0
    robots_blocked: int = 0
    fetch_failed: int = 0
    empty: int = 0


class SearchProvider(Protocol):
    async def search(self, query: str, count: int) -> list[tuple[str, str]]:
        """Return (url, title) pairs. Implementations must not raise for zero results."""
        ...


class BraveSearchProvider:
    """Optional live web-search adapter. Swap for another provider by implementing
    SearchProvider; nothing else in this module depends on Brave specifically.
    """

    def __init__(self, api_key: str, client: httpx.AsyncClient) -> None:
        self._api_key = api_key
        self._client = client

    async def search(self, query: str, count: int) -> list[tuple[str, str]]:
        with stage("discovery.search", provider="brave"):
            response = await self._client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers=outbound_headers(
                    {"X-Subscription-Token": self._api_key, "Accept": "application/json"}
                ),
                params={"q": query, "count": str(count)},
            )
            response.raise_for_status()
        results = response.json().get("web", {}).get("results", [])
        return [
            (str(item["url"]), str(item.get("title") or item["url"]))
            for item in results
            if "url" in item
        ]


def load_topics(path: Path = DEFAULT_SEEDS_PATH) -> list[DiscoveryTopic]:
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    topics: list[DiscoveryTopic] = []
    for entry in raw.get("topics", []):
        topics.append(
            DiscoveryTopic(
                name=entry["name"],
                jurisdiction=entry["jurisdiction"],
                allowed_domains=tuple(entry.get("allowed_domains", [])),
                start_urls=tuple(entry.get("start_urls", [])),
                keywords=tuple(entry.get("keywords", [])),
            )
        )
    return topics


def _domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host.removeprefix("www.")


def is_domain_allowed(url: str, allowed_domains: Sequence[str]) -> bool:
    """Empty allowlist means "no domain restriction"; callers should avoid that for
    anything but a fully manual, single-URL request."""
    if not allowed_domains:
        return True
    domain = _domain(url)
    return any(
        domain == allowed.lower() or domain.endswith(f".{allowed.lower()}")
        for allowed in allowed_domains
    )


def _looks_relevant(url: str, keywords: Sequence[str]) -> bool:
    if not keywords:
        return True
    haystack = url.lower()
    return any(keyword.lower().split()[0] in haystack for keyword in keywords)


async def discover_candidates_for_topic(
    topic: DiscoveryTopic,
    scraper: WebScraper,
    search_provider: SearchProvider | None = None,
    max_candidates: int = DEFAULT_MAX_CANDIDATES_PER_TOPIC,
) -> list[SourceCandidate]:
    """Find candidate URLs for one topic. Does not fetch full page bodies yet."""
    candidates: dict[str, SourceCandidate] = {}

    for start_url in topic.start_urls:
        if len(candidates) >= max_candidates:
            break
        if not is_domain_allowed(start_url, topic.allowed_domains):
            continue
        candidates[start_url] = SourceCandidate(
            url=start_url,
            title=topic.name,
            topic=topic.name,
            jurisdiction=topic.jurisdiction,
            discovered_via="seed_start_url",
        )
        if not await scraper.check_robots_txt(start_url):
            continue
        for link in (await scraper.fetch_links(start_url))[:MAX_LINKS_PER_START_URL]:
            if len(candidates) >= max_candidates:
                break
            if link in candidates or not is_domain_allowed(link, topic.allowed_domains):
                continue
            if not _looks_relevant(link, topic.keywords):
                continue
            candidates[link] = SourceCandidate(
                url=link,
                title=link,
                topic=topic.name,
                jurisdiction=topic.jurisdiction,
                discovered_via="seed_crawl",
            )

    if search_provider is not None and len(candidates) < max_candidates:
        for keyword in topic.keywords or (topic.name,):
            if len(candidates) >= max_candidates:
                break
            for url, title in await search_provider.search(
                f"{keyword} official text", max_candidates
            ):
                if len(candidates) >= max_candidates:
                    break
                if url in candidates or not is_domain_allowed(url, topic.allowed_domains):
                    continue
                candidates[url] = SourceCandidate(
                    url=url,
                    title=title,
                    topic=topic.name,
                    jurisdiction=topic.jurisdiction,
                    discovered_via="search_provider",
                )

    return list(candidates.values())[:max_candidates]


class StagingRepository(Protocol):
    async def exists_by_hash(self, source_hash: str) -> bool: ...

    async def insert_candidate(
        self, candidate: SourceCandidate, body_text: str, source_hash: str
    ) -> int | None: ...

    async def list_pending(self) -> list[StagedCandidate]: ...

    async def get(self, staging_id: int) -> StagedCandidate | None: ...

    async def mark_promoted(self, staging_id: int, reviewer: str) -> None: ...

    async def mark_rejected(
        self, staging_id: int, reviewer: str, reason: str
    ) -> None: ...


class AsyncpgStagingRepository:
    """Backs StagingRepository with the same asyncpg pool the rest of the app uses."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def exists_by_hash(self, source_hash: str) -> bool:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT 1 FROM corpus_staging WHERE source_hash = $1
                UNION ALL
                SELECT 1 FROM corpus_documents WHERE source_hash = $1
                LIMIT 1
                """,
                source_hash,
            )
        return row is not None

    async def insert_candidate(
        self, candidate: SourceCandidate, body_text: str, source_hash: str
    ) -> int | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO corpus_staging
                    (url, domain, title, topic, jurisdiction, body_text,
                     source_hash, discovered_via, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'pending_review')
                ON CONFLICT (source_hash) DO NOTHING
                RETURNING id
                """,
                candidate.url,
                _domain(candidate.url),
                candidate.title[:512],
                candidate.topic,
                candidate.jurisdiction,
                body_text,
                source_hash,
                candidate.discovered_via,
            )
        return int(row["id"]) if row is not None else None

    async def list_pending(self) -> list[StagedCandidate]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT id, url, title, topic, jurisdiction, body_text, source_hash, status
                FROM corpus_staging WHERE status = 'pending_review' ORDER BY id
                """
            )
        return [self._row_to_candidate(row) for row in rows]

    async def get(self, staging_id: int) -> StagedCandidate | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT id, url, title, topic, jurisdiction, body_text, source_hash, status
                FROM corpus_staging WHERE id = $1
                """,
                staging_id,
            )
        return self._row_to_candidate(row) if row is not None else None

    async def mark_promoted(self, staging_id: int, reviewer: str) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                "UPDATE corpus_staging SET status='promoted', reviewed_by=$2, "
                "reviewed_at=CURRENT_TIMESTAMP WHERE id=$1",
                staging_id,
                reviewer,
            )

    async def mark_rejected(
        self, staging_id: int, reviewer: str, reason: str
    ) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                "UPDATE corpus_staging SET status='rejected', reviewed_by=$2, "
                "reviewed_at=CURRENT_TIMESTAMP, rejection_reason=$3 WHERE id=$1",
                staging_id,
                reviewer,
                reason,
            )

    @staticmethod
    def _row_to_candidate(row: Any) -> StagedCandidate:
        return StagedCandidate(
            id=row["id"],
            url=row["url"],
            title=row["title"],
            topic=row["topic"],
            jurisdiction=row["jurisdiction"],
            body_text=row["body_text"],
            source_hash=row["source_hash"],
            status=row["status"],
        )


async def run_discovery(
    topics: Sequence[DiscoveryTopic],
    scraper: WebScraper,
    repository: StagingRepository,
    search_provider: SearchProvider | None = None,
    max_candidates_per_topic: int = DEFAULT_MAX_CANDIDATES_PER_TOPIC,
) -> DiscoveryStats:
    stats = DiscoveryStats()
    for topic in topics:
        candidates = await discover_candidates_for_topic(
            topic, scraper, search_provider, max_candidates_per_topic
        )
        for candidate in candidates:
            stats.candidates_found += 1
            if not await scraper.check_robots_txt(candidate.url):
                stats.robots_blocked += 1
                continue
            try:
                scraped = await scraper.scrape(candidate.url)
            except (httpx.HTTPError, ValueError):
                stats.fetch_failed += 1
                continue
            if not scraped.text.strip():
                stats.empty += 1
                continue
            if await repository.exists_by_hash(scraped.source_hash):
                stats.duplicate += 1
                continue
            new_id = await repository.insert_candidate(
                candidate, scraped.text, scraped.source_hash
            )
            if new_id is None:
                stats.duplicate += 1
            else:
                stats.staged += 1
    return stats
