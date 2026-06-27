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
IMAGE_BASE_URL = "https://images.metadata.sky.com/pd-image"

LOGO_INDEX_API = "https://api.github.com/repos/tv-logo/tv-logos/contents/countries/united-kingdom"
LOGO_BASE_URL = "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/united-kingdom"

# Undocumented API - identify ourselves and don't hammer it.
USER_AGENT = "sky-epg-xmltv/1.0 (+https://github.com/Permanently/sky-epg-xmltv)"
DEFAULT_REQUEST_DELAY = 0.4


def _get_json(url: str, retries: int = 3, delay: float = 1.0) -> dict | list | None:
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


# ---- Channel logos (tv-logo/tv-logos) -------------------------------------

def fetch_logo_index() -> set[str]:
    """Live filenames in tv-logo/tv-logos' UK directory, e.g. {'bbc-one-uk.png', ...}."""
    data = _get_json(LOGO_INDEX_API)
    if not isinstance(data, list):
        return set()
    return {item["name"] for item in data if item.get("type") == "file" and item["name"].endswith(".png")}


LOGO_OVERRIDES = {
    # Sky's abbreviated/rebranded names don't slugify cleanly - map the exceptions by hand.
    "discovery": "discovery-channel",
    "nat geo": "national-geographic",
    "natgeo wild": "national-geographic-wild",
    "id": "investigation-discovery",
    "crime+inv": "crime-investigation",
    "sky one": "sky-max",
    "comedycent": "comedy-central",
}


def _split_camel(s: str) -> str:
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", s)
    return s


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _override_key(name: str) -> str:
    s = name.strip().lower().replace(".", " ")
    s = re.sub(r"\s*\+\s*1\s*$", "", s)
    s = re.sub(r"\s*hd\s*$", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _bbc_region_logo(name: str, logo_index: set[str]) -> str | None:
    lname = name.lower()
    for brand, generic in (("bbc one", "bbc-one-uk.png"), ("bbc two", "bbc-two-uk.png")):
        if not lname.startswith(brand):
            continue
        prefix = brand.replace(" ", "-")
        candidate = None
        if "scot" in lname:
            candidate = f"{prefix}-scotland-uk.png"
        elif "wal" in lname or "cymru" in lname:
            candidate = f"{prefix}-wales-uk.png"
        elif "northern ireland" in lname or " ni " in f" {lname} ":
            candidate = f"{prefix}-northern-ireland-uk.png"
        if candidate and candidate in logo_index:
            return candidate
        return generic  # English regions, or a brand with no region-specific variant
    return None


def _logo_candidates(name: str):
    cleaned = _split_camel(name)
    cleaned = re.sub(r"\s*\+\s*1\s*$", " plus", cleaned)
    cleaned = re.sub(r"\bHD\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("&", " and ").replace(".", " ")
    yield _slugify(cleaned)
    yield _slugify(re.sub(r"([A-Za-z])(\d)", r"\1 \2", cleaned))
    yield _slugify(re.sub(r"(\d)([A-Za-z])", r"\1 \2", cleaned))


def match_logo(name: str, logo_index: set[str]) -> str | None:
    """Best-effort channel name -> tv-logos filename. Returns None on no match -
    callers should skip the <icon> entirely rather than guess at a broken URL."""
    region = _bbc_region_logo(name, logo_index)
    if region:
        return region

    override = LOGO_OVERRIDES.get(_override_key(name))
    if override:
        fname = f"{override}-uk.png"
        if fname in logo_index:
            return fname

    for cand in _logo_candidates(name):
        fname = f"{cand}-uk.png"
        if fname in logo_index:
            return fname

    return None


def logo_url(name: str, logo_index: set[str]) -> str | None:
    fname = match_logo(name, logo_index)
    return f"{LOGO_BASE_URL}/{fname}" if fname else None


# ---- XMLTV building --------------------------------------------------------

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


def channel_block(name: str, sid: str, icon_url: str | None = None) -> list[str]:
    lines = [
        f'  <channel id="{channel_id(sid)}">',
        f"    <display-name>{escape_xml(name)}</display-name>",
    ]
    if icon_url:
        lines.append(f'    <icon src="{escape_xml(icon_url)}" />')
    lines.append("  </channel>")
    return lines


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

    programmeuuid = event.get("programmeuuid")
    if programmeuuid:
        lines.append(f'    <icon src="{IMAGE_BASE_URL}/{programmeuuid}/16-9" />')
        lines.append(f'    <icon src="{IMAGE_BASE_URL}/{programmeuuid}/3-4" />')

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


def write_xmltv(path: str, channels: dict[str, dict], sid_events: dict[str, list[dict]]) -> int:
    """channels: {name: {"sid": str, "icon": str | None}}.
    sid_events is a shared {sid: [event, ...]} cache, fetched once and reused across regions."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append(
        '<tv generator-info-name="sky-epg-xmltv" '
        'generator-info-url="https://github.com/Permanently/sky-epg-xmltv">'
    )

    for name, info in channels.items():
        lines.extend(channel_block(name, info["sid"], info.get("icon")))

    count = 0
    for name, info in channels.items():
        sid = info["sid"]
        for event in sid_events.get(sid, []):
            block = programme_block(sid, event)
            if block:
                lines.extend(block)
                count += 1

    lines.append("</tv>")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return count
