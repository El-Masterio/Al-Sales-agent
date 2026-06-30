"""
app/services/scraper_service.py
===============================
Web scraping service using Playwright for company websites and (optionally,
behind a residential proxy) LinkedIn company pages.

Design notes:
  - Headless browser scraping is used over plain HTTP requests because most
    modern marketing sites are JS-rendered (React/Next.js/Vue).
  - Rate limiting is enforced per-domain via the Redis RateLimiter.
  - All scraping respects robots.txt by default (checked before navigation).
  - LinkedIn scraping is gated behind FEATURE_LINKEDIN_SCRAPING because it
    requires a compliant proxy/account strategy — disabled by default.
"""

from __future__ import annotations

import re
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import structlog
import tldextract
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from playwright.async_api import Browser, Page, async_playwright
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.redis import RateLimiter, get_rate_limiter

logger = structlog.get_logger(__name__)

_ua = UserAgent()


@dataclass
class ScrapedPage:
    url: str
    title: str
    text_content: str
    html: str
    links: list[str]


class ScraperService:
    """
    Async context-manager wrapper around a Playwright browser instance.

    Usage:
        async with ScraperService() as scraper:
            page = await scraper.scrape_url("https://example.com")
    """

    def __init__(self) -> None:
        self._playwright = None
        self._browser: Browser | None = None
        self._rate_limiter: RateLimiter | None = None

    async def __aenter__(self) -> ScraperService:
        self._playwright = await async_playwright().start()
        launch_kwargs: dict = {"headless": settings.PLAYWRIGHT_HEADLESS}
        if settings.PLAYWRIGHT_SLOW_MO:
            launch_kwargs["slow_mo"] = settings.PLAYWRIGHT_SLOW_MO
        if settings.SCRAPER_PROXY_URL:
            launch_kwargs["proxy"] = {"server": settings.SCRAPER_PROXY_URL}
        self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        self._rate_limiter = get_rate_limiter()
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    # ── Robots.txt compliance ─────────────────────────────────────────────────

    async def _is_allowed_by_robots(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(robots_url)
            rp.read()
            return rp.can_fetch("*", url)
        except Exception:
            # If robots.txt is unreachable or malformed, default to allow
            # (matches standard practice for most scraping frameworks)
            return True

    # ── Rate limiting ─────────────────────────────────────────────────────────

    async def _check_rate_limit(self, url: str) -> bool:
        domain = tldextract.extract(url).registered_domain
        return await self._rate_limiter.is_allowed(
            "scrape_domain",
            domain,
            limit=int(settings.SCRAPER_RATE_LIMIT_RPS * 60),
            window_seconds=60,
        )

    # ── Core scraping ─────────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=15))
    async def scrape_url(self, url: str) -> ScrapedPage | None:
        if not await self._is_allowed_by_robots(url):
            logger.warning("scrape_blocked_by_robots", url=url)
            return None

        if not await self._check_rate_limit(url):
            logger.warning("scrape_rate_limited", url=url)
            return None

        if self._browser is None:
            raise RuntimeError("ScraperService must be used as an async context manager")

        page: Page = await self._browser.new_page(user_agent=_ua.random)
        try:
            await page.goto(url, timeout=settings.SCRAPER_TIMEOUT * 1000, wait_until="networkidle")
            html = await page.content()
            title = await page.title()
        finally:
            await page.close()

        soup = BeautifulSoup(html, "lxml")

        # Strip non-content elements before extracting text
        for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
            tag.decompose()

        text_content = re.sub(r"\n{3,}", "\n\n", soup.get_text(separator="\n", strip=True))

        links = []
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            absolute = urljoin(url, href)
            if urlparse(absolute).netloc == urlparse(url).netloc:
                links.append(absolute)

        return ScrapedPage(
            url=url,
            title=title,
            text_content=text_content[:50_000],   # cap to avoid runaway token costs
            html=html[:200_000],
            links=list(set(links))[:100],
        )

    async def scrape_company_site(self, base_url: str, max_pages: int = 5) -> str:
        """
        Scrape a company's homepage plus a few likely-relevant subpages
        (about, products, pricing, careers — useful for company size signals).
        Returns concatenated text content for the research agent.
        """
        homepage = await self.scrape_url(base_url)
        if homepage is None:
            return ""

        relevant_keywords = ["about", "product", "pricing", "careers", "team", "blog"]
        candidate_links = [
            link for link in homepage.links
            if any(kw in link.lower() for kw in relevant_keywords)
        ][: max_pages - 1]

        all_content = [f"=== {homepage.title} ({homepage.url}) ===\n{homepage.text_content}"]

        for link in candidate_links:
            sub_page = await self.scrape_url(link)
            if sub_page:
                all_content.append(f"=== {sub_page.title} ({sub_page.url}) ===\n{sub_page.text_content}")

        return "\n\n".join(all_content)

    # ── Technology detection (basic signature matching) ───────────────────────

    TECH_SIGNATURES: dict[str, list[str]] = {
        "React": ["__NEXT_DATA__", "react-dom", "data-reactroot"],
        "Next.js": ["__NEXT_DATA__", "_next/static"],
        "Vue.js": ["__vue__", "vue.js", "v-app"],
        "WordPress": ["wp-content", "wp-includes"],
        "Shopify": ["cdn.shopify.com", "Shopify.theme"],
        "HubSpot": ["js.hs-scripts.com", "hubspot"],
        "Salesforce": ["force.com", "salesforce.com"],
        "Stripe": ["js.stripe.com", "stripe.com/v3"],
        "Intercom": ["widget.intercom.io"],
        "Segment": ["cdn.segment.com"],
        "Google Analytics": ["google-analytics.com", "gtag("],
        "Webflow": ["webflow.com", "wf-page"],
    }

    def detect_tech_stack(self, html: str) -> list[str]:
        detected = []
        for tech, signatures in self.TECH_SIGNATURES.items():
            if any(sig in html for sig in signatures):
                detected.append(tech)
        return detected
