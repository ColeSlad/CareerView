# CareerView

A terminal tracker for software engineering internship openings. A GitHub Actions
job checks a set of job sources on a schedule, emails you a digest when it finds
new relevant internships, and a local terminal UI lets you browse, filter,
and track your application pipeline.

## How it works

```
GitHub Actions (cron every ~15 min)
  └─ careerview poll --email
       fetch all sources → dedup → diff against known listings
         → new relevant roles → one email digest
         → commit updated data/ back to this repo
                     │
        data/listings.json  (canonical, lives in this repo)
                     │ git pull
                     ▼
  Local:  careerview  (Textual TUI)
       browse / filter / mark applied / open in browser
```

The cloud workflow owns `data/listings.json` (what's out there). Your Mac owns a
local SQLite file (your own status/notes on each listing). The two never write to
the same thing, so there's no syncing to worry about.

Email digests group openings under each company's name and listing count in both
HTML and plain text. Companies appear by their newest posting, with roles sorted
newest first within each company.

### Sources

- [SimplifyJobs](https://github.com/SimplifyJobs/Summer2026-Internships) — community-maintained internship list
- **459 company boards** across Greenhouse, Lever, Ashby, Workday, and Oracle Cloud — configured in `companies.yaml`, with eight sources fetched concurrently. See the [full company catalog and coverage gaps](docs/watchlist.md).
- **Adzuna** — a broader keyword search, for coverage beyond the watchlist (optional; skipped automatically if not configured)

An open role stays eligible for its first email until it is actually emailed, even
if an earlier poll discovered it while its location failed the relevance filter.
The first-ever poll still establishes a silent baseline. Direct ATS links are
deduplicated across community feeds, and email history follows the posting when
the selected feed changes. City-only US locations such as `SF`, `San Francisco`,
and `New York City` are recognized; Ashby country metadata is also preserved.

ATS adapters exclude clearly non-software internship titles from the Software
category (for example, accounting and mechanical engineering), while retaining
ambiguous engineering internships. This is a heuristic, not a full job-description
classifier. The US/Remote filter continues to include remote postings; check each
posting's geographic and work-authorization requirements.

Check every configured company board without sending email or modifying listing state:

```bash
PYTHONPATH=src .venv/bin/python scripts/audit_watchlist.py --output /tmp/watchlist-health.json
```

The audit reports failed boards by company and exits nonzero if any fail. A working
board with zero matching internships is still watched for future openings.

## Setup

```bash
cd careerview
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

> **Note:** use `pip install .`, not `pip install -e .`. The editable install's
> `.pth` mechanism is unreliable on this Python/macOS combination — it can work
> right after installing and then silently stop working in a new terminal. A
> normal install doesn't have that problem. The one tradeoff: if the code
> changes, you need to re-run `pip install .` once to pick it up.

## Usage

### Browse listings (the TUI)

```bash
careerview
```

Run this from the repo root — it reads `config.yaml`, `companies.yaml`, and
`data/listings.json` relative to your current directory, and does a best-effort
`git pull` on startup to grab whatever the cloud watcher has found since you last
looked.

| Key | Action |
|---|---|
| `/` | Focus search (matches company or title) |
| `↑`/`↓` | Move selection |
| `Enter` | Show full listing details |
| `o` | Open the listing's apply URL in your browser |
| `a` | Mark **Applied** |
| `i` | Mark **Interested** |
| `s` | Mark **Skipped** |
| `n` | Add/edit a note |
| `1` | Toggle "Active only" filter |
| `2` | Toggle "Relevant only" filter (category + intern-title match) |
| `3` | Toggle "US/Remote only" filter |
| `4` | Cycle status filter (all → new → interested → applied → skipped) |
| `5` | Cycle inbox view (all → new since last visit → unread) |
| `m` | Mark the selected listing reviewed |
| `Shift+m` | Mark all listings in the current filtered view reviewed |
| `r` | Pull the latest listings and refresh the table |
| `h` | Open polling health: last checks, failed boards, and source history |
| `q` | Quit |

The first launch with inbox tracking establishes a baseline from the current
listings. On later visits, **New since last visit** shows listings that were not
present on any previous visit, including arrivals found by pressing `r`. It uses
listing IDs, so older posting dates and missing dates do not hide new arrivals.
Refreshing keeps the current visit's new markers.

**Unread** keeps new arrivals available across visits until you review them.
Opening details or an apply link, changing application status, saving a note, or
pressing `m` marks a listing reviewed. `Shift+m` reviews only the listings matching
the current view and filters. The new/unread counts also respect your search and
application filters. A reviewed arrival stays in "New since last visit" for the
rest of that visit, labeled "New · read".

Inbox review state is separate from the existing **New** application status,
which means you have not assigned an application status. Your statuses, notes,
and inbox history are stored locally in `~/.local/share/careerview/status.db` and
are never committed to the repo.

### Polling health

The health line above the listings shows when the latest saved poll finished,
how many sources succeeded, and whether any failed. It warns **STALE** after
45 minutes without a recorded poll. The warning updates while the TUI is open;
press `r` to pull the newest cloud results. A failed pull is shown separately so
an old local snapshot does not look like a successful sync.

Press `h` for the searchable health dashboard. Failed sources appear first, with
the last successful check, fetch duration, listing count, error type or HTTP
status, and consecutive failure count. Select a row for exact timestamps. A
successful fetch with zero listings is healthy; a failed fetch has no count.
Counts are returned listings before cross-source deduplication. The summary
distinguishes partial failures from a fully successful poll.

You can also inspect the saved snapshot without launching the TUI:

```bash
careerview health
```

This command does not poll or pull from GitHub. It exits with status 1 when the
snapshot is stale, degraded, or has no recorded health. Health is stored alongside
listings in `data/meta.json`, so existing snapshots show "Health not recorded"
until the next poll with the updated code. Last-success history starts then.

Failed sources retain their previous listings and email history until a later
successful fetch; retained rows do not generate new alerts while the source is
failing. Poll diagnostics are saved even if email delivery fails, and pending
alerts remain eligible for a later run. If all sources fail, the poll exits
nonzero and the workflow still commits its diagnostics.

Set `poll.stale_after_minutes` in `config.yaml` to change the warning threshold.
This does not change the cloud schedule. The dashboard reports saved polling
results, not a live connection to GitHub or an external outage notification.

### Manually run a poll

```bash
careerview poll --dry-run          # fetch + show what's relevant, write nothing
careerview poll                    # fetch, write data/listings.json, no email
careerview poll --email            # also email a digest of anything new + relevant
```

`--email` requires `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, and `NOTIFY_TO` to be set
as environment variables (see below).

## Configuration

- **`config.yaml`** — which Simplify repo/branch to pull, the relevance filter
  (category, US/remote, intern-title keywords), and Adzuna search settings.
- **`companies.yaml`** — the Greenhouse/Lever/Ashby company watchlist. Each entry
  maps a company's job-board slug to a display name, e.g.:
  ```yaml
  greenhouse:
    stripe: Stripe
  lever:
    palantir: Palantir
  ashby:
    openai: OpenAI
  ```

## Cloud watcher (GitHub Actions)

The four `.github/workflows/poll-*.yml` schedules target minutes `:07`, `:22`,
`:37`, and `:52` each hour and call `_poll-run.yml` to run `careerview poll --email`
and commit the updated `data/` back to the repo. GitHub may delay or skip scheduled
runs, so the 15-minute target is not guaranteed; use the health view to check
actual freshness. It needs these repository secrets
(Settings → Secrets and variables → Actions):

| Secret | Required | Purpose |
|---|---|---|
| `GMAIL_ADDRESS` | yes | Gmail address to send from |
| `GMAIL_APP_PASSWORD` | yes | [App password](https://myaccount.google.com/apppasswords) (not your regular login — requires 2-Step Verification) |
| `NOTIFY_TO` | yes | Where the digest email goes |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | no | Free key from [developer.adzuna.com](https://developer.adzuna.com) — Adzuna is skipped automatically if unset |

The repo should be **public** so the workflow gets unlimited free Actions minutes
(private repos are capped at ~2,000 min/month on the free plan).

You can trigger a run manually from the Actions tab ("Run workflow") or via
`gh workflow run poll-1.yml`.

## Tests

Run the alert eligibility, source parsing, inbox persistence, and headless UI tests
against the source checkout:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```
