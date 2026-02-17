"""
NewsBot - Main Orchestrator & Scheduler

Canadian Defence & Sovereignty News Aggregator
Collects news from government RSS feeds, think tanks, and Google News,
filters for relevance, and sends a daily digest to Microsoft Teams.

Usage:
    python -m src.main                  # Run once (collect + send)
    python -m src.main --dry-run        # Collect + preview (no Teams send)
    python -m src.main --schedule       # Run daily at scheduled time
    python -m src.main --schedule 08:00 # Run daily at 8:00 AM
    python -m src.main --stats          # Show dedup database stats
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import schedule
from dotenv import load_dotenv

# Ensure we can import from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.feed_collector import FeedCollector
from src.keyword_filter import KeywordFilter
from src.dedup import DedupTracker
from src.teams_sender import TeamsSender

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(verbose: bool = False):
    """Configure logging with optional verbose mode."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("data/newsbot.log", mode="a"),
        ],
    )
    # Quiet down noisy libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("feedparser").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------
def run_pipeline(
    dry_run: bool = False,
    max_age_hours: int = 48,
    webhook_url: str = "",
) -> int:
    """
    Execute the full news collection pipeline.

    Steps:
    1. Collect articles from all RSS sources
    2. Filter by keyword relevance
    3. Deduplicate against previously sent articles
    4. Send digest to Teams (or print preview in dry-run mode)

    Returns:
        Number of articles sent
    """
    logger = logging.getLogger("newsbot.pipeline")

    logger.info("=" * 60)
    logger.info("NewsBot Pipeline Starting")
    logger.info(f"Time: {datetime.now(timezone.utc).isoformat()}")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    logger.info(f"Max article age: {max_age_hours} hours")
    logger.info("=" * 60)

    # Step 1: Collect feeds
    logger.info("\nStep 1/4: Collecting feeds...")
    collector = FeedCollector()
    all_articles = collector.collect_all(max_age_hours=max_age_hours)

    if not all_articles:
        logger.warning("No articles collected from any source!")

    # Step 2: Keyword filtering
    logger.info("\nStep 2/4: Applying keyword filter...")
    kw_filter = KeywordFilter()
    relevant_articles = kw_filter.filter_articles(all_articles)

    # Step 3: Deduplication
    logger.info("\nStep 3/4: Deduplicating...")
    dedup = DedupTracker()
    new_articles = dedup.filter_unseen(relevant_articles)

    # Step 4: Send to Teams
    logger.info(f"\nStep 4/4: Sending {len(new_articles)} articles to Teams...")

    if not webhook_url and not dry_run:
        logger.error(
            "No TEAMS_WEBHOOK_URL configured! "
            "Set it in .env or pass --dry-run to preview."
        )
        # Still show a preview even without webhook
        dry_run = True

    sender = TeamsSender(webhook_url=webhook_url)
    success = sender.send_digest(new_articles, dry_run=dry_run)

    if success and not dry_run:
        # Mark articles as sent
        dedup.mark_batch_seen(new_articles)
        logger.info(f"Marked {len(new_articles)} articles as sent")
    elif dry_run:
        logger.info("Dry run complete - no articles marked as sent")

    # Periodic cleanup of old entries
    dedup.cleanup_old(days=30)

    logger.info(f"\nPipeline complete. {len(new_articles)} new articles processed.")
    return len(new_articles)


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
def run_scheduled(schedule_time: str = "07:00", dry_run: bool = False):
    """Run the pipeline on a daily schedule."""
    logger = logging.getLogger("newsbot.scheduler")

    webhook_url = os.getenv("TEAMS_WEBHOOK_URL", "")

    logger.info(f"Scheduling daily run at {schedule_time} (local time)")
    logger.info("Press Ctrl+C to stop.\n")

    def job():
        logger.info(f"Scheduled run triggered at {datetime.now()}")
        try:
            run_pipeline(dry_run=dry_run, webhook_url=webhook_url)
        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)

    schedule.every().day.at(schedule_time).do(job)

    # Also run immediately on start
    logger.info("Running initial collection now...")
    job()

    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    """Command-line interface for NewsBot."""
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="NewsBot - Canadian Defence & Sovereignty News Aggregator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.main --dry-run          Preview collected news
  python -m src.main                    Collect and send to Teams
  python -m src.main --schedule 08:00   Run daily at 8:00 AM
  python -m src.main --stats            Show database statistics
  python -m src.main --verbose          Run with debug logging
        """,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Collect and preview articles without sending to Teams",
    )
    parser.add_argument(
        "--schedule",
        nargs="?",
        const="07:00",
        metavar="HH:MM",
        help="Run on a daily schedule (default: 07:00)",
    )
    parser.add_argument(
        "--max-age",
        type=int,
        default=48,
        metavar="HOURS",
        help="Maximum article age in hours (default: 48)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show deduplication database statistics",
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(verbose=args.verbose)

    # Ensure data directory exists
    Path("data").mkdir(exist_ok=True)

    if args.stats:
        dedup = DedupTracker()
        stats = dedup.stats()
        print(f"\nNewsBot Database Stats:")
        print(f"  Total articles tracked: {stats['total_tracked']}")
        print(f"  Sent in last 24 hours:  {stats['sent_last_24h']}")
        return

    webhook_url = os.getenv("TEAMS_WEBHOOK_URL", "")

    if args.schedule:
        run_scheduled(
            schedule_time=args.schedule,
            dry_run=args.dry_run,
        )
    else:
        run_pipeline(
            dry_run=args.dry_run,
            max_age_hours=args.max_age,
            webhook_url=webhook_url,
        )


if __name__ == "__main__":
    main()
