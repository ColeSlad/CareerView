from __future__ import annotations

import argparse
import sys

from careerview.config import load_config
from careerview.filters import is_relevant
from careerview.sources.simplify import SimplifySource


def _print_listings(listings, heading: str) -> None:
    print(f"\n{heading} ({len(listings)})")
    for listing in listings:
        loc = ", ".join(listing.locations) if listing.locations else "?"
        print(f"  [{listing.source:9}] {listing.company:25.25} | {listing.title:40.40} | {loc:25.25} | {listing.url}")


def cmd_poll(args: argparse.Namespace) -> int:
    config = load_config()
    source = SimplifySource(repo=config.simplify_repo, branch=config.simplify_branch)

    print(f"Fetching from {source.name}...")
    fetched = source.fetch()
    print(f"  fetched {len(fetched)} raw listings")

    relevant = [listing for listing in fetched if is_relevant(listing, config.relevance)]
    _print_listings(relevant, "Relevant listings")

    if args.dry_run:
        print("\n(dry run — nothing written, no email sent)")

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
