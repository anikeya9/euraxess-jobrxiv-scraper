# Job Finder AI 🤖

An agentic AI pipeline that scrapes academic and research job boards, then uses two LLM agents to filter and score jobs against your personal profile — so you only review the ones that actually matter.

Built with [Claude](https://claude.ai) (Anthropic) as an AI pair-programming assistant.

---

## How it works

```
scraper.py                      →    jobs.json
(EURAXESS or jobRxiv)                (raw job data)
                                           ↓
                                    run_agents.py
                                           ↓
                              Agent 1: Technical Gate
                              (PASS / REJECT based on role & skills)
                                           ↓
                              Agent 2: Life Situation Score
                              (chill factor 1-10: WLB, location, culture)
                                           ↓
                                    results.csv
                              (all Agent 1 passes + Agent 2 scores)
```

**Key design decisions:**
- **Scrape once, evaluate many times.** `jobs.json` is saved locally. Re-run the agents with different thresholds without re-scraping.
- **Chunked & resumable.** Process 100 jobs at a time. Progress is saved to `progress.json` — stop and resume any time.
- **Two agents with distinct roles.** Agent 1 is a strict technical screener. Agent 2 evaluates work-life balance, location, and culture — separate concerns, separate prompts.
- **No CV PDF required.** Your profile is hardcoded in `profile.py` for precise, consistent evaluation.

---

## Sources

| Source | Type | Notes |
|---|---|---|
| [EURAXESS](https://euraxess.ec.europa.eu/jobs/search) | Academic / Research | EU-focused, server-side rendered, no account needed |
| [jobRxiv](https://jobrxiv.org) | Academic / Research | International science jobs, open access |

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/job-finder-ai.git
cd job-finder-ai
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set up your profile

```bash
cp profile.example.py profile.py
```

Edit `profile.py` with your own background, skills, location, and goals. This file is in `.gitignore` — it never gets committed.

### 4. Get a free Gemini API key

Get your key at [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) — free tier includes 14,400 requests/day on Gemma 3 27B.

```bash
export GEMINI_API_KEY="AIza..."
```

---

## Usage

### Step 1 — Scrape jobs

```bash
# Scrape EURAXESS (default)
python scraper.py --source euraxess --pages 10

# Scrape jobRxiv
python scraper.py --source jobrxiv --pages 5

# Use a custom filtered URL
python scraper.py --source euraxess --url "https://euraxess.ec.europa.eu/jobs/search?..." --pages 20

# Save to a specific file
python scraper.py --source jobrxiv --output jobrxiv_jobs.json
```

This saves all scraped jobs to `jobs.json` (or your named file).

### Step 2 — Run the agents

```bash
# Screen 100 jobs through Agent 1, stop after 100 passes
python run_agents.py --mode screen --chunk 100

# Resume from where you left off
python run_agents.py --mode screen --chunk 100

# Run Agent 2 on all passes, save to a named file
python run_agents.py --mode evaluate --output results_chill7.csv

# Re-run Agent 2 with a looser threshold
python run_agents.py --mode evaluate --chill-threshold 6 --output results_chill6.csv

# Screen and evaluate in one go
python run_agents.py --mode both --chunk 100 --output batch1.csv
```

### Step 3 — Review results

Open the CSV in Excel or LibreOffice. Useful filters:
- `agent2_approved = TRUE` → best picks
- Sort `agent2_chill_score` descending → ranked list
- `agent2_location_verdict = GREAT` → easiest commute
- `agent2_approved = FALSE` → review manually, Agent 2 may be too strict

---

## Configuration

| File | What to edit |
|---|---|
| `profile.py` | Your skills, goals, location — private, never committed |
| `scraper.py` | `EURAXESS_URL`, `JOBRXIV_URL`, `MAX_PAGES`, `SCRAPE_DELAY_MIN/MAX` |
| `run_agents.py` | `GEMINI_MODEL`, `API_DELAY`, `CHILL_THRESHOLD` |

### Tuning Agent 2 strictness

```bash
# Strict (fewer results, higher quality)
python run_agents.py --mode evaluate --chill-threshold 8 --output strict.csv

# Balanced (default)
python run_agents.py --mode evaluate --chill-threshold 7 --output balanced.csv

# Loose (more results to review manually)
python run_agents.py --mode evaluate --chill-threshold 6 --output loose.csv
```

---

## Rate limits (free Gemma 3 27B tier)

| Limit | Value | Impact |
|---|---|---|
| RPM | 30 | `API_DELAY = 5.0s` keeps you at ~12 calls/min |
| TPM | 15,000 | ~1,100 tokens/call × 12 calls/min = ~13,200 TPM ✅ |
| RPD | 14,400 | Enough for ~7,200 jobs/day (2 calls each) |

---

## Project structure

```
job-finder-ai/
  scraper.py            ← scrapes EURAXESS or jobRxiv → jobs.json
  run_agents.py         ← chunked, resumable two-agent pipeline
  profile.example.py    ← template: copy to profile.py and fill in
  profile.py            ← your private profile (gitignored)
  requirements.txt
  .gitignore
  README.md
```

---

## Built with

- [Claude](https://claude.ai) by [Anthropic](https://anthropic.com) — AI pair-programming assistant
- [Gemma 3 27B](https://aistudio.google.com) via Google AI Studio — free LLM for agent evaluation
- [requests](https://requests.readthedocs.io) + [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) — web scraping

---

## Disclaimer

This tool scrapes publicly available job listings. Always respect each site's `robots.txt` and terms of service. EURAXESS and jobRxiv are academic/open platforms that do not prohibit reasonable automated access to public data.
