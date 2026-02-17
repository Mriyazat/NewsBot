"""
Teams Sender - Formats and sends news digests to Microsoft Teams.

Uses Teams Workflows webhook (the free replacement for Incoming Webhooks)
to POST Adaptive Cards with a clean, organized daily news digest
grouped by source category.

Setup: In Teams channel > "..." > Workflows > "Post to a channel when
a webhook request is received" > copy the URL into .env
"""

import logging
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

MAX_ARTICLES_PER_MESSAGE = 30
MAX_TITLE_LENGTH = 150


class TeamsSender:
    """Sends formatted news digests to a Microsoft Teams channel."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def _group_articles(self, articles: list) -> dict[str, list]:
        """Group articles by source category for organized display."""
        groups = {
            "government": [],
            "think_tank": [],
            "google_news": [],
            "linkedin": [],
        }

        for article in articles:
            category = getattr(article, "source_category", "google_news")
            if category not in groups:
                groups[category] = []
            groups[category].append(article)

        return {k: v for k, v in groups.items() if v}

    def _category_label(self, category: str) -> str:
        """Human-readable category labels with icon."""
        labels = {
            "government": "\U0001F3DB Government",
            "think_tank": "\U0001F4DA Research & Analysis",
            "google_news": "\U0001F4F0 News & Media",
            "linkedin": "\U0001F4BC LinkedIn",
        }
        return labels.get(category, category.title())

    def _category_color(self, category: str) -> str:
        """Color for each category."""
        colors = {
            "government": "Light",
            "think_tank": "Good",
            "google_news": "Accent",
            "linkedin": "Warning",
        }
        return colors.get(category, "Default")

    def _build_article_block(self, article) -> dict:
        """Build a single article as a clean container block."""
        title = article.title[:MAX_TITLE_LENGTH]
        if len(article.title) > MAX_TITLE_LENGTH:
            title += "..."

        # Clean source name (remove "Google News - " prefix for cleaner look)
        source = article.source_name
        if source.startswith("Google News - "):
            source = source.replace("Google News - ", "")

        # Build the subtitle: Source | Date
        subtitle_parts = [source]
        if article.published:
            subtitle_parts.append(article.published_str)

        return {
            "type": "Container",
            "spacing": "Medium",
            "items": [
                {
                    "type": "ColumnSet",
                    "columns": [
                        {
                            "type": "Column",
                            "width": "auto",
                            "items": [
                                {
                                    "type": "TextBlock",
                                    "text": "\u25AA",
                                    "color": "Accent",
                                    "spacing": "None",
                                    "size": "Small",
                                }
                            ],
                            "verticalContentAlignment": "Top",
                            "spacing": "None",
                        },
                        {
                            "type": "Column",
                            "width": "stretch",
                            "spacing": "Small",
                            "items": [
                                {
                                    "type": "TextBlock",
                                    "text": f"[{title}]({article.link})",
                                    "wrap": True,
                                    "spacing": "None",
                                    "weight": "Bolder",
                                    "size": "Default",
                                },
                                {
                                    "type": "TextBlock",
                                    "text": " \u00B7 ".join(subtitle_parts),
                                    "isSubtle": True,
                                    "spacing": "None",
                                    "size": "Small",
                                    "wrap": True,
                                },
                            ],
                        },
                    ],
                }
            ],
        }

    def _build_adaptive_card(self, articles: list, date_str: str) -> dict:
        """Build a clean, modern Adaptive Card for Teams."""
        body = []

        # ── Header ──
        body.append({
            "type": "Container",
            "style": "emphasis",
            "bleed": True,
            "items": [
                {
                    "type": "ColumnSet",
                    "columns": [
                        {
                            "type": "Column",
                            "width": "stretch",
                            "items": [
                                {
                                    "type": "TextBlock",
                                    "text": "\U0001F6E1 Defence & Sovereignty News",
                                    "weight": "Bolder",
                                    "size": "Large",
                                    "wrap": True,
                                    "color": "Light",
                                },
                                {
                                    "type": "TextBlock",
                                    "text": f"{date_str}  \u2022  {len(articles)} articles",
                                    "size": "Small",
                                    "isSubtle": True,
                                    "spacing": "None",
                                    "wrap": True,
                                },
                            ],
                        },
                    ],
                },
            ],
        })

        # ── Articles grouped by category ──
        grouped = self._group_articles(articles)

        for category, cat_articles in grouped.items():
            # Category section header
            body.append({
                "type": "TextBlock",
                "text": self._category_label(category),
                "weight": "Bolder",
                "size": "Medium",
                "spacing": "Large",
                "color": self._category_color(category),
                "wrap": True,
                "separator": True,
            })

            # Article entries
            for article in cat_articles[:MAX_ARTICLES_PER_MESSAGE]:
                body.append(self._build_article_block(article))

        # ── Payload ──
        payload = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "contentUrl": None,
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": body,
                    },
                }
            ],
        }

        return payload

    def _build_no_news_card(self, date_str: str) -> dict:
        """Build a card for when there are no relevant articles."""
        body = [
            {
                "type": "Container",
                "style": "emphasis",
                "bleed": True,
                "items": [
                    {
                        "type": "TextBlock",
                        "text": "\U0001F6E1 Defence & Sovereignty News",
                        "weight": "Bolder",
                        "size": "Large",
                        "wrap": True,
                        "color": "Light",
                    },
                    {
                        "type": "TextBlock",
                        "text": date_str,
                        "size": "Small",
                        "isSubtle": True,
                        "spacing": "None",
                    },
                ],
            },
            {
                "type": "TextBlock",
                "text": "No new relevant articles found today. All sources checked.",
                "wrap": True,
                "spacing": "Large",
                "isSubtle": True,
            },
        ]

        return {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "contentUrl": None,
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": body,
                    },
                }
            ],
        }

    def send_digest(
        self, articles: list, dry_run: bool = False
    ) -> bool:
        """
        Send a news digest to Teams.

        Args:
            articles: List of filtered, deduplicated articles
            dry_run: If True, print the card instead of sending

        Returns:
            True if sent successfully (or dry_run), False otherwise
        """
        date_str = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")

        if articles:
            payload = self._build_adaptive_card(articles, date_str)
        else:
            payload = self._build_no_news_card(date_str)

        if dry_run:
            logger.info("=" * 60)
            logger.info("DRY RUN - Would send to Teams:")
            logger.info("=" * 60)
            self._print_digest_preview(articles, date_str)
            return True

        # Send to Teams Workflows webhook
        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )

            if response.status_code in (200, 202):
                logger.info(
                    f"Successfully sent digest with {len(articles)} articles "
                    f"to Teams (HTTP {response.status_code})"
                )
                return True
            else:
                logger.error(
                    f"Teams webhook returned {response.status_code}: "
                    f"{response.text[:300]}"
                )
                return False

        except requests.RequestException as e:
            logger.error(f"Failed to send to Teams: {e}")
            return False

    def _print_digest_preview(self, articles: list, date_str: str):
        """Print a text preview of the digest for dry-run mode."""
        print(f"\n{'='*60}")
        print(f"  \U0001F6E1 Defence & Sovereignty News")
        print(f"  {date_str}  \u2022  {len(articles)} articles")
        print(f"{'='*60}")

        if not articles:
            print("\n  No new relevant articles found today.\n")
            return

        grouped = self._group_articles(articles)

        for category, cat_articles in grouped.items():
            print(f"\n  {self._category_label(category)}")
            print(f"  {'─' * 40}")
            for article in cat_articles:
                source = article.source_name
                if source.startswith("Google News - "):
                    source = source.replace("Google News - ", "")
                print(f"  \u25AA {article.title[:80]}")
                print(f"    {source} \u00B7 {article.published_str}")
                print(f"    {article.link[:80]}")

        print(f"\n{'='*60}\n")
