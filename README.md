# sky-epg-xmltv

Generates a standard [XMLTV](https://wiki.xmltv.org/index.php/XMLTVFormat) electronic programme
guide for Sky channels, sourced from Sky's own (undocumented) linear EPG service - one guide per
UK region, updated daily via GitHub Actions, with a rolling 7-day window.

`epgsky.com` is a Sky registered domain, and appears to be the same backend that Sky Q, Sky Go,
and the Android app use internally. It isn't a documented *public* API though, so treat it as
unofficial/unsupported. There is literally **zero** guarantee it stays stable. Don't yell at me.

## Quickstart

Browse to the `guides/` folder in this repo and pick out the XML file for your region. Each is
name  after its region key (see `data/regions.json` for the full list, e.g. `tyne_hd`, `london_hd`,
`wales_sd`).

Grab the raw file URL and point your EPG-consuming app (Plex, Jellyfin, TVHeadend, etc.) at it
directly - it'll update daily on its own. For example, the London HD guide:

```
https://raw.githubusercontent.com/Permanently/sky-epg-xmltv/main/guides/london_hd.xml
```

## Structure

```
data/regions.json        # bouquet/subBouquet codes for every UK Sky region (HD + SD)
channels/<region>.json   # auto-generated: live channel name -> SID map per region
guides/<region>.xml      # auto-generated: the actual XMLTV output per region
scripts/
  sky_api.py             # shared fetch + XMLTV-building helpers
  discover_channels.py   # build a channel list for one region, or --all of them
  fetch_epg.py           # ad-hoc: one channel list -> one XMLTV file
  build_all_guides.py    # the main script - builds every region's guide efficiently
```

## Why "build_all_guides.py" instead of just looping the single-region script

Most Sky channels are identical across every region, and only a handful (BBC One, ITV1, BBC Two
Wales/NI, S4C etc etc etc) actually carry regional variants. Naively running the single-channel-list
fetch once per region would re-fetch hundreds of identical national channels dozens of times.

`build_all_guides.py` instead:

1. Discovers the live channel list for every region in `data/regions.json` (via Sky's
   `/hawk/linear/services/{bouquet}/{subBouquet}` endpoint).
2. Builds one global set of unique channel SIDs across *all* regions.
3. Fetches each unique SID's schedule exactly once.
4. Writes one `guides/<region>.xml` per region, reusing the shared fetch results for whichever
   SIDs that region needs.

Essentially this is just keeping the global channels being called once, to speed up the process.

A rough sense of scale: across all ~48 regions there are roughly 300-350 *unique* SIDs in total
(out of Sky's full lineup), so a full run is roughly that many schedule fetches \* 7 days, not
channels \* regions \* days. With the default 0.4s delay between requests that's still a fair few
minutes - if you only care about one or two regions, pass `--regions` to limit it.

## Getting your region(s) right

```bash
python scripts/discover_channels.py --list-regions          # see available region keys
python scripts/build_all_guides.py --days 7 --regions tyne_hd,london_hd   # just these two, for testing
python scripts/build_all_guides.py --days 7                  # every region (what the workflow runs)
```

`data/regions.json` is the single source of truth for region codes - edit it to add/remove
regions rather than touching any of the scripts.

## Programme artwork and channel logos

The EPG output is fully usable without either, and a miss just means an `<icon>` is silently
omitted rather than a broken link being served. This is purely for cosmetic since I like logos :^)

**Programme artwork.** Every schedule event includes a `programmeuuid`, which doubles as a key
into Sky's separate image service at `images.metadata.sky.com`. Each programme gets two `<icon>`
elements: a 16:9 landscape still and a 3:4 portrait crop. Both endpoints are undocumented (found
by testing), so coverage isn't guaranteed for every programme (a generic news bulletin is less
likely to have one than a film), but no extra requests are needed to attach them - the URL is
just built directly from data already in the schedule response.

