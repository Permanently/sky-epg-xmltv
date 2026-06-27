#!/usr/bin/env python3
"""
Fetch a Sky EPG for a single channel list and write one XMLTV file.
For ad-hoc/manual use - for every region at once, use build_all_guides.py.

Usage:
    python fetch_epg.py --channels ../channels/channels.example.json --days 7 --out guide.xml
"""
from __future__ import annotations

import argparse
import json

import sky_api


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channels", default="channels/channels.json")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--out", default="guide.xml")
    parser.add_argument("--delay", type=float, default=sky_api.DEFAULT_REQUEST_DELAY)
    args = parser.parse_args()

    with open(args.channels, "r", encoding="utf-8") as f:
        channels: dict[str, str] = json.load(f)
    channels.pop("_comment", None)

    sid_events: dict[str, list[dict]] = {}
    for name, sid in channels.items():
        print(f"Fetching {name} ({sid})...")
        sid_events[sid] = sky_api.fetch_sid_events(sid, args.days, delay=args.delay)

    count = sky_api.write_xmltv(args.out, channels, sid_events)
    print(f"Wrote {args.out}: {len(channels)} channels, {count} programmes")


if __name__ == "__main__":
    main()
