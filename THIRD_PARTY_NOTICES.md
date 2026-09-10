# Third party data and code

Everything in `data/snapshots/` came from somewhere else. This file says where,
under what terms, and what was done to it.

## CelesTrak general perturbations element sets

All five files are from `https://celestrak.org/NORAD/elements/gp.php?GROUP=<group>&FORMAT=csv`,
created by Dr T.S. Kelso, CelesTrak. Licence note below. **Transformation: none.** Each
file is committed exactly as served, byte for byte.

| Group | Local path under `data/snapshots/2026-08-17/` | Bytes | Rows | Retrieved (UTC) |
|---|---|---|---|---|
| `active` | `gp-active.csv` | 2,469,549 | 16,344 | 2026-08-17T23:20:44Z |
| `fengyun-1c-debris` | `gp-fengyun-1c-debris.csv` | 296,853 | 1,935 | 2026-08-18T00:13:23Z |
| `cosmos-2251-debris` | `gp-cosmos-2251-debris.csv` | 91,649 | 591 | 2026-08-18T00:13:29Z |
| `iridium-33-debris` | `gp-iridium-33-debris.csv` | 17,255 | 111 | 2026-08-18T00:13:35Z |
| `cosmos-1408-debris` | `gp-cosmos-1408-debris.csv` | 703 | 3 | 2026-08-18T00:13:41Z |

SHA-256, per file:

```
a8eb6d3475c0354f602827c9e1b7dadbde7fbba70184ef5b552ea2808f11c951  gp-active.csv
f03bf630a4c889167ab428e767b1c8619a451c93581e44b510d27d2cfbe57264  gp-fengyun-1c-debris.csv
6f7286ebc88982e83647872bebbf84bfec69820a2e077b07d88f9bae3810f01f  gp-cosmos-2251-debris.csv
0c8d097e0888acb6dadf45ac36488435a34e02f3b02f3b434854521f49792b7c  gp-iridium-33-debris.csv
deab8eb307db5318490677c243ad472e54d2940912a28bd6425086689ddb89e0  gp-cosmos-1408-debris.csv
```

### Which debris is here, and by what rule

**The rule: every debris cloud CelesTrak publishes as a fetchable GROUP. All of them,
with no selection on my part.** On 2026-08-18 that is three groups listed on
`https://celestrak.org/NORAD/elements/index.php` (`fengyun-1c-debris`,
`iridium-33-debris`, `cosmos-2251-debris`) plus `cosmos-1408-debris`, which appears
nowhere on that index but whose endpoint still answers, with 3 objects. A reader can
check the rule in one request: fetch the index, count the debris groups.

The binding constraint is availability, not size. That matters, because the ranking in
`data/survey/debris_families.json` (produced by `scripts/debris_families.py` from the
committed SATCAT, no network) shows what is therefore missing:

| family | on-orbit fragments | median perigee | why not here |
|---|---|---|---|
| CZ-6A | 1,206 | 749 km | not one event. 8 separate launches of the same upper stage, so there is no parent object to name a group after |
| DELTA 1 | 954 | 1,075 km | not one event, 35 launches |
| COSMOS 1275 | 402 | 879 km | single 1981 breakup, no CelesTrak GROUP |
| NOAA 16 | 356 | 764 km | single 2015 breakup, no CelesTrak GROUP |
| OPS 4682 | 208 | 1,249 km | single breakup, no CelesTrak GROUP |

Included: 2,637 of 12,497 on-orbit catalogued debris objects, 21.1%. The single-event
families with no endpoint would add roughly another 1,200 if they had one.

The four that are here are also the ones the project is named after. Cosmos 2251 and
Iridium 33 are the two halves of the 2009 collision, the only accidental hypervelocity
collision between two intact satellites on record. Fengyun 1C is the 2007
anti-satellite test and is still the largest single debris source on orbit, 2,315
catalogued fragments. Cosmos 1408 is the 2021 anti-satellite test.

