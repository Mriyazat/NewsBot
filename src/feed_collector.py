"""
Feed Collector - Fetches and parses RSS/Atom feeds from all configured sources.

Handles:
- Direct RSS/Atom feeds (government, think tanks)
- Google News RSS feeds (keyword-based queries)
- LinkedIn RSS.app feeds (optional)
- Graceful error handling for unavailable feeds
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote_plus

import feedparser
import requests
import yaml

logger = logging.getLogger(__name__)

# Timeout for feed requests (seconds)
REQUEST_TIMEOUT = 15

# User-Agent to avoid being blocked by some feeds
USER_AGENT = (
    "Mozilla/5.0 (compatible; NewsBot/1.0; "
    "+https://github.com/Mriyazat/NewsBot-)"
)


class Article:
    """Represents a single news article collected from a feed."""

    def __init__(
        self,
        title: str,
        link: str,
        description: str,
        published: Optional[datetime],
        source_name: str,
        source_category: str,
    ):
        self.title = title.strip() if title else ""
        self.link = link.strip() if link else ""
        self.description = description.strip() if description else ""
        self.published = published
        self.source_name = source_name
        self.source_category = source_category

    @property
    def published_str(self) -> str:
        """Human-readable published date."""
        if self.published:
            return self.published.strftime("%b %d, %Y")
        return "Unknown date"

    def __repr__(self) -> str:
        return f"Article(title='{self.title[:50]}...', source='{self.source_name}')"


class FeedCollector:
    """Collects articles from all configured RSS feed sources."""

    def __init__(self, sources_path: str = "config/sources.yaml"):
        self.sources_path = sources_path
        self.sources = self._load_sources()

    def _load_sources(self) -> dict:
        """Load feed sources from YAML config."""
        try:
            with open(self.sources_path, "r") as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            logger.error(f"Sources config not found: {self.sources_path}")
            return {}

    def _parse_feed(self, feed_url: str) -> feedparser.FeedParserDict:
        """Fetch and parse a single RSS/Atom feed."""
        try:
            response = requests.get(
                feed_url,
                timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": USER_AGENT},
                verify=True,
            )
            response.raise_for_status()
            return feedparser.parse(response.content)
        except requests.exceptions.SSLError:
            # Some government sites have SSL issues; retry without verify
            logger.warning(f"SSL error for {feed_url}, retrying without verification")
            try:
                response = requests.get(
                    feed_url,
                    timeout=REQUEST_TIMEOUT,
                    headers={"User-Agent": USER_AGENT},
                    verify=False,
                )
                response.raise_for_status()
                return feedparser.parse(response.content)
            except requests.RequestException as e:
                logger.warning(f"Failed to fetch feed {feed_url}: {e}")
                return feedparser.FeedParserDict()
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch feed {feed_url}: {e}")
            return feedparser.FeedParserDict()

    def _parse_date(self, entry: dict) -> Optional[datetime]:
        """Extract published date from a feed entry."""
        date_fields = ["published_parsed", "updated_parsed", "created_parsed"]
        for field in date_fields:
            parsed = entry.get(field)
            if parsed:
                try:
                    dt = datetime(*parsed[:6], tzinfo=timezone.utc)
                    return dt
                except (ValueError, TypeError):
                    continue
        return None

    def _extract_articles(
        self,
        feed: feedparser.FeedParserDict,
        source_name: str,
        source_category: str,
        max_age_hours: int = 48,
    ) -> list[Article]:
        """Extract articles from a parsed feed, filtering by age."""
        articles = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

        for entry in feed.get("entries", []):
            published = self._parse_date(entry)

            # Skip articles older than cutoff (if we can determine the date)
            if published and published < cutoff:
                continue

            # Extract description/summary
            description = ""
            if "summary" in entry:
                description = entry["summary"]
            elif "description" in entry:
                description = entry["description"]

            # Clean HTML tags from description (simple approach)
            import re
            description = re.sub(r"<[^>]+>", " ", description)
            description = re.sub(r"\s+", " ", description).strip()

            article = Article(
                title=entry.get("title", "No title"),
                link=entry.get("link", ""),
                description=description[:500],  # Limit description length
                published=published,
                source_name=source_name,
                source_category=source_category,
            )

            if article.title and article.link:
                articles.append(article)

        return articles

    def collect_government_feeds(self, max_age_hours: int = 48) -> list[Article]:
        """Collect articles from government RSS feeds."""
        articles = []
        sources = self.sources.get("government", [])

        for source in sources:
            name = source["name"]
            feed_url = source["feed_url"]
            category = source.get("category", "government")

            logger.info(f"Fetching: {name}")
            feed = self._parse_feed(feed_url)
            new_articles = self._extract_articles(
                feed, name, category, max_age_hours
            )
            articles.extend(new_articles)
            logger.info(f"  -> {len(new_articles)} articles from {name}")

        return articles

    def collect_think_tank_feeds(self, max_age_hours: int = 48) -> list[Article]:
        """Collect articles from think tank RSS feeds."""
        articles = []
        sources = self.sources.get("think_tanks", [])

        for source in sources:
            name = source["name"]
            feed_url = source["feed_url"]
            category = source.get("category", "think_tank")

            logger.info(f"Fetching: {name}")
            feed = self._parse_feed(feed_url)
            new_articles = self._extract_articles(
                feed, name, category, max_age_hours
            )
            articles.extend(new_articles)
            logger.info(f"  -> {len(new_articles)} articles from {name}")

        return articles

    def collect_media_feeds(self, max_age_hours: int = 48) -> list[Article]:
        """Collect articles from Canadian media RSS feeds (CBC, CTV, etc.)."""
        articles = []
        sources = self.sources.get("media", [])

        for source in sources:
            name = source["name"]
            feed_url = source["feed_url"]
            category = source.get("category", "google_news")

            logger.info(f"Fetching: {name}")
            feed = self._parse_feed(feed_url)
            new_articles = self._extract_articles(
                feed, name, category, max_age_hours
            )
            articles.extend(new_articles)
            logger.info(f"  -> {len(new_articles)} articles from {name}")

        return articles

    def collect_google_news_feeds(self, max_age_hours: int = 48) -> list[Article]:
        """Collect articles from Google News RSS keyword searches."""
        articles = []
        queries = self.sources.get("google_news_queries", [])
        base_url = self.sources.get(
            "google_news_base_url",
            "https://news.google.com/rss/search?q={query}&hl=en-CA&gl=CA&ceid=CA:en",
        )

        for q in queries:
            query = q["query"]
            label = q["label"]
            feed_url = base_url.format(query=quote_plus(query))

            logger.info(f"Google News: {label}")
            feed = self._parse_feed(feed_url)
            new_articles = self._extract_articles(
                feed, f"Google News - {label}", "google_news", max_age_hours
            )
            articles.extend(new_articles)
            logger.info(f"  -> {len(new_articles)} articles for '{label}'")

        return articles

    def collect_linkedin_feeds(self, max_age_hours: int = 48) -> list[Article]:
        """Collect articles from LinkedIn RSS.app feeds (if configured)."""
        articles = []
        sources = self.sources.get("linkedin_rss", [])

        if not sources:
            logger.info("No LinkedIn RSS feeds configured (Tier 3 - optional)")
            return articles

        for source in sources:
            name = source["name"]
            feed_url = source["feed_url"]
            category = source.get("category", "linkedin")

            logger.info(f"Fetching LinkedIn: {name}")
            feed = self._parse_feed(feed_url)
            new_articles = self._extract_articles(
                feed, name, category, max_age_hours
            )
            articles.extend(new_articles)
            logger.info(f"  -> {len(new_articles)} articles from {name}")

        return articles

    def _deduplicate_by_title(self, articles: list[Article]) -> list[Article]:
        """
        Remove duplicate articles that appear from multiple sources.
        Uses normalized title similarity to catch the same article
        found by different Google News queries.
        """
        seen_titles = {}
        unique = []

        for article in articles:
            # Normalize: lowercase, strip punctuation, collapse spaces
            import re
            normalized = re.sub(r"[^\w\s]", "", article.title.lower())
            normalized = re.sub(r"\s+", " ", normalized).strip()

            # Check if we've seen a very similar title
            is_dup = False
            for seen_norm, seen_article in seen_titles.items():
                # If titles share first 60 chars (normalized), it's a duplicate
                if (
                    len(normalized) > 20
                    and len(seen_norm) > 20
                    and normalized[:60] == seen_norm[:60]
                ):
                    is_dup = True
                    break

            if not is_dup:
                seen_titles[normalized] = article
                unique.append(article)
            else:
                logger.debug(f"Cross-source duplicate removed: {article.title[:50]}...")

        removed = len(articles) - len(unique)
        if removed:
            logger.info(f"Removed {removed} cross-source duplicate(s)")

        return unique

    def collect_all(self, max_age_hours: int = 48) -> list[Article]:
        """Collect articles from ALL configured sources."""
        logger.info("=" * 60)
        logger.info("Starting feed collection...")
        logger.info("=" * 60)

        all_articles = []

        # Tier 1: Government feeds
        logger.info("\n--- Government Sources ---")
        all_articles.extend(self.collect_government_feeds(max_age_hours))

        # Tier 1: Think tanks
        logger.info("\n--- Think Tanks ---")
        all_articles.extend(self.collect_think_tank_feeds(max_age_hours))

        # Tier 1: Canadian media
        logger.info("\n--- Canadian Media ---")
        all_articles.extend(self.collect_media_feeds(max_age_hours))

        # Tier 2: Google News keyword feeds
        logger.info("\n--- Google News Queries ---")
        all_articles.extend(self.collect_google_news_feeds(max_age_hours))

        # Tier 3: LinkedIn (optional)
        logger.info("\n--- LinkedIn Feeds ---")
        all_articles.extend(self.collect_linkedin_feeds(max_age_hours))

        # Remove cross-source duplicates (same article from multiple queries)
        all_articles = self._deduplicate_by_title(all_articles)

        logger.info(f"\nTotal unique articles collected: {len(all_articles)}")
        return all_articles
