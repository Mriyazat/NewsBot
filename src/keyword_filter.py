"""
Keyword Filter - Smart contextual relevance scoring for articles.

Uses a THREE-LAYER approach for non-trusted sources:

1. Primary keyword match: Does the article mention a defence/sovereignty topic?
2. Canada check: Is this specifically about CANADA (not EU, US, UK defence)?
3. Context validation: Is the article ACTUALLY about defence (not sports)?

Scoring:
- Title matches are worth 3x more than description matches
- Multiple keyword matches increase the score
- Negative keywords disqualify articles (sports, entertainment, etc.)
- Trusted sources (government, think tanks) need lower scores to pass
"""

import logging
import re
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


class KeywordFilter:
    """Filters articles using contextual relevance scoring."""

    def __init__(self, keywords_path: str = "config/keywords.yaml"):
        self.keywords_path = keywords_path
        self.config = self._load_config()

        self.primary_keywords = [
            kw.lower() for kw in self.config.get("primary_keywords", [])
        ]
        self.canada_keywords = [
            kw.lower() for kw in self.config.get("canada_keywords", [])
        ]
        self.context_keywords = [
            kw.lower() for kw in self.config.get("context_keywords", [])
        ]
        self.negative_keywords = [
            kw.lower() for kw in self.config.get("negative_keywords", [])
        ]
        self.trusted_categories = self.config.get("trusted_categories", [])

        scoring = self.config.get("scoring", {})
        self.title_multiplier = scoring.get("title_multiplier", 3)
        self.desc_multiplier = scoring.get("description_multiplier", 1)
        self.min_score_trusted = scoring.get("min_score_trusted", 1)
        self.min_score_general = scoring.get("min_score_general", 3)

    def _load_config(self) -> dict:
        """Load keyword configuration from YAML."""
        try:
            with open(self.keywords_path, "r") as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            logger.error(f"Keywords config not found: {self.keywords_path}")
            return {}

    def _count_keyword_matches(
        self, text: str, keywords: list[str]
    ) -> tuple[int, list[str]]:
        """
        Count how many keywords appear in the text.

        Returns:
            (count, list_of_matched_keywords)
        """
        text_lower = text.lower()
        matched = []
        count = 0
        for kw in keywords:
            # Use word boundary matching so "defence" doesn't match "defenceless"
            # but still catches "defence," and "defence." etc.
            pattern = r'\b' + re.escape(kw) + r'\b'
            if re.search(pattern, text_lower):
                matched.append(kw)
                count += 1
        return count, matched

    def _has_negative_keywords(self, title: str, description: str) -> bool:
        """Check if article contains disqualifying negative keywords."""
        combined = f"{title} {description}".lower()
        for neg_kw in self.negative_keywords:
            if neg_kw in combined:
                logger.debug(f"Negative keyword '{neg_kw}' found, excluding article")
                return True
        return False

    def score_article(self, article) -> dict:
        """
        Score an article for relevance.

        Returns a dict with:
        - score: numeric relevance score
        - passed: bool whether it meets the threshold
        - matched_primary: list of matched primary keywords
        - matched_context: list of matched context keywords
        - reason: human-readable explanation
        """
        title = article.title
        description = article.description
        category = article.source_category

        # Step 1: Check negative keywords (instant disqualification)
        if self._has_negative_keywords(title, description):
            return {
                "score": 0,
                "passed": False,
                "matched_primary": [],
                "matched_context": [],
                "reason": "Excluded by negative keyword",
            }

        # Step 2: Count primary keyword matches in title and description
        title_primary_count, title_primary_matched = self._count_keyword_matches(
            title, self.primary_keywords
        )
        desc_primary_count, desc_primary_matched = self._count_keyword_matches(
            description, self.primary_keywords
        )

        all_primary_matched = list(
            set(title_primary_matched + desc_primary_matched)
        )

        # Step 3: Calculate primary score
        primary_score = (
            title_primary_count * self.title_multiplier
            + desc_primary_count * self.desc_multiplier
        )

        # Step 4: If no primary keywords matched, the article is not relevant
        if primary_score == 0:
            return {
                "score": 0,
                "passed": False,
                "matched_primary": [],
                "matched_context": [],
                "reason": "No primary keyword match",
            }

        # Step 5: For trusted sources, primary match is enough
        is_trusted = category in self.trusted_categories
        if is_trusted:
            min_score = self.min_score_trusted
        else:
            min_score = self.min_score_general

        # Step 6: Canada check + context validation for non-trusted sources
        context_matched = []
        if not is_trusted:
            # 6a: Article MUST mention Canada specifically
            combined_text = f"{title} {description}"
            _, canada_matched = self._count_keyword_matches(
                combined_text, self.canada_keywords
            )
            if not canada_matched:
                return {
                    "score": primary_score,
                    "passed": False,
                    "matched_primary": all_primary_matched,
                    "matched_context": [],
                    "reason": "Not about Canada",
                }

            # 6b: Also need domain context keywords
            _, title_context = self._count_keyword_matches(
                title, self.context_keywords
            )
            _, desc_context = self._count_keyword_matches(
                description, self.context_keywords
            )
            context_matched = list(set(title_context + desc_context))

            if not context_matched:
                return {
                    "score": primary_score,
                    "passed": False,
                    "matched_primary": all_primary_matched,
                    "matched_context": [],
                    "reason": "Primary match but no context validation (likely off-topic)",
                }

            # Bonus: multiple context keywords boost the score
            context_bonus = len(context_matched) - 1
            primary_score += context_bonus

        # Step 7: Check against threshold
        passed = primary_score >= min_score

        if passed:
            reason = (
                f"Score {primary_score} >= {min_score} "
                f"({'trusted' if is_trusted else 'general'} source)"
            )
        else:
            reason = (
                f"Score {primary_score} < {min_score} "
                f"({'trusted' if is_trusted else 'general'} source)"
            )

        return {
            "score": primary_score,
            "passed": passed,
            "matched_primary": all_primary_matched,
            "matched_context": context_matched,
            "reason": reason,
        }

    def filter_articles(self, articles: list) -> list:
        """
        Filter a list of articles, returning only relevant ones.

        Each returned article gets an additional `relevance` attribute
        with scoring details.
        """
        relevant = []
        total = len(articles)
        passed_count = 0

        for article in articles:
            result = self.score_article(article)

            if result["passed"]:
                article.relevance_score = result["score"]
                article.matched_keywords = result["matched_primary"]
                relevant.append(article)
                passed_count += 1
                logger.debug(
                    f"  PASS [{result['score']}]: {article.title[:60]}... "
                    f"({result['reason']})"
                )
            else:
                logger.debug(
                    f"  SKIP: {article.title[:60]}... ({result['reason']})"
                )

        # Sort by relevance score (highest first), then by date
        relevant.sort(
            key=lambda a: (
                -a.relevance_score,
                a.published or datetime_min(),
            ),
            reverse=False,
        )

        # Re-sort: highest score first, and within same score, newest first
        relevant.sort(
            key=lambda a: (
                -a.relevance_score,
                -(a.published.timestamp() if a.published else 0),
            )
        )

        logger.info(
            f"Keyword filter: {passed_count}/{total} articles passed "
            f"({total - passed_count} filtered out)"
        )

        return relevant


def datetime_min():
    """Return a minimal datetime for sorting fallback."""
    from datetime import datetime, timezone
    return datetime(2000, 1, 1, tzinfo=timezone.utc)
