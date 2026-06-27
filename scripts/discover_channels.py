#!/usr/bin/env python3
"""
Build a Sky channel -> SID map straight from Sky's services endpoint.
Region definitions live in data/regions.json, not here.

Usage:
    python discover_channels.py --list-regions
    python discover_channels.py --region tyne_hd --out channels/tyne_hd.json
    python discover_channels.py --all --out-dir channels
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


def discover_one(bouquet: int, sub_bouquet: int) -> dict[str, str]:
    services = sky_api.fetch_services(bouquet, sub_bouquet)
    return {s["t"]: str(s["sid"]) for s in services if s.get("t") and s.get("sid")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--regions-file", default=DEFAULT_REGIONS_FILE)
    parser.add_argument("--region", help="Single region key to discover (see --list-regions)")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--out", default=None)
    parser.add_argument("--out-dir", default="channels")
    parser.add_argument("--list-regions", action="store_true")
    parser.add_argument("--delay", type=float, default=sky_api.DEFAULT_REQUEST_DELAY)
    args = parser.parse_args()

    regions = load_regions(args.regions_file)

    if args.list_regions:
        for key in sorted(regions):
            print(key)
        return

    if args.all:
        os.makedirs(args.out_dir, exist_ok=True)
        for key in sorted(regions):
            rb = regions[key]
            print(f"Discovering {key}...")
            channels = discover_one(rb["bouquet"], rb["subBouquet"])
            out_path = os.path.join(args.out_dir, f"{key}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(channels, f, indent=2, sort_keys=True)
            print(f"  {len(channels)} channels -> {out_path}")
            time.sleep(args.delay)
        return

    region_key = args.region or "london_hd"
    if region_key not in regions:
        print(f"Unknown region '{region_key}'. Use --list-regions to see options.", file=sys.stderr)
        sys.exit(1)

    rb = regions[region_key]
    channels = discover_one(rb["bouquet"], rb["subBouquet"])
    out_path = args.out or os.path.join("channels", f"{region_key}.json")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(channels, f, indent=2, sort_keys=True)
    print(f"Wrote {len(channels)} channels for region '{region_key}' to {out_path}")


if __name__ == "__main__":
    main()
