"""Record dated central-bank publications before a live decision, never in replay."""

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import requests

from .models import Evidence

SOURCES = {
    "Federal Reserve": "https://www.federalreserve.gov/feeds/press_monetary.xml",
    "ECB": "https://www.ecb.europa.eu/rss/press.html",
}


def collect_macro_evidence(catalog, *, fetch=None, clock=None):
    fetch = fetch or requests.get
    clock = clock or (lambda: datetime.now(timezone.utc))
    statuses = []
    for name, url in SOURCES.items():
        count, eligible = 0, 0
        try:
            response = fetch(
                url, timeout=(5, 10), headers={"User-Agent": "TradingAgents-Research/0.1"}
            )
            response.raise_for_status()
            if len(response.content) > 2_000_000:
                raise ValueError("RSS response exceeds the size limit")
            root = ElementTree.fromstring(response.content)
            if root.tag != "rss":
                raise ValueError("Expected an RSS publication feed")
            received = clock()
            for item in root.findall(".//item")[:100]:
                title = (item.findtext("title") or "").strip()
                date = item.findtext("pubDate") or item.findtext(
                    "{http://purl.org/dc/elements/1.1/}date"
                )
                if not title or not date:
                    continue
                try:
                    try:
                        published = parsedate_to_datetime(date)
                    except (ValueError, TypeError):
                        published = datetime.fromisoformat(date.replace("Z", "+00:00"))
                    if published.tzinfo is None:
                        continue
                    published = published.astimezone(timezone.utc)
                except (ValueError, TypeError):
                    continue
                if not received - timedelta(days=7) <= published <= received:
                    continue
                eligible += 1
                record = Evidence(
                    kind="macro",
                    published_at=published,
                    received_at=received,
                    source=name,
                    summary=(
                        title[:1300]
                        + "\n"
                        + (item.findtext("link") or url)[:400]
                        + "\nCentral-bank publication only; not a complete economic calendar."
                    ),
                )
                count += catalog.append(record)
            statuses.append(
                {
                    "source": name,
                    "status": "recorded" if eligible else "no_recent_items",
                    "added": count,
                    "calendar_coverage": "unverified",
                }
            )
        except (requests.RequestException, ElementTree.ParseError, ValueError) as exc:
            statuses.append(
                {
                    "source": name,
                    "status": "unavailable",
                    "added": 0,
                    "error_type": type(exc).__name__,
                    "calendar_coverage": "unverified",
                }
            )
    return statuses
