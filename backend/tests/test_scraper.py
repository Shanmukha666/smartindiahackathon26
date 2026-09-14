from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.scraper import ScrapedPage, WebScraper, extract_text_from_html


def make_test_settings(**kwargs: object) -> Settings:
    defaults: dict[str, object] = {
        "app_name": "test-app",
        "database_url": SecretStr("postgresql://localhost/test"),
        "jwt_signing_key": SecretStr("test-signing-key-not-for-production"),
        "credential_kek_secret_resource": "projects/test/secrets/credential-kek/versions/latest",
        "voyage_api_url": "https://api.voyageai.com/v1/embeddings",
        "voyage_model": "voyage-3-large",
        "otel_service_name": "test-service",
        "otel_exporter_otlp_endpoint": "http://localhost:4317",
        "otel_traces_exporter": "none",
        "scrape_timeout_seconds": 5.0,
    }
    defaults.update(kwargs)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_extract_text_from_html() -> None:
    html = """
    <!DOCTYPE html>
    <html>
    <head><title>Test AYUSH Article</title></head>
    <body>
        <nav><a href="/home">Home</a></nav>
        <header><h1>Site Header</h1></header>
        <main>
            <h2>Ayurvedic Medicine Overview</h2>
            <p>Traditional Indian systems of medicine.</p>
        </main>
        <script>console.log('remove me');</script>
        <style>.hide { display: none; }</style>
        <footer>Copyright 2026</footer>
    </body>
    </html>
    """
    title, text = extract_text_from_html(html)
    assert title == "Test AYUSH Article"
    assert "Ayurvedic Medicine Overview" in text
    assert "Traditional Indian systems of medicine." in text
    assert "remove me" not in text
    assert "Site Header" not in text
    assert "Copyright 2026" not in text


@pytest.mark.asyncio
async def test_scraper_invalid_scheme() -> None:
    settings = make_test_settings()
    async with WebScraper(settings) as scraper:
        with pytest.raises(ValueError, match="Invalid URL scheme"):
            await scraper.scrape("ftp://example.com/doc")


@pytest.mark.asyncio
async def test_scraper_success() -> None:
    settings = make_test_settings()

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://example.com/ayurveda"
        html = "<html><head><title>Ayurveda Law</title></head><body><p>Section 3(p) details</p></body></html>"
        return httpx.Response(200, text=html, headers={"Content-Type": "text/html"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        scraper = WebScraper(settings, client=client)
        page = await scraper.scrape("https://example.com/ayurveda")

    assert isinstance(page, ScrapedPage)
    assert page.title == "Ayurveda Law"
    assert "Section 3(p) details" in page.text
    assert len(page.source_hash) == 64


@pytest.mark.asyncio
async def test_check_robots_txt() -> None:
    settings = make_test_settings()

    def handler(request: httpx.Request) -> httpx.Response:
        if "/robots.txt" in str(request.url):
            content = "User-agent: *\nDisallow: /private/\nDisallow: /admin\n"
            return httpx.Response(200, text=content)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        scraper = WebScraper(settings, client=client)
        assert await scraper.check_robots_txt("https://example.com/public/doc") is True
        assert await scraper.check_robots_txt("https://example.com/private/doc") is False


@pytest.mark.asyncio
async def test_scraper_pdf_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_test_settings()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-1.4 dummy", headers={"Content-Type": "application/pdf"})

    import app.file_extract as file_extract_mod
    monkeypatch.setattr(file_extract_mod, "extract_text", lambda data, filename, content_type=None: "Extracted PDF content for AYUSH patent.")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        scraper = WebScraper(settings, client=client)
        page = await scraper.scrape("https://example.com/document.pdf")

    assert "Extracted PDF content" in page.text
    assert page.title == "Document"

