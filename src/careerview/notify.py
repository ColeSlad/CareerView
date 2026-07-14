from __future__ import annotations

import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

from careerview.models import Listing

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def _format_posted(date_posted: int | None) -> str:
    if not date_posted:
        return "?"
    return datetime.fromtimestamp(date_posted, tz=timezone.utc).strftime("%Y-%m-%d")


def _sorted_newest_first(listings: list[Listing]) -> list[Listing]:
    return sorted(listings, key=lambda listing: listing.date_posted or 0, reverse=True)


def build_subject(listings: list[Listing]) -> str:
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"🚀 {len(listings)} new SWE internships — {date_str}"


def build_html(listings: list[Listing]) -> str:
    rows = []
    for listing in _sorted_newest_first(listings):
        term = escape(", ".join(listing.terms)) if listing.terms else "?"
        loc = escape(", ".join(listing.locations)) if listing.locations else "?"
        rows.append(
            "<tr>"
            f"<td>{escape(listing.company)}</td>"
            f"<td>{escape(listing.title)}</td>"
            f"<td>{loc}</td>"
            f"<td>{term}</td>"
            f"<td>{_format_posted(listing.date_posted)}</td>"
            f'<td><a href="{escape(listing.url)}">Apply</a></td>'
            "</tr>"
        )
    return (
        "<html><body>"
        "<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse'>"
        "<tr><th>Company</th><th>Role</th><th>Location</th><th>Term</th><th>Posted</th><th>Apply</th></tr>"
        + "".join(rows)
        + "</table></body></html>"
    )


def build_plaintext(listings: list[Listing]) -> str:
    lines = []
    for listing in _sorted_newest_first(listings):
        loc = ", ".join(listing.locations) if listing.locations else "?"
        lines.append(f"{listing.company} — {listing.title} ({loc}) — {listing.url}")
    return "\n".join(lines)


def send_digest(listings: list[Listing], *, smtp_user: str, smtp_password: str, to_addr: str) -> bool:
    """Sends exactly one digest email covering all new listings. No-ops (returns False) if empty."""
    if not listings:
        return False

    message = MIMEMultipart("alternative")
    message["Subject"] = build_subject(listings)
    message["From"] = smtp_user
    message["To"] = to_addr
    message.attach(MIMEText(build_plaintext(listings), "plain"))
    message.attach(MIMEText(build_html(listings), "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(message)

    return True
