# NewsBot - Canadian Defence & Sovereignty News Aggregator

A Python bot that collects defence and sovereignty-related news from Canadian government RSS feeds, think tanks, major media (CBC, CTV, Globe and Mail, etc.), and Google News, filters them for relevance, and delivers a digest to Microsoft Teams every 12 hours.

## Features

- **Multi-source collection**: Government RSS, think tanks, CBC/CTV/Globe and Mail/National Post, Google News keyword searches, and optional LinkedIn feeds
- **Smart keyword filtering**: Two-layer relevance scoring (not just keyword matching) with negative keyword exclusion to avoid false positives
- **Deduplication**: SQLite-based tracking ensures you never see the same article twice
- **Teams integration**: Clean Adaptive Card posted via Teams Workflows webhook
- **Automated delivery**: GitHub Actions runs every 12 hours (7 AM and 7 PM EST)
- **Configurable**: All sources and keywords managed via YAML files

## Quick Start

### 1. Set up the environment

```bash
conda activate newsbot
pip install -r requirements.txt
```

### 2. Configure Teams webhook

```bash
cp .env.example .env
# Edit .env and paste your Teams webhook URL
```

To create a Teams webhook (free, no premium needed):
1. Go to your Teams channel
2. Click **...** on the channel name > **Workflows**
3. Select **"Post to a channel when a webhook request is received"**
4. Name it (e.g. "NewsBot"), click through
5. Copy the webhook URL into `.env`

### 3. Run a dry-run preview

```bash
python -m src.main --dry-run
```

### 4. Send to Teams

```bash
python -m src.main
```

## Automated Deployment (GitHub Actions)

The bot runs automatically every 12 hours via GitHub Actions. To set it up:

### 1. Push code to GitHub

```bash
git push -u origin main
```

### 2. Add your webhook URL as a GitHub secret

1. Go to your repo on GitHub
2. **Settings** > **Secrets and variables** > **Actions**
3. Click **New repository secret**
4. Name: `TEAMS_WEBHOOK_URL`
5. Value: paste your full webhook URL
6. Click **Add secret**

### 3. That's it

The workflow runs automatically at:
- **7:00 AM EST** (12:00 UTC)
- **7:00 PM EST** (00:00 UTC)

You can also trigger it manually: **Actions** tab > **NewsBot** > **Run workflow**.

## Usage (local)

```
python -m src.main [options]

Options:
  --dry-run             Preview articles without sending to Teams
  --schedule [HH:MM]    Run daily at the specified time (default: 07:00)
  --max-age HOURS       Maximum article age in hours (default: 48)
  --verbose, -v         Enable debug logging
  --stats               Show deduplication database statistics
```

## Configuration

### Adding/Removing Sources

Edit `config/sources.yaml`:

- **Government**: Canada.ca, DND, NSERC, Global Affairs, CSA, IDEaS, ISED
- **Think tanks**: CDA Institute, Macdonald-Laurier, NAADSN, CIC
- **Media**: CBC Politics, CBC Canada, CTV, Global News, National Post, Globe and Mail
- **Google News**: 18 keyword queries covering defence research, Arctic, quantum, procurement, etc.
- **LinkedIn** (optional): Via RSS.app

### Tuning Keywords

Edit `config/keywords.yaml`:

- **primary_keywords**: Topics you care about (must match at least one)
- **context_keywords**: Domain validation (proves article is about defence, not sports)
- **negative_keywords**: Disqualifiers (sports, entertainment, etc.)
- **scoring thresholds**: Adjust sensitivity for trusted vs. general sources

## Project Structure

```
NewsBot/
├── .github/workflows/
│   └── newsbot.yml         # GitHub Actions (every 12 hours)
├── config/
│   ├── sources.yaml        # RSS feed URLs and Google News queries
│   └── keywords.yaml       # Keywords, context validation, scoring
├── src/
│   ├── main.py             # CLI + orchestrator + scheduler
│   ├── feed_collector.py   # RSS/Atom feed fetching & parsing
│   ├── keyword_filter.py   # Two-layer relevance scoring
│   ├── dedup.py            # SQLite duplicate tracking
│   └── teams_sender.py     # Teams Adaptive Card formatting
├── data/                   # Auto-created DB + logs (not committed)
├── .env                    # Your webhook URL (not committed)
├── .env.example            # Template for .env
├── requirements.txt
└── README.md
```

## License

MIT
