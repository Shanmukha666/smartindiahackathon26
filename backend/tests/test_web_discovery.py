from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.scraper import ScrapedPage
from app.web_discovery import (
    DEFAULT_SEEDS_PATH,
    DiscoveryTopic,
    SourceCandidate,
    discover_candidates_for_topic,
    is_domain_allowed,
    load_topics,
    run_discovery,
)


def test_is_domain_allowed_matches_exact_and_subdomain() -> None:
    assert is_domain_allowed("https://indiacode.nic.in/handle/1", ["indiacode.nic.in"])
    assert is_domain_allowed(
        "https://www.indiacode.nic.in/handle/1", ["indiacode.nic.in"]
    )
    assert is_domain_allowed("https://sub.wipo.int/x", ["wipo.int"])
    assert not is_domain_allowed(
        "https://evil-indiacode.nic.in.attacker.com/x", ["indiacode.nic.in"]
    )
    assert not is_domain_allowed("https://example.com", ["indiacode.nic.in"])


def test_is_domain_allowed_empty_allowlist_permits_everything() -> None:
    assert is_domain_allowed("https://anything.example", [])


def test_seed_file_loads_and_every_topic_has_a_jurisdiction() -> None:
    topics = load_topics(DEFAULT_SEEDS_PATH)
    assert len(topics) >= 5
    for topic in topics:
        assert topic.jurisdiction in ("IN", "INTL")
        assert topic.allowed_domains, (
            f"{topic.name} must restrict crawling to specific domains"
        )


class FakeScraper:
    """Stands in for WebScraper: no network, deterministic link graph."""

    def __init__(
        self, link_graph: dict[str, list[str]], pages: dict[str, ScrapedPage]
    ) -> None:
        self._link_graph = link_graph
        self._pages = pages
        self.robots_checked: list[str] = []

    async def check_robots_txt(self, url: str) -> bool:
        self.robots_checked.append(url)
        return "blocked" not in url

    async def fetch_links(self, url: str) -> list[str]:
        return self._link_graph.get(url, [])

    async def scrape(self, url: str) -> ScrapedPage:
        if url not in self._pages:
            raise ValueError(f"no fake page for {url}")
        return self._pages[url]


@dataclass
class FakeStagingRepository:
    staged: dict[str, SourceCandidate] = field(default_factory=dict)
    next_id: int = 1

    async def exists_by_hash(self, source_hash: str) -> bool:
        return source_hash in self.staged

    async def insert_candidate(
        self, candidate: SourceCandidate, body_text: str, source_hash: str
    ) -> int | None:
        if source_hash in self.staged:
            return None
        self.staged[source_hash] = candidate
        staged_id = self.next_id
        self.next_id += 1
        return staged_id

    async def list_pending(self) -> list[object]:
        return []

    async def get(self, staging_id: int) -> object | None:
        return None

    async def mark_promoted(self, staging_id: int, reviewer: str) -> None:
        pass

    async def mark_rejected(self, staging_id: int, reviewer: str, reason: str) -> None:
        pass


@pytest.mark.asyncio
async def test_discover_candidates_follows_same_domain_links_only() -> None:
    topic = DiscoveryTopic(
        name="Test Act",
        jurisdiction="IN",
        allowed_domains=("gov.example",),
        start_urls=("https://gov.example/acts",),
        keywords=("act",),
    )
    scraper = FakeScraper(
        link_graph={
            "https://gov.example/acts": [
                "https://gov.example/acts/test-act-2001",
                "https://unrelated.example/spam",
            ]
        },
        pages={},
    )
    candidates = await discover_candidates_for_topic(topic, scraper)  # type: ignore[arg-type]
    urls = {candidate.url for candidate in candidates}
    assert "https://gov.example/acts" in urls
    assert "https://gov.example/acts/test-act-2001" in urls
    assert "https://unrelated.example/spam" not in urls


@pytest.mark.asyncio
async def test_run_discovery_stages_new_pages_and_skips_duplicates() -> None:
    topic = DiscoveryTopic(
        name="Test Act",
        jurisdiction="IN",
        allowed_domains=("gov.example",),
        start_urls=("https://gov.example/act",),
    )
    page = ScrapedPage(
        url="https://gov.example/act",
        title="Test Act",
        text="Section 1. ...",
        source_hash="abc123",
    )
    scraper = FakeScraper(link_graph={}, pages={"https://gov.example/act": page})
    repository = FakeStagingRepository()

    stats = await run_discovery([topic], scraper, repository)  # type: ignore[arg-type]
    assert stats.staged == 1
    assert stats.duplicate == 0

    # Re-running discovery must not create a second staging row for identical content.
    stats_again = await run_discovery([topic], scraper, repository)  # type: ignore[arg-type]
    assert stats_again.staged == 0
    assert stats_again.duplicate == 1


@pytest.mark.asyncio
async def test_run_discovery_respects_robots_txt() -> None:
    topic = DiscoveryTopic(
        name="Test Act",
        jurisdiction="IN",
        allowed_domains=("gov.example",),
        start_urls=("https://gov.example/blocked-page",),
    )
    scraper = FakeScraper(link_graph={}, pages={})
    repository = FakeStagingRepository()

    stats = await run_discovery([topic], scraper, repository)  # type: ignore[arg-type]
    assert stats.robots_blocked == 1
    assert stats.staged == 0
