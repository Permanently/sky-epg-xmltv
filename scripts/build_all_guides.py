#!/usr/bin/env python3
"""
Build an XMLTV guide for every region in data/regions.json.

Most Sky channels are identical across every region - only a handful
(BBC One, ITV1, BBC Two Wales/NI, S4C, etc.) actually vary by area. Fetching
every channel once per region would multiply request volume for no benefit,
so this fetches each unique SID's schedule exactly once and reuses it across
every region's guide that needs it.

Usage:
    python build_all_guides.py --days 7
    python build_all_guides.py --days 7 --regions tyne_hd,london_hd
"""
from __future__ import annotations

import argparse
import json
import os
import time

import sky_api

DEFAULT_REGIONS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "regions.json")


def discover_region(key: str, rb: dict, channels_dir: str, logo_index: set[str] | None) -> dict[str, dict]:
    services = sky_api.fetch_services(rb["bouquet"], rb["subBouquet"])
    channels = {}
    for s in services:
        name, sid = s.get("t"), s.get("sid")
        if not (name and sid):
            continue
        icon = sky_api.logo_url(name, logo_index) if logo_index is not None else None
        channels[name] = {"sid": str(sid), "icon": icon}

    with open(os.path.join(channels_dir, f"{key}.json"), "w", encoding="utf-8") as f:
        json.dump(channels, f, indent=2, sort_keys=True)
    return channels


def load_cached_region(key: str, channels_dir: str) -> dict[str, dict] | None:
    path = os.path.join(channels_dir, f"{key}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--regions-file", default=DEFAULT_REGIONS_FILE)
    parser.add_argument("--regions", help="Comma-separated subset of region keys (default: all)")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--channels-dir", default="channels")
    parser.add_argument("--out-dir", default="guides")
    parser.add_argument("--delay", type=float, default=sky_api.DEFAULT_REQUEST_DELAY)
    parser.add_argument(
        "--skip-discovery",
        action="store_true",
        help="Read existing channels/<region>.json instead of re-discovering from Sky. "
        "Falls back to discovering if a region has no cached file yet.",
    )
    parser.add_argument("--no-logos", action="store_true", help="Skip logo matching on fallback discovery")
    args = parser.parse_args()

    with open(args.regions_file, "r", encoding="utf-8") as f:
        all_regions: dict[str, dict[str, int]] = json.load(f)

    if args.regions:
        wanted = set(args.regions.split(","))
        regions = {k: v for k, v in all_regions.items() if k in wanted}
    else:
        regions = all_regions

    os.makedirs(args.channels_dir, exist_ok=True)
    os.makedirs(args.out_dir, exist_ok=True)

    region_channels: dict[str, dict[str, dict]] = {}
    all_sids: dict[str, str] = {}
    logo_index = None  # only fetched lazily, if a fallback discovery is actually needed

    for key in sorted(regions):
        rb = regions[key]
        chmap = load_cached_region(key, args.channels_dir) if args.skip_discovery else None

        if chmap is None:
            if logo_index is None and not args.no_logos:
                logo_index = sky_api.fetch_logo_index()
            print(f"[discover] {key} (bouquet {rb['bouquet']}/{rb['subBouquet']})")
            chmap = discover_region(key, rb, args.channels_dir, logo_index)
            time.sleep(args.delay)
        else:
            print(f"[cached] {key}: {len(chmap)} channels")

        region_channels[key] = chmap
        for name, info in chmap.items():
            all_sids.setdefault(info["sid"], name)

    print(f"\n{len(all_sids)} unique channel SIDs across {len(regions)} regions\n")

    sid_events: dict[str, list[dict]] = {}
    for i, (sid, name) in enumerate(sorted(all_sids.items()), start=1):
        print(f"[fetch {i}/{len(all_sids)}] {name} ({sid})")
        sid_events[sid] = sky_api.fetch_sid_events(sid, args.days, delay=args.delay)

    print()
    for key in sorted(regions):
        chmap = region_channels[key]
        out_path = os.path.join(args.out_dir, f"{key}.xml")
        count = sky_api.write_xmltv(out_path, chmap, sid_events)
        print(f"[write] {out_path}: {len(chmap)} channels, {count} programmes")


if __name__ == "__main__":
    main()
