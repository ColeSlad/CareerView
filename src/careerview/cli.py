from __future__ import annotations

import argparse
import os
import sys

from careerview import health, notify, store
from careerview.config import Config, load_config
from careerview.filters import is_relevant
from careerview.poller import run_poll
from careerview.sources.adzuna import AdzunaSource
from careerview.sources.ashby import AshbySource
from careerview.sources.base import Source
from careerview.sources.greenhouse import GreenhouseSource
from careerview.sources.lever import LeverSource
from careerview.sources.oraclecloud import OracleCloudSource
from careerview.sources.simplify import SimplifySource
from careerview.sources.vanshb03 import Vanshb03Source
from careerview.sources.workday import WorkdaySource


def _build_sources(config: Config) -> list[Source]:
    sources: list[Source] = [
        SimplifySource(repo=config.simplify_repo, branch=config.simplify_branch, name="simplify"),
        SimplifySource(repo=config.pittcsc_repo, branch=config.pittcsc_branch, name="pittcsc"),
        Vanshb03Source(repo=config.vanshb03_repo, branch=config.vanshb03_branch),
    ]

    include_kw = config.relevance.include_title_keywords
    exclude_kw = config.relevance.exclude_title_keywords

    for slug, company_name in config.companies.get("greenhouse", {}).items():
        sources.append(GreenhouseSource(slug, company_name, include_kw, exclude_kw))
    for slug, company_name in config.companies.get("lever", {}).items():
        sources.append(LeverSource(slug, company_name, include_kw, exclude_kw))
    for slug, company_name in config.companies.get("ashby", {}).items():
        sources.append(AshbySource(slug, company_name, include_kw, exclude_kw))
    for tenant, wd in config.companies.get("workday", {}).items():
        sources.append(WorkdaySource(tenant, wd["wd"], wd["site"], wd["name"], include_kw, exclude_kw))
    for tenant, oc in config.companies.get("oraclecloud", {}).items():
        sources.append(OracleCloudSource(tenant, oc["dc"], oc["site"], oc["name"], include_kw, exclude_kw))

    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if app_id and app_key:
        sources.append(
            AdzunaSource(
                app_id=app_id,
                app_key=app_key,
                country=config.adzuna_country,
                keywords=config.adzuna_keywords,
                locations=config.adzuna_locations,
                include_keywords=include_kw,
                exclude_keywords=exclude_kw,
            )
        )
    else:
        print("(skipping Adzuna: ADZUNA_APP_ID / ADZUNA_APP_KEY not set)")

    return sources


def _print_listings(listings, heading: str) -> None:
    print(f"\n{heading} ({len(listings)})")
    for listing in listings:
        loc = ", ".join(listing.locations) if listing.locations else "?"
        print(f"  [{listing.source:9}] {listing.company:25.25} | {listing.title:40.40} | {loc:25.25} | {listing.url}")


def cmd_poll(args: argparse.Namespace) -> int:
    config = load_config()
    sources = _build_sources(config)

    result = run_poll(sources)
    print(f"Fetched {result.fetched_count} listings from {len(sources)} source(s) after dedup")

    if result.is_first_run:
        print(f"First run: seeding {len(result.all_listings)} listings as already-seen (no email)")
        relevant_new = []
    else:
        # A previously discovered role may become eligible after a filter fix or
        # a location update. Discovery alone must not consume its email alert.
        relevant_new = [
            listing for listing in result.all_listings.values()
            if listing.uid not in result.retained_uids
            and not listing.emailed and is_relevant(listing, config.relevance)
        ]
        print(f"New listings this run: {len(result.new_listings)}; awaiting alert: {len(relevant_new)}")
        _print_listings(relevant_new, "Relevant listings awaiting an alert")

    if args.dry_run:
        print("\n(dry run — nothing written, no email sent)")
        return 0

    meta = store.load_meta()
    meta["poll_health"] = health.build_health(
        meta, result.source_checks, result.started_at, result.finished_at, result.duration_seconds)
    poll_health = meta["poll_health"]
    poll_health["email_status"] = "not_needed" if args.email else "not_requested"
    exit_code = 1 if poll_health["status"] in {"failed", "no_sources"} else 0

    if args.email and relevant_new:
        smtp_user = os.environ.get("GMAIL_ADDRESS")
        smtp_password = os.environ.get("GMAIL_APP_PASSWORD")
        to_addr = os.environ.get("NOTIFY_TO")
        if not (smtp_user and smtp_password and to_addr):
            print(
                "\nerror: --email requires GMAIL_ADDRESS, GMAIL_APP_PASSWORD, NOTIFY_TO to be set",
                file=sys.stderr,
            )
            poll_health["email_status"] = "failed"
            exit_code = 1
        else:
            try:
                notify.send_digest(relevant_new, smtp_user=smtp_user, smtp_password=smtp_password, to_addr=to_addr)
            except Exception as exc:
                print(f"\nerror: email delivery failed ({type(exc).__name__}); alerts remain pending", file=sys.stderr)
                poll_health["email_status"] = "failed"
                exit_code = 1
            else:
                print(f"\nSent digest email for {len(relevant_new)} listing(s) to {to_addr}")
                poll_health["email_status"] = "sent"
                for listing in relevant_new:
                    result.all_listings[listing.uid].emailed = True
    elif args.email:
        print("\n(--email set but nothing relevant to send)")

    store.save_listings(result.all_listings)
    meta.update(last_run=result.finished_at, fetched_count=result.fetched_count)
    store.save_meta(meta)
    print(f"Wrote {len(result.all_listings)} listings to data/listings.json")
    print(health.summary(meta, store.now_ts(), config.poll_stale_after_minutes))

    return exit_code


def cmd_health(args: argparse.Namespace) -> int:
    config = load_config()
    meta = store.load_meta()
    now = store.now_ts()
    print(health.details(meta, now, config.poll_cadence_minutes, config.poll_stale_after_minutes))
    for row in health.sorted_sources(meta):
        if row["error"]:
            print(f"  FAILED {row['company']} ({row['key']}): {row['error']} | "
                  f"last success {health.age(row['last_success_at'], now)} | "
                  f"{row['consecutive_failures']} consecutive failure(s)")
    return int(health.needs_attention(meta, now, config.poll_stale_after_minutes))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="careerview")
    subparsers = parser.add_subparsers(dest="command")

    poll = subparsers.add_parser("poll", help="Fetch sources and show relevant listings")
    poll.add_argument("--dry-run", action="store_true", help="Fetch and print without writing state or emailing")
    poll.add_argument("--email", action="store_true", help="Email a digest of newly-found relevant listings")
    poll.set_defaults(func=cmd_poll)

    health_parser = subparsers.add_parser("health", help="Show saved polling health (does not fetch sources)")
    health_parser.set_defaults(func=cmd_health)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not getattr(args, "command", None):
        from careerview.tui.app import run as run_tui

        run_tui()
        return

    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
