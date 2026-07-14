from __future__ import annotations

import argparse
import sys

from careerview import store
from careerview.config import load_config
from careerview.filters import is_relevant
from careerview.poller import run_poll
from careerview.sources.simplify import SimplifySource


def _print_listings(listings, heading: str) -> None:
    print(f"\n{heading} ({len(listings)})")
    for listing in listings:
        loc = ", ".join(listing.locations) if listing.locations else "?"
        print(f"  [{listing.source:9}] {listing.company:25.25} | {listing.title:40.40} | {loc:25.25} | {listing.url}")


def cmd_poll(args: argparse.Namespace) -> int:
    config = load_config()
    sources = [SimplifySource(repo=config.simplify_repo, branch=config.simplify_branch)]

    result = run_poll(sources)
    print(f"Fetched {result.fetched_count} listings from {len(sources)} source(s) after dedup")

    if result.is_first_run:
        print(f"First run: seeding {len(result.all_listings)} listings as already-seen (no email)")
    else:
        relevant_new = [listing for listing in result.new_listings if is_relevant(listing, config.relevance)]
        print(f"New listings this run: {len(result.new_listings)} (relevant: {len(relevant_new)})")
        _print_listings(relevant_new, "New relevant listings")

    if args.dry_run:
        print("\n(dry run — nothing written, no email sent)")
    else:
        store.save_listings(result.all_listings)
        store.save_meta({"last_run": store.now_ts(), "fetched_count": result.fetched_count})
        print(f"\nWrote {len(result.all_listings)} listings to data/listings.json")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="careerview")
    subparsers = parser.add_subparsers(dest="command")

    poll = subparsers.add_parser("poll", help="Fetch sources and show relevant listings")
    poll.add_argument("--dry-run", action="store_true", help="Fetch and print without writing state or emailing")
    poll.set_defaults(func=cmd_poll)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not getattr(args, "command", None):
        parser.print_help()
        sys.exit(1)

    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
