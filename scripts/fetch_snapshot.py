"""Pull one dated snapshot of the CelesTrak GP catalogue and SATCAT.

CelesTrak's robots.txt disallows the GP endpoint for every user agent and their
policy page threatens to firewall IPs that hammer it. So this runs server-side,
on demand or on a slow cron, and writes a dated snapshot to disk. Nothing else
in kessler talks to CelesTrak. The browser never does.

Usage:
    python scripts/fetch_snapshot.py                 # today, skip what exists
    python scripts/fetch_snapshot.py --force         # refetch even if present
    python scripts/fetch_snapshot.py --only gp       # one file
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS = ROOT / "data" / "snapshots"

# A user agent that says who is calling and where to complain. CelesTrak asks
# for this; anonymous python-urllib is what gets firewalled.
USER_AGENT = "kessler/0.1 (portfolio conjunction screening; github.com/markolivaic/kessler)"

SOURCES = {
    "gp-active": {
        "url": "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=csv",
        "filename": "gp-active.csv",
        "description": "General perturbations element sets, GROUP=active",
    },
    "satcat": {
        "url": "https://celestrak.org/pub/satcat.csv",
        "filename": "satcat.csv",
        "description": "Satellite catalogue: object type, owner, size, orbit class",
    },
    # The four canonical breakup clouds. Not an arbitrary pick: Cosmos 2251 and
    # Iridium 33 are the two halves of the 2009 collision, the only accidental
    # hypervelocity collision between two intact satellites on record. Fengyun 1C
    # is the 2007 anti-satellite test and is still the largest single debris
    # source on orbit. Cosmos 1408 is the 2021 anti-satellite test. Kessler
    # syndrome is the theory that predicts exactly these events, so a project
    # named after it screening only intact active satellites would be missing
    # its own subject.
    "fengyun-1c-debris": {
        "url": "https://celestrak.org/NORAD/elements/gp.php?GROUP=fengyun-1c-debris&FORMAT=csv",
        "filename": "gp-fengyun-1c-debris.csv",
        "description": "Fengyun 1C breakup, 2007 anti-satellite test",
    },
    "cosmos-2251-debris": {
        "url": "https://celestrak.org/NORAD/elements/gp.php?GROUP=cosmos-2251-debris&FORMAT=csv",
        "filename": "gp-cosmos-2251-debris.csv",
        "description": "Cosmos 2251 breakup, 2009 collision with Iridium 33",
    },
    "iridium-33-debris": {
        "url": "https://celestrak.org/NORAD/elements/gp.php?GROUP=iridium-33-debris&FORMAT=csv",
        "filename": "gp-iridium-33-debris.csv",
        "description": "Iridium 33 breakup, 2009 collision with Cosmos 2251",
    },
    "cosmos-1408-debris": {
        "url": "https://celestrak.org/NORAD/elements/gp.php?GROUP=cosmos-1408-debris&FORMAT=csv",
        "filename": "gp-cosmos-1408-debris.csv",
        "description": "Cosmos 1408 breakup, 2021 anti-satellite test",
    },
}

# Seconds between requests. One snapshot is two requests; there is no reason to
# make them back to back.
POLITE_DELAY = 5.0


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def fetch(url: str, timeout: float = 120.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"{url} returned HTTP {response.status}")
        return response.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=None, help="snapshot date, default today UTC")
    parser.add_argument("--force", action="store_true", help="refetch files that exist")
    parser.add_argument("--only", default=None, choices=sorted(SOURCES), help="one source")
    args = parser.parse_args()

    stamp = args.date or datetime.now(UTC).strftime("%Y-%m-%d")
    outdir = SNAPSHOTS / stamp
    outdir.mkdir(parents=True, exist_ok=True)

    manifest_path = outdir / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    manifest.setdefault("snapshot_date", stamp)
    manifest.setdefault("source", "CelesTrak (celestrak.org)")
    manifest.setdefault(
        "redistribution",
        "CelesTrak publishes no licence. Redistribution of basic SSA data rests on the "
        "USSPACECOM blanket approval, which requires citation. See THIRD_PARTY_NOTICES.md.",
    )
    manifest.setdefault("files", {})

    wanted = [args.only] if args.only else list(SOURCES)
    first = True

    for key in wanted:
        source = SOURCES[key]
        target = outdir / source["filename"]

        if target.exists() and not args.force:
            print(f"  have  {target.relative_to(ROOT)}  ({target.stat().st_size:,} bytes)")
            continue

        if not first:
            time.sleep(POLITE_DELAY)
        first = False

        print(f"  fetch {source['url']}")
        try:
            payload = fetch(source["url"])
        except urllib.error.HTTPError as error:
            print(f"  HTTP {error.code} from CelesTrak. Do not retry in a loop.", file=sys.stderr)
            return 1
        except urllib.error.URLError as error:
            print(f"  network error: {error.reason}", file=sys.stderr)
            return 1

        target.write_bytes(payload)
        lines = payload.count(b"\n")
        manifest["files"][source["filename"]] = {
            "url": source["url"],
            "description": source["description"],
            "bytes": len(payload),
            "sha256": sha256(payload),
            "rows": max(lines - 1, 0),
            "retrieved_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        print(f"  wrote {target.relative_to(ROOT)}  ({len(payload):,} bytes, {lines - 1:,} rows)")

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"  wrote {manifest_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