**Channel logos.** Sourced from [tv-logo/tv-logos](https://github.com/tv-logo/tv-logos), matched
by channel name. Sky's discovered channel names don't always slugify cleanly onto that repo's
filenames (abbreviations, rebrands, regional variants), so matching is best-effort: a small
manual override table handles known exceptions (e.g. "Sky One" -> `sky-max`, since the channel
later rebranded), BBC One/Two regional variants resolve to their region-specific logo where one
exists and fall back to the generic UK logo otherwise, and everything else goes through a
camelCase-aware slugifier checked against the *actual* live file listing (via GitHub's API) - so
a guess is only used if it's confirmed to exist, never just assumed.

Logos are matched once during discovery (`discover_channels.py`, normally the weekly job) and
baked into `channels/<region>.json` as `{"sid": "...", "icon": "... or null"}`, so the daily
guide build doesn't need to re-query anything for them. Pass `--no-logos` to either script to
skip logo matching (e.g. for faster iteration while testing).

tv-logo/tv-logos' logos are free for personal use. No LICENSE file exists in that repo, just 
README-stated terms: don't resell, don't use the logos in any "illegitimate" way. Something 
something, don't use for bad.

## Running locally

No third-party dependencies required - just Python 3.9+. Run scripts from the repo root, not
from inside `scripts/` - the default `channels`/`guides` paths are relative to wherever you run
from, and `cd`-ing into `scripts/` first will create `scripts/channels` and `scripts/guides`
instead of the top-level ones.

```bash
python scripts/build_all_guides.py --days 7
```

Output lands in `channels/*.json` and `guides/*.xml`.

For a single quick test against one hand-picked channel list (e.g. while developing), use
`fetch_epg.py` with `channels/channels.example.json` instead - it's faster since it's not
discovering or building every region.

## Automation

Two scheduled workflows:

- **`update-channels.yml`** - weekly (Sundays), runs `discover_channels.py --all` to refresh
  `channels/*.json` from Sky's services endpoint. Channel/SID mappings rarely change, so this
  doesn't need to run daily.
- **`update-epg.yml`** - daily, runs `build_all_guides.py --skip-discovery` to fetch 7 days of
  schedule data per unique SID and write `guides/*.xml`. `--skip-discovery` means it reads the
  channel lists the weekly job already maintains instead of re-querying the services endpoint
  every day; it'll fall back to discovering on the fly for any region missing a cached file.

Each region's guide ends up at a stable raw-GitHub-content URL, ready to feed into Plex,
Jellyfin, TVHeadend, etc.

`channels/*.json` is committed deliberately, not just generated and discarded - it changes far
less often than `guides/` (only when Sky actually reshuffles a SID), so it gives a cheap, readable
git history of channel/SID changes over time without the daily programme-listing noise.

## Notes / caveats

- **This is an unofficial, reverse-engineered data source.** It can change or break without
  warning, and I have no idea when. Don't rely on this for anything critical, and again, please
  don't yell at me when it breaks. Maybe blame Sky for only nearly hiring me years ago or something,
  I don't know.
- **Be a polite scraper.** The default delay and custom User-Agent are there on purpose - don't
  remove them or crank up request frequency, especially now that a full run touches every region.
- **Field mapping is best-effort.** Sky's `seasonnumber`/`episodenumber` fields aren't always
  populated or reliable for non-scripted programming (news, sport, etc.), so `<episode-num>` is
  only emitted when an episode number is present.
- Scraping and redistributing a broadcaster's EPG sits in a legal grey area - it's common
  practice in the IPTV/EPG hobbyist community (see `iptv-org/epg`, various Kodi/Enigma2 grabbers),
  but it isn't something Sky has authorised. Use for personal/non-commercial purposes.

## Credits

- In grateful memory of Jesse Mann ("jesmannstl", affectionately known as the "EPG Master"), whose work and API research in [tvmerge](https://github.com/jesmannstl/tvmerge) helped inform this project's API usage patterns. His contributions to the IPTV community continue to benefit, even today 🕊️
- Channel logos from [tv-logo/tv-logos](https://github.com/tv-logo/tv-logos) - free for personal use; please support the maintainer if you can.
- Region bouquet and subBouquet codes sourced from community research in [iptv-org/epg#1133](https://github.com/iptv-org/epg/issues/1133).