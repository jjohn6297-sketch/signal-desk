# How Signal Desk runs itself

John reviews key insights and can override any forecast. Everything else is automatic.

## The three jobs

| Job | When | Who | Does |
| --- | --- | --- | --- |
| Daily snapshot | 06:17 UTC every day | GitHub Actions (`.github/workflows/daily.yml`) | Career-board and Hiring Lab snapshots; resolves forecasts with `method: auto`; rescores; refits recalibration |
| Daily run | Weekdays after 09:00 Dublin | Scheduled Claude task | Resolves judged forecasts that are due; pre-registers forecasts for events in the next 7 days; updates thesis evidence; checks kill criteria; raises action cards; writes the daily insights |
| Weekly review | Sundays after 09:00 Dublin | Scheduled Claude task | Reviews scores and calibration; updates system conviction per thesis; retires or rewrites weak theses; proposes new contrarian bets; writes the weekly insights |

## The Signal Desk docs (Claude Docs)

| Doc | Id | Use |
| --- | --- | --- |
| Signal Desk: how it works (tabs: How it works, Insights log) | `f28084e2-f891-4e31-930e-6234fa247a2e` | Operating guide; the Insights log tab receives every run's insights, newest first |
| Week 1: contrarian bets, theses and watch list | `f9c98915-06bb-4212-84ad-59d33b46ec86` | Bets, theses, forecast tables, watch list tab |
| Investment Intelligence System: plan | `3dce3446-b0fb-40d4-942f-f825bdd74202` | The plan |
| Signal Desk dashboard (Dashboard artifact, not a doc) | https://claude.ai/artifact/Uh1nu9TVMEPNViAcATP81K | Private page; its data sources are refreshed in daily-run step 10 |

Last-seen revisions of each doc are stored in `state/docs.json` (`{doc_id: {tab_body_id: rev}}`).

## Daily run: steps

0. **Feedback first.** For each doc above, list open comment threads (Claude Docs `query` on utterances under each tab body) and read changes since the stored revision (`read` with `{"kind": "view", "sinceRev": <rev>}`). For each comment: act on it (override, thesis change, watch-list change, preference, question), reply in its thread with what you did in one or two sentences, and resolve it. A comment on a forecast row with a number is an override: add `override: {probability, at, note, source: comment}` to that forecast. An inline edit to a thesis statement, kill criterion or watch-list entry is copied to the repository; an inline edit to a probability is treated as an override. Append every change to `feedback/log.md` (date, doc, what John asked, what changed). Store new revisions in `state/docs.json`. Standing preferences about insights go in `feedback/preferences.md` and apply to every later run.
1. `git pull`. Read `forecasts/forecasts.yaml`, `theses/*.yaml`, `watchlist/companies.csv`, `scores/recalibration.json`, `feedback/preferences.md`, and the last 5 files in `insights/`.
2. **Resolve judged forecasts** whose `resolves_by` is today or earlier (and any whose outcome is already certain). Use the `resolution.guidance`. Open the primary source (company release, regulator, official data). Set `status: resolved`, `outcome: 1|0`, `resolved_at`, and `evidence` with the URL. If the event did not happen or the data does not exist on the stated basis, set `status: void` with the reason. Never change `probability`.
3. **Pre-register events** in the next 7 days that touch a thesis, a contrarian bet or a watch-list company (results, central banks, data releases, regulatory decisions). For each, add 1–3 forecasts with:
   - `kind: event`, a specific and checkable `statement` (a number and a threshold, or a yes/no outcome),
   - `probability_raw` from base rates and the current consensus, then `probability` = the calibrated value (step 6),
   - `reasoning` in 1–3 sentences: the base rate, the consensus, and why you differ from it if you do,
   - `expected` (what you think will happen, in words) and `implications` (what yes and no would mean for which thesis),
   - `resolution`: `auto` with a rule if a public series can resolve it (see `scripts/resolve_forecasts.py`), otherwise `judged` with guidance.
   Forecasts must be written **before** the event. Use ids like `EV-YYYYMMDD-<company>-<n>`.
