"""Web page scraping and text extraction."""

import asyncio
import ipaddress
import socket

import httpx
import structlog
import trafilatura

from shared.schemas.pipeline import Source

logger = structlog.get_logger()

_ALLOWED_SCHEMES = {"http", "https"}


def _is_safe_url(url: str) -> bool:
    """Return False for URLs that resolve to private/internal IP ranges (SSRF protection).

    Blocks: loopback (127.x, ::1), RFC-1918 private ranges, link-local (169.254.x),
    and any URL with a non-http/https scheme.
    """
    try:
        parsed = httpx.URL(url)
        if parsed.scheme not in _ALLOWED_SCHEMES:
            return False
        hostname = parsed.host
        if not hostname:
            return False
        # Resolve all A/AAAA records and check each one
        addr_infos = socket.getaddrinfo(hostname, None)
        for addr_info in addr_infos:
            ip = ipaddress.ip_address(addr_info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        return True
    except Exception:
        return False


class WebScraper:
    """Scrapes web pages and extracts clean article text.

    Uses trafilatura for content extraction — it handles boilerplate removal,
    article detection, and produces clean text from HTML.
    """

    def __init__(self, timeout: float = 15.0, max_concurrent: int = 5) -> None:
        self._timeout = timeout
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def scrape_sources(self, sources: list[Source]) -> list[Source]:
        """Scrape full text for sources that don't have it yet.

        Modifies sources in-place and returns the updated list.
        """
        tasks = []
        for source in sources:
            if not source.full_text and source.url:
                tasks.append(self._scrape_single(source))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        scraped_count = sum(1 for s in sources if s.full_text)
        logger.info("scraping_complete", total=len(sources), scraped=scraped_count)
        return sources

    async def _scrape_single(self, source: Source) -> None:
        """Scrape a single source URL and update its full_text."""
        async with self._semaphore:
            # SEC-001: SSRF protection — skip internal/private URLs
            if not _is_safe_url(source.url):
                logger.warning("ssrf_blocked", url=source.url[:80])
                return

            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout,
                    follow_redirects=True,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36"
                        )
                    },
                ) as client:
                    response = await client.get(source.url)
                    response.raise_for_status()

                    # Extract clean text using trafilatura
                    text = trafilatura.extract(
                        response.text,
                        include_comments=False,
                        include_tables=True,
                        no_fallback=False,
                    )

                    if text:
                        source.full_text = text
                        logger.debug("scraped_source", url=source.url[:80], chars=len(text))
                    else:
                        logger.warning("no_content_extracted", url=source.url[:80])

            except Exception as e:
                logger.warning("scrape_failed", url=source.url[:80], error=str(e))
