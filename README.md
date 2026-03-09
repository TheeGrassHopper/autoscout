# AutoScout AI — Vehicle Deal Hunter

A multi-phase Python system that scrapes vehicle listings from Craigslist (and later FB Marketplace),
compares them against KBB / Carvana / Carmax, scores each deal, and auto-drafts seller messages
via the Claude API.

---

## Project Structure

```
autoscout/
├── main.py                  # Entry point — run the full pipeline
├── config.py                # All your search settings in one place
├── requirements.txt
├── .env.example
│
├── scrapers/
│   ├── craigslist.py        # Craigslist RSS + HTML scraper
│   └── facebook.py          # FB Marketplace via Apify (Phase 2)
│
├── pricing/
│   ├── kbb.py               # KBB market value lookup
│   ├── carvana.py           # Carvana comparable search
│   └── carmax.py            # Carmax comparable search
│
├── scoring/
│   └── engine.py            # Deal scoring algorithm
│
├── messaging/
│   ├── drafter.py           # Claude API message drafting
│   └── sender.py            # Message sending / export
│
├── utils/
│   ├── normalizer.py        # Claude AI listing normalizer
│   ├── db.py                # SQLite — tracks listings + sent messages
│   └── notifier.py          # SMS alerts via Twilio
│
└── output/
    └── deals.csv            # Exported results
```

## Quick Start

1. pip install -r requirements.txt
2. cp .env.example .env  (add your API keys)
3. Edit config.py with your search criteria
4. python main.py

## Build Phases

Phase 1 — Craigslist + KBB + scoring + CSV export     (THIS REPO)
Phase 2 — FB Marketplace (Apify) + Claude normalize   (next)
Phase 3 — n8n scheduler + SQLite + Twilio SMS         (next)
Phase 4 — Auto-send messages + approval workflow      (next)
