#!/usr/bin/env python3
"""
Build a Sky channel -> {sid, icon} map straight from Sky's services endpoint,
with a best-effort logo URL attached from tv-logo/tv-logos. Region definitions
live in data/regions.json, not here.

Usage:
    python discover_channels.py --list-regions
    python discover_channels.py --region tyne_hd --out channels/tyne_hd.json
    python discover_channels.py --all --out-dir channels
    python discover_channels.py --all --no-logos
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import sky_api

DEFAULT_REGIONS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "regions.json")


def load_regions(path: str) -> dict[str, dict[str, int]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def discover_one(bouquet: int, sub_bouquet: int, logo_map: dict[str, list[str]] | None) -> dict[str, dict]:
    services = sky_api.fetch_services(bouquet, sub_bouquet)
    result = {}
    for s in services:
        name, sid = s.get("t"), s.get("sid")
        if not (name and sid):
            continue
        icon = sky_api.logo_url(name, logo_map) if logo_map is not None else None
        result[name] = {"sid": str(sid), "icon": icon}
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--regions-file", default=DEFAULT_REGIONS_FILE)
    parser.add_argument("--region", help="Single region key to discover (see --list-regions)")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--out", default=None)
    parser.add_argument("--out-dir", default="channels")
    parser.add_argument("--list-regions", action="store_true")
    parser.add_argument("--no-logos", action="store_true", help="Skip logo matching (faster, no icons)")
    parser.add_argument("--delay", type=float, default=sky_api.DEFAULT_REQUEST_DELAY)
    args = parser.parse_args()

    regions = load_regions(args.regions_file)

    if args.list_regions:
        for key in sorted(regions):
            print(key)
        return

    logo_map = None if args.no_logos else sky_api.build_logo_map(sky_api.fetch_logo_index())
    if logo_map is not None:
        print(f"Logo index: {len(logo_map)} matchable logo stems across all countries")

    if args.all:
        os.makedirs(args.out_dir, exist_ok=True)
        for key in sorted(regions):
            rb = regions[key]
            print(f"Discovering {key}...")
            channels = discover_one(rb["bouquet"], rb["subBouquet"], logo_map)
            out_path = os.path.join(args.out_dir, f"{key}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(channels, f, indent=2, sort_keys=True)
            matched = sum(1 for c in channels.values() if c.get("icon"))
            print(f"  {len(channels)} channels ({matched} with logos) -> {out_path}")
            time.sleep(args.delay)
        return

    region_key = args.region or "london_hd"
    if region_key not in regions:
        print(f"Unknown region '{region_key}'. Use --list-regions to see options.", file=sys.stderr)
        sys.exit(1)

    rb = regions[region_key]
    channels = discover_one(rb["bouquet"], rb["subBouquet"], logo_map)
    out_path = args.out or os.path.join("channels", f"{region_key}.json")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(channels, f, indent=2, sort_keys=True)
    matched = sum(1 for c in channels.values() if c.get("icon"))
    print(f"Wrote {len(channels)} channels ({matched} with logos) for region '{region_key}' to {out_path}")


if __name__ == "__main__":
    main()