One number in that list is worth stopping on. **Cosmos 1408 produced over 1,500
tracked fragments in 2021 and 3 of them are left.** Fengyun 1C, nineteen years older
and a comparable event, still has 2,315. The difference is altitude: the 2021 test was
conducted near 480 km where atmospheric drag clears debris in a few years, the 2007
test near 850 km where it does not. Altitude decides persistence more than the size of
the event does.

The snapshot directory is named for the catalogue epoch the survey propagates from,
not for the wall-clock time each file was pulled. The debris files were fetched about
fifty minutes after the active catalogue, which crossed midnight UTC. Every file
carries its true retrieval timestamp above and in `MANIFEST.json`.

## CelesTrak satellite catalogue

| | |
|---|---|
| Creator | Dr T.S. Kelso, CelesTrak |
| Source | `https://celestrak.org/pub/satcat.csv` |
| Local path | `data/snapshots/2026-08-17/satcat.csv` |
| Retrieved | 2026-08-17T23:20:53Z |
| Size | 6,703,547 bytes, 70,292 rows |
| SHA-256 | `b869bf4aab89bf2d59e07170331a9a64017954060f8bd09481b10331e0e64612` |
| Licence | None published. See the note below. |
| Transformation | None. Joined to the element sets on `NORAD_CAT_ID` at run time for object type and radar cross section. Nothing is written back. |

Both files are byte-identical to what the server returned. `MANIFEST.json` next to
them records the same hashes, so a reader can check that claim rather than take it.

### On the licence, and on the fetching

CelesTrak publishes no licence text. Redistribution of basic orbital data of this
kind rests on the United States Space Command blanket release for basic space
situational awareness data, which asks for citation. The upstream terms are
Space-Track's: `https://www.space-track.org/documentation#/user_agree`. If CelesTrak
ask for the snapshot to come down, it comes down.

Two things about how it was fetched, because they are not obvious and they shaped
the design:

CelesTrak's `robots.txt` disallows the `gp.php` endpoint for every user agent, and
their published policy says repeat offenders get firewalled at the IP. So kessler
never fetches from a browser and never fetches on a page load. One process pulled
one snapshot, on 2026-08-17, with a user agent naming the project. That snapshot is
committed. `scripts/fetch_snapshot.py` is the only code that talks to CelesTrak, it
sleeps between the two requests, and it does not retry on an HTTP error.

The consequence for a reader: the numbers here describe the sky as it was on
2026-08-17. They are not live. Rerunning the survey against the committed snapshot
reproduces them exactly.

## sgp4

| | |
|---|---|
| Creator | Brandon Rhodes, from the Vallado et al. reference implementation |
| Source | `https://pypi.org/project/sgp4/` |
| Version | 2.27 |
| Licence | MIT |
| Use | Unmodified. Imported as a dependency, not vendored. |

## What the derived values are not

`data/survey/conjunctions.csv` and `data/survey/summary.json` are computed by
`scripts/survey_conjunctions.py` from the snapshot above. They are model output.

- They are **not observations**. Nothing here was measured against a radar or an
  optical track. A miss distance in that file is where SGP4 says two objects would
  be if the published mean elements were exact.
- They are **not collision probabilities**. A probability needs a covariance, and a
  two-line element set carries none. Where kessler shows a probability it is always
  conditional on a covariance **you** typed in, the assumed value is on screen beside
  the number, and changing it moves the answer by orders of magnitude. That is the
  point of showing it. A bare probability from data like this would be a number
  someone invented and then rounded.
- They are **not a conjunction warning service**. The real ones screen against the
  full tracked catalogue using observations that are not public. This screens
  **18,984 of the 34,819 objects the catalogue lists as on orbit, 54.5%**, from
  public elements, once, on one date. Payload coverage is 82.4%, debris 21.1%,
  rocket bodies 0.1%. The missing half is not a rounding error, and a passage this
  project does not report is not a passage that did not happen.
- They are **not** a reason to move a spacecraft.
