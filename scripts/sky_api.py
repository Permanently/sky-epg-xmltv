"""
Shared helpers for talking to Sky's undocumented EPG backend and building
XMLTV output. Used by discover_channels.py, fetch_epg.py and
build_all_guides.py - keep this as the single source of truth for both.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

SCHEDULE_API = "https://awk.epgsky.com/hawk/linear/schedule"
SERVICES_API = "https://awk.epgsky.com/hawk/linear/services"
IMAGE_BASE_URL = "https://images.metadata.sky.com/pd-image"

LOGO_REPO_URL = "https://github.com/tv-logo/tv-logos.git"
LOGO_RAW_BASE = "https://raw.githubusercontent.com/tv-logo/tv-logos/main"
LOGO_SKIP_SUBDIRS = {"hd", "obsolete", "other", "screen-bug"}

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

_STEM_RE = re.compile(r"^(.+)-([a-z]{2,4})\.png$")


def fetch_logo_index() -> set[str]:
    """Every PNG's repo-relative path, e.g. {'countries/united-kingdom/bbc-one-uk.png', ...}.

    Uses a blobless git clone (tree only, no image bytes - ~500KB vs the ~400MB the
    repo's images actually total) rather than GitHub's REST API, since the API's
    anonymous rate limit (60/hr) is shared across a wider IP pool than expected and
    proved unreliable even for a single call in testing."""
    tmp_dir = tempfile.mkdtemp(prefix="tv-logos-")
    try:
        subprocess.run(
            ["git", "clone", "--filter=blob:none", "--no-checkout", "--depth=1", LOGO_REPO_URL, tmp_dir],
            check=True, capture_output=True, timeout=120,
        )
        result = subprocess.run(
            ["git", "-C", tmp_dir, "ls-tree", "-r", "HEAD", "--name-only"],
            check=True, capture_output=True, text=True, timeout=30,
        )
    except Exception as e:  # noqa: BLE001
        print(f"  Failed to fetch logo index: {e}", file=sys.stderr)
        return set()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    paths = set()
    for line in result.stdout.splitlines():
        if not line.endswith(".png") or not line.startswith("countries/"):
            continue
        parts = line.split("/")
        if len(parts) >= 3 and parts[2] in LOGO_SKIP_SUBDIRS:
            continue  # hd/obsolete/other/screen-bug - not real channel logos
        paths.add(line)
    return paths


def build_logo_map(logo_index: set[str]) -> dict[str, list[str]]:
    """Precomputed once: {stem: [matching paths across all countries]}.
    A stem is the filename minus its trailing 2-4 letter country-code suffix, so
    'bbc-one-uk.png' -> stem 'bbc-one'. This O(n) pass means each channel lookup
    afterwards is an O(1) dict get rather than a regex scan of the whole index."""
    mapping: dict[str, list[str]] = {}
    for path in logo_index:
        m = _STEM_RE.match(path.rsplit("/", 1)[-1])
        if m:
            mapping.setdefault(m.group(1), []).append(path)
    return mapping


LOGO_OVERRIDES = {
    # Sky's abbreviated/rebranded names don't slugify cleanly - map the exceptions by hand.
    "discovery": "discovery-channel",
    "nat geo": "national-geographic",
    "natgeo wild": "national-geographic-wild",
    "id": "investigation-discovery",
    "crime+inv": "crime-and-investigation",
    "sky one": "sky-max",
    "comedycent": "comedy-central",
    "5": "channel-5",
    "4": "channel-4",
    "bbc parl": "bbc-parliament",
    "cbeebies": "bbc-cbeebies",
    "cbbc": "bbc-cbbc",
    # Bloomberg - no plain bloomberg-*.png exists in any country; bloomberg-television-us.png
    # is the canonical brand logo and the only unambiguous match.
    "bloomberg": "bloomberg-television",
    # TNT Sports Box Office (Sky abbreviates the channel name heavily)
    "tntsboxoff": "tnt-sports-box-office",
    "tntsboxoff2": "tnt-sports-box-office-2",
    # Sky Cinema - Sky's on-screen names drop "Cinema" entirely
    "sky action": "sky-cinema-action",
    "sky drama": "sky-cinema-drama",
    "sky family": "sky-cinema-family",
    "sky greats": "sky-cinema-greats",
    "sky scfi/hor": "sky-cinema-sci-fi-and-horror",
    "sky thriller": "sky-cinema-thriller",
    "skydocmntrs": "sky-documentaries",
    "skydocumntrs": "sky-documentaries",
    "skyminions": "sky-cinema-animation",
    "skypremiere": "sky-cinema-premiere",
    # Sky Sports - Sky uses the "SkySp" prefix for all Sky Sports channels
    "skysp action": "sky-sports-action",
    "skysp f'ball": "sky-sports-football",
    "skysp f1": "sky-sports-f1",
    "skysp golf": "sky-sports-golf",
    "skysp mix": "sky-sports-mix",
    "skysp news": "sky-sports-news",
    "skysp pl": "sky-sports-premier-league",
    "skysp racing": "sky-sports-racing",
    "skysp tennis": "sky-sports-tennis",
    "skysp+": "sky-sports-plus-hz",  # no plain sky-sports-plus-uk.png; -hz variant exists
    "skyspboxoff": "sky-sports-box-office",
    "skyspcricket": "sky-sports-cricket",
    "skyspmainev": "sky-sports-main-event",
}

LOGO_PATH_OVERRIDES = {
    # Channels where stem-matching can't resolve cleanly because the same stem exists in
    # multiple countries with no UK option (ambiguous) - map directly to the preferred path.
    "cnbc": "countries/world-europe/cnbc-eu.png",
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


def _logo_candidates(name: str):
    has_plus = bool(re.search(r"\+\s*1\s*$", name.strip()))
    override = LOGO_OVERRIDES.get(_override_key(name))
    if override:
        if has_plus:
            yield f"{override}-plus"
        yield override

    cleaned = _split_camel(name)
    cleaned = re.sub(r"\s*\+\s*1\s*$", " plus", cleaned)
    cleaned = re.sub(r"\bHD\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("&", " and ").replace(".", " ")
    base = _slugify(cleaned)
    yield base
    yield _slugify(re.sub(r"([A-Za-z])(\d)", r"\1 \2", cleaned))
    yield _slugify(re.sub(r"(\d)([A-Za-z])", r"\1 \2", cleaned))
    yield base.replace("-", "")  # squashed, e.g. "al-jazeera" -> "aljazeera"


def _match_stem(stem: str, logo_map: dict[str, list[str]]) -> str | None:
    matches = logo_map.get(stem)
    if not matches:
        return None
    uk = [p for p in matches if p.startswith("countries/united-kingdom/")]
    if uk:
        return uk[0]
    if len(matches) == 1:
        return matches[0]
    return None  # same stem in 2+ different countries with no UK option - too ambiguous to guess


def _bbc_region_logo(name: str, logo_map: dict[str, list[str]]) -> str | None:
    """BBC One/Two have real per-nation logos for Scotland/Wales/NI, but the many
    English regional variants (Tyne, London, etc.) all share the plain generic logo,
    which the general stem-matching won't find on its own (no file is named e.g.
    'bbc-one-tyne')."""
    lname = name.lower()
    for brand in ("bbc one", "bbc two"):
        if not lname.startswith(brand):
            continue
        generic_stem = brand.replace(" ", "-")
        stem = generic_stem
        if "scot" in lname:
            stem = f"{generic_stem}-scotland"
        elif "wal" in lname or "cymru" in lname:
            stem = f"{generic_stem}-wales"
        elif "northern ireland" in lname or " ni " in f" {lname} ":
            stem = f"{generic_stem}-northern-ireland"

        return _match_stem(stem, logo_map) or _match_stem(generic_stem, logo_map)
    return None


def match_logo(name: str, logo_map: dict[str, list[str]]) -> str | None:
    """Best-effort channel name -> tv-logos repo-relative path. Returns None on no
    confident match - callers should skip the <icon> entirely rather than guess."""
    path = LOGO_PATH_OVERRIDES.get(_override_key(name))
    if path:
        return path

    region = _bbc_region_logo(name, logo_map)
    if region:
        return region

    for cand in _logo_candidates(name):
        match = _match_stem(cand, logo_map)
        if match:
            return match

    return None


def logo_url(name: str, logo_map: dict[str, list[str]]) -> str | None:
    path = match_logo(name, logo_map)
    return f"{LOGO_RAW_BASE}/{path}" if path else None


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