4. **Update theses.** For each thesis touched by new information since the last run, append to `evidence_for` or `evidence_against` (date, claim, source). Check every kill criterion. Update `system_conviction` (0–100) with a one-line reason and keep the history in `conviction_history`.
5. **Action cards.** Create `insights/cards/YYYY-MM-DD-<thesis>.md` only when a rule in the plan fires: a kill criterion is hit; conviction moves 15 points or more; a new thesis scores 70 or more; a catalyst resolves against the pre-registered expectation. Each card: what changed (source), the rule, the plan written in advance, the strongest counter-argument, what would reverse it. Never place trades.
6. **Calibration.** If `scores/recalibration.json` has `active: true`, set `probability = sigmoid(k * logit(probability_raw) + b)` for every new system forecast and keep both fields. If not active, `probability = probability_raw`.
7. Run `python -m unittest discover -s tests` and `python scripts/score_forecasts.py`. Commit with a message like `Daily run YYYY-MM-DD: N resolved, M pre-registered`, then push to `main`.
8. **Insights.** Write `insights/YYYY-MM-DD.md` with at most 8 bullets, most important first: action cards; forecasts resolved (hit or miss, and the Brier contribution); kill criteria hit or close; new pre-registered expectations for the coming days; one line on anything surprising. No filler. If nothing material happened, write one line saying so.
9. If the Claude Docs tools are available, insert the same bullets at the top of the "Signal Desk: insights" doc under a dated heading (newest first).
10. **Refresh the dashboard** (private Dashboard artifact, URL in the table below). Run `python scripts/build_dashboard.py`; it writes one JSON file per source into `dashboard/`. For each file, in this order: upload it with the Artifact tool (`action: publish`, `url` = the dashboard URL, `file_path` = the file, `asset: true`; one call per file); then, with the ArtifactData tool, `get` collection `datasets`, doc_id = the file's stem, and `update` it with `if_version` = that version and data `{"source": {"kind": "file", "url": "<the upload's /_blob/ url>", "name": "<file name>"}, "updated": {"at": "<now, ISO 8601 UTC>", "by": "Signal Desk daily run"}}`. A batch of updates is fine once all uploads are done. Never change `files/index.html` or the dataset ids in a daily run; layout changes are made in a chat with John, and the page's source is kept in `dashboard/page/index.html`. If the build writes a file for a source the dashboard does not have yet, report it rather than creating the source. If an upload fails, leave that source as it was and report it. Then delete each source's previous upload (Artifact `action: delete`, `url`, `path` = the old asset id) only after its update succeeded. Commit the `dashboard/` folder with the rest of the run.
11. Finish the run with the bullets as the final message.

## Weekly review: steps

1. Everything in the daily run's steps 1–2.
2. Read `scores/summary.md`. Report the Brier score, calibration by bin, and which theses, engines and forecast kinds score best and worst.
3. For each thesis: update `system_conviction`; mark theses whose evidence has turned against them; propose a rewrite or closure (status `closed` with a note) when the kill criteria or the evidence say so.
4. Look for one new contrarian bet: a consensus position (positioning surveys, valuations, flows) that the evidence now contradicts. Add it as a draft thesis with 2–3 forecasts only if it passes the test in the plan (measurable consensus, evidence, dated catalyst).
5. **Overrides.** Compare John's overrides with the system on the same resolved forecasts. If he scores better on 10 or more, start blending: new system forecasts in that kind or theme become 50/50 averages of the system's view and the median of his recent overrides' direction, and say so in the summary. Remove the blend if the advantage disappears.
6. **First Sunday of the month:** post-mortem on every resolved miss (Brier contribution above 0.36), each tagged with one cause: data missing, data wrong, interpretation wrong, right view but wrong timing, or chance. Write the counts and the fix for the most common cause.
7. **First Sunday of January, April, July and October:** reweight the conviction components (evidence balance, variant gap, catalyst clarity, management credibility, macro fit) towards those whose changes best predicted resolved outcomes; review the watch list, the tracked funds and the position-size bands.
8. Write `insights/weekly/YYYY-WW.md`: scores, calibration, what to change, and decisions John may want to make (at most 5 bullets). Refresh the dashboard as in daily-run step 10. Commit, push, and post to the Insights log tab as in the daily run.

## Rules

- An event forecast must have `made_at` before `event_date`; the daily run voids any that do not.
- A forecast is never edited after `made_at`. A changed view is a new forecast with a new id that references the old one in `revises`.
- John's overrides go in `override: {probability, at, note}`. Both the system and the override are scored.
- Every number needs a source URL. Prefer primary sources.
- Probabilities between 0.03 and 0.97. Prefer base rates and market pricing (futures, options, consensus) as the starting point.
- Models: never use Fable 5.1. Use Opus 5.5 for the weekly review and hard synthesis; Sonnet or Haiku for routine extraction where a choice exists.
- Never trade, never publish anything publicly, and never write personal data outside this private repository.
