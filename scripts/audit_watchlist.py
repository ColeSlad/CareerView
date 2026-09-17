"""Check configured company boards without changing listings or sending email.

Run from the repository root:
    PYTHONPATH=src .venv/bin/python scripts/audit_watchlist.py --output /tmp/watchlist-health.json
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

from careerview.cli import _build_sources
from careerview.config import load_config
from careerview.filters import is_relevant
from careerview.sources.base import fetch_with_retry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    config = load_config()
    sources = [source for source in _build_sources(config) if hasattr(source, 'company_name')]

    def check(source):
        started = monotonic()
        row = {'company': source.company_name, 'provider': source.name,
               'board': getattr(source, 'slug', getattr(source, 'tenant', ''))}
        try:
            listings = fetch_with_retry(source)
            row.update(status='ok', internships=len(listings),
                       matching_internships=sum(is_relevant(job, config.relevance) for job in listings))
        except Exception as exc:
            row.update(status='error', error=str(exc))
        row['seconds'] = round(monotonic() - started, 2)
        print(f"{row['status']:5} {row['provider']}:{row['board']} — {row['company']}"
              f" — {row.get('matching_internships', 0)} matching internships", flush=True)
        if row['status'] == 'error':
            print(f"      {row['error']}", flush=True)
        return row

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(check, sources))
    failures = sum(row['status'] == 'error' for row in rows)
    report = {'checked_at': datetime.now(timezone.utc).isoformat(),
              'companies': len(rows), 'failures': failures, 'results': rows}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(f"\n{len(rows)} companies checked; {failures} failed.")
    return int(failures > 0)


if __name__ == '__main__':
    raise SystemExit(main())
