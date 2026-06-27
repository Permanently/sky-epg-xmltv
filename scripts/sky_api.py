"""
Shared helpers for talking to Sky's undocumented EPG backend and building
XMLTV output. Used by discover_channels.py, fetch_epg.py and
build_all_guides.py - keep this as the single source of truth for both.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

SCHEDULE_API = "https://awk.epgsky.com/hawk/linear/schedule"
SERVICES_API = "https://awk.epgsky.com/hawk/linear/services"

# Undocumented API - identify ourselves and don't hammer it.
USER_AGENT = "sky-epg-xmltv/1.0 (+https://github.com/Permanently/sky-epg-xmltv)"
DEFAULT_REQUEST_DELAY = 0.4


def _get_json(url: str, retries: int = 3, delay: float = 1.0) -> dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            print(f"  HTTP {e.code} for {url} (attempt {attempt}/{retries})", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"  Error fetching {url}: {e} (attempt {attempt}/{retries})", file=sys.stderr)
        time.sleep(delay)
    return None


def fetch_services(bouquet: int, sub_bouquet: int) -> list[dict]:
    data = _get_json(f"{SERVICES_API}/{bouquet}/{sub_bouquet}")
    return (data or {}).get("services", [])


def fetch_day(date_str: str, sid: str) -> dict | None:
    return _get_json(f"{SCHEDULE_API}/{date_str}/{sid}")


def date_range(days: int) -> list[str]:
    start = datetime.now(timezone.utc).date()
    return [(start + timedelta(days=offset)).strftime("%Y%m%d") for offset in range(days)]


def fetch_sid_events(sid: str, days: int, delay: float = DEFAULT_REQUEST_DELAY) -> list[dict]:
    events: list[dict] = []
    seen_eids: set[str] = set()

    for date_str in date_range(days):
        data = fetch_day(date_str, sid)
        time.sleep(delay)
        if not data or "schedule" not in data:
            continue
        for sched in data["schedule"]:
            for event in sched.get("events", []):
                eid = event.get("eid")
                # Sky's per-day windows overlap slightly at the edges - dedupe on eid.
                if eid and eid in seen_eids:
                    continue
                if eid:
                    seen_eids.add(eid)
                events.append(event)

    return events


def xmltv_time(epoch_seconds: int) -> str:
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).strftime("%Y%m%d%H%M%S +0000")


def clean_synopsis(text: str) -> str:
    # Sky embeds markers like [S] [HD] [AD] inline in the synopsis - strip them.
    if not text:
        return ""
    return re.sub(r"\s*\[[^\]]*\]\s*", " ", text).strip()


def escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def channel_id(sid: str) -> str:
    return f"{sid}.sky.uk"


def channel_block(name: str, sid: str) -> list[str]:
    return [
        f'  <channel id="{channel_id(sid)}">',
        f"    <display-name>{escape_xml(name)}</display-name>",
        "  </channel>",
    ]


def programme_block(sid: str, event: dict) -> list[str]:
    start = event.get("st")
    duration = event.get("d", 0)
    if start is None:
        return []
    stop = start + duration

    lines = [
        f'  <programme start="{xmltv_time(start)}" stop="{xmltv_time(stop)}" channel="{channel_id(sid)}">',
        f'    <title lang="en">{escape_xml(event.get("t", "Unknown"))}</title>',
    ]

    synopsis = clean_synopsis(event.get("sy", ""))
    if synopsis:
        lines.append(f'    <desc lang="en">{escape_xml(synopsis)}</desc>')

    season = event.get("seasonnumber")
    episode = event.get("episodenumber")
    if episode:  # Sky uses 0 to mean "no specific episode number"
        season_part = str(season - 1) if season else ""
        lines.append(f'    <episode-num system="xmltv_ns">{season_part}.{episode - 1}.</episode-num>')

    if event.get("hd"):
        lines.append("    <video><quality>HD</quality></video>")

    if event.get("s"):
        lines.append('    <subtitles type="teletext" />')

    if event.get("new"):
        lines.append("    <new />")

    lines.append("  </programme>")
    return lines


def write_xmltv(path: str, channels: dict[str, str], sid_events: dict[str, list[dict]]) -> int:
    """sid_events is a shared {sid: [event, ...]} cache, fetched once and reused across regions."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append(
        '<tv generator-info-name="sky-epg-xmltv" '
        'generator-info-url="https://github.com/Permanently/sky-epg-xmltv">'
    )

    for name, sid in channels.items():
        lines.extend(channel_block(name, sid))

    count = 0
    for name, sid in channels.items():
        for event in sid_events.get(sid, []):
            block = programme_block(sid, event)
            if block:
                lines.extend(block)
                count += 1

    lines.append("</tv>")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return count
