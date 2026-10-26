# Signal Desk

Private research system: theses, a decision journal, and a dated archive of hiring data.
Plan: see the "Investment Intelligence System — Plan" doc.

## Layout

| Path | What it holds |
| --- | --- |
| `theses/` | One YAML file per thesis, in the template in `theses/TEMPLATE.yaml` |
| `watchlist/companies.csv` | Watch-list companies, themes, tickers and the executives to follow |
| `journal/positions.csv` | Every position: why it was bought, its kill criterion, linked theses |
| `journal/decisions.csv` | Every decision, including decisions not to act (starts in Week 2) |
| `config/career_boards.yaml` | Career boards to snapshot each day |
| `scripts/` | Data jobs |
| `data/jobs/` | Career-board snapshots: current roles, open/close events, daily counts |
| `data/hiringlab/` | Indeed Hiring Lab series for tracked countries and sectors, plus a summary |

## Daily job

`.github/workflows/daily.yml` runs at 06:17 UTC every day on GitHub's servers (your laptop can be off):

1. Runs the tests.
2. `scripts/snapshot_jobs.py` reads every board in `config/career_boards.yaml`, stores today's open roles, and logs roles opened and closed since yesterday. Roles are grouped (customer support, software engineering, product management, data and AI, legal, accounting and finance, and others) and tagged junior, senior or unknown.
3. `scripts/snapshot_hiringlab.py` appends new days of Indeed Hiring Lab data for the US, UK, Germany, France and Ireland, and rewrites `data/hiringlab/summary.csv` with the latest level and 3- and 12-month changes.
4. Commits any new data.

Run it by hand from the Actions tab (Daily snapshot, then Run workflow). After the first run, check `data/jobs/board_status.csv` and fix or remove boards that show `ok = no`.

## Run locally

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/snapshot_hiringlab.py
python scripts/snapshot_jobs.py
```

## Data licences

- Indeed Hiring Lab data: CC BY 4.0. Cite "Indeed Hiring Lab" in anything published.
- Career-board data comes from public job-board endpoints. Poll at most once a day.
- Do not commit paid-data-provider content (for example FMP transcripts) to anything that is published.

## Next jobs (Phase 1)

- `scripts/sec_13f.py`: quarter-on-quarter 13F changes for the tracked funds.
- `scripts/form4.py`: insider open-market purchases at watch-list companies.
- Workday career sites for large companies.
- The Hiring Lab generative-AI share file has moved; find its new path.
