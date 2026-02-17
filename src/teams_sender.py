"""
Teams Sender - Formats and sends news digests to Microsoft Teams.

Uses Teams Workflows webhook to POST Adaptive Cards.
Uses compatible elements only (no Container emphasis/bleed).
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
        """Category labels with emoji indicators."""
        labels = {
            "government": "\U0001F3DB\uFE0F  Government Sources",
            "think_tank": "\U0001F4D6  Research & Analysis",
            "google_news": "\U0001F4F0  News & Media",
            "linkedin": "\U0001F4BC  LinkedIn",
        }
        return labels.get(category, category.title())

    def _clean_source(self, source_name: str) -> str:
        """Clean up source name for display."""
        if source_name.startswith("Google News - "):
            return source_name.replace("Google News - ", "")
        return source_name

    def _build_adaptive_card(self, articles: list, date_str: str) -> dict:
        """Build a polished Adaptive Card for Teams."""
        body = []

        # ── Header ──
        body.append({
            "type": "TextBlock",
            "text": "\U0001F6E1\uFE0F Defence & Sovereignty News",
            "weight": "Bolder",
            "size": "ExtraLarge",
            "wrap": True,
            "color": "Accent",
        })
        body.append({
            "type": "TextBlock",
            "text": f"{date_str}",
            "isSubtle": True,
            "spacing": "None",
            "size": "Small",
        })
        body.append({
            "type": "TextBlock",
            "text": f"**{len(articles)}** new articles across Canadian defence & sovereignty topics",
            "wrap": True,
            "spacing": "Small",
            "size": "Small",
        })

        # ── Articles grouped by category ──
        grouped = self._group_articles(articles)
        article_num = 0

        for category, cat_articles in grouped.items():
            # Category header with separator line
            body.append({
                "type": "TextBlock",
                "text": self._category_label(category),
                "weight": "Bolder",
                "size": "Medium",
                "spacing": "ExtraLarge",
                "separator": True,
                "wrap": True,
            })

            # Each article as a numbered entry
            for article in cat_articles[:MAX_ARTICLES_PER_MESSAGE]:
                article_num += 1
                title = article.title[:MAX_TITLE_LENGTH]
                if len(article.title) > MAX_TITLE_LENGTH:
                    title += "..."

                source = self._clean_source(article.source_name)
                date_part = f" \u2022 {article.published_str}" if article.published else ""

                # Article number + clickable title
                body.append({
                    "type": "TextBlock",
                    "text": f"**{article_num}.** [{title}]({article.link})",
                    "wrap": True,
                    "spacing": "Medium",
                    "size": "Default",
                })

                # Source and date on a subtle line below
                body.append({
                    "type": "TextBlock",
                    "text": f"\u2003\u2003{source}{date_part}",
                    "isSubtle": True,
                    "spacing": "None",
                    "size": "Small",
                    "wrap": True,
                })

        # ── Footer ──
        body.append({
            "type": "TextBlock",
            "text": "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
            "isSubtle": True,
            "spacing": "Large",
            "size": "Small",
        })
        body.append({
            "type": "TextBlock",
            "text": f"Sources: {len(articles)} articles from government feeds, think tanks, CBC, Global News, National Post, Globe and Mail & Google News",
            "isSubtle": True,
            "spacing": "None",
            "size": "Small",
            "wrap": True,
        })

        # Standard webhook payload
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
                "type": "TextBlock",
                "text": "\U0001F6E1\uFE0F Defence & Sovereignty News",
                "weight": "Bolder",
                "size": "ExtraLarge",
                "wrap": True,
                "color": "Accent",
            },
            {
                "type": "TextBlock",
                "text": date_str,
                "isSubtle": True,
                "spacing": "None",
                "size": "Small",
            },
            {
                "type": "TextBlock",
                "text": "No new relevant articles found today. All sources were checked.",
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
        """Send a news digest to Teams."""
        date_str = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")

        if articles:
            payload = self._build_adaptive_card(articles, date_str)
        else:
            payload = self._build_no_news_card(date_str)

        if dry_run:
            logger.info("DRY RUN - Would send to Teams:")
            self._print_digest_preview(articles, date_str)
            return True

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
        print(f"  Defence & Sovereignty News")
        print(f"  {date_str}  |  {len(articles)} articles")
        print(f"{'='*60}")

        if not articles:
            print("\n  No new relevant articles found today.\n")
            return

        grouped = self._group_articles(articles)
        num = 0

        for category, cat_articles in grouped.items():
            print(f"\n  {self._category_label(category)}")
            print(f"  {'─' * 40}")
            for article in cat_articles:
                num += 1
                source = self._clean_source(article.source_name)
                print(f"  {num}. {article.title[:75]}")
                print(f"     {source} \u2022 {article.published_str}")

        print(f"\n{'='*60}\n")
