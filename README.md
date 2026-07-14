# CareerView

A terminal tracker for software engineering internship openings. A GitHub Actions
job checks a set of job sources on a schedule, emails you a digest the moment a
genuinely new internship appears, and a local terminal UI lets you browse, filter,
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

### Sources

- [SimplifyJobs](https://github.com/SimplifyJobs/Summer2026-Internships) — community-maintained internship list
- **Greenhouse / Lever / Ashby** — pulled directly from each company's public job board API, for companies you list in `companies.yaml`
- **Adzuna** — a broader keyword search, for coverage beyond the watchlist (optional; skipped automatically if not configured)

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
| `q` | Quit |

Your statuses and notes are stored locally in `~/.local/share/careerview/status.db`
and are never committed to the repo.

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

`.github/workflows/poll.yml` runs `careerview poll --email` every ~15 minutes and
commits the updated `data/` back to the repo. It needs these repository secrets
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
`gh workflow run poll.yml`.
