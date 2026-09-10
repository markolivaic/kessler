# progress

Running log. One entry per phase, written when the phase ends.

## E0, the gating measurement, 2026-08-18

**Shipped**

- `scripts/fetch_snapshot.py`, one dated snapshot of the CelesTrak GP catalogue and
  SATCAT, committed under `data/snapshots/2026-08-17/` with a `MANIFEST.json`
  carrying byte counts and SHA-256 for both files.
- `scripts/survey_conjunctions.py`, the screen. Preflight, gated KD-tree screen with
  a linear time-of-closest-approach test, run grouping, SGP4 minimisation, artefact
  classification.
- `scripts/benchmark.py`, timings for SGP4 and the neighbour search separately,
  because the survey's own phase timings mix propagation with array work.
- `data/survey/summary.json`, `data/survey/conjunctions.csv`, `data/survey/benchmark.json`.
- `THIRD_PARTY_NOTICES.md`, LICENSE, ruff config, venv.

**The number**

First pass ran on `GROUP=active` alone, 16,343 usable objects, and gave 1,469,455
passages within 25 km. That set contains no debris, which for a project named after
Kessler syndrome is the wrong scope. Four debris clouds were added and E0 rerun.

Final: **18,983 usable objects**, 24 h from 2026-08-17T00:00Z, 10 s steps,
164,010,103 state vectors. After both artefact filters: **1,525,863 passages within
25 km**, 234,742 within 10 km, 47,457 within 5 km, **772 within 1 km**.

Per object, the number that decides the interface: at 5 km a satellite averages
**5.0 passages a day**, and of the 13,509 objects that see at least one, the median
is 3 and the 95th percentile is 23. At 1 km it is one passage every twelve days.
Adding debris moved the median down from 5 to 3, because the debris arrived in
shells that are emptier than the one Starlink occupies. The 5 km choice survives it.

**Coverage, measured, not adjectival**

Denominator is every SATCAT row with a blank `DECAY_DATE`, 34,819 objects on orbit.

| type | screened | on orbit | |
|---|---|---|---|
| payloads | 16,345 | 19,847 | 82.4% |
| debris | 2,637 | 12,497 | 21.1% |
| rocket bodies | 2 | 2,421 | 0.1% |
| unknown | 0 | 54 | 0% |
| **all** | **18,984** | **34,819** | **54.5%** |

Rocket bodies are now the largest hole. The full catalogue needs a Space-Track
login, which would break clone-and-run, so this is a boundary rather than an
oversight, and it goes above the fold as a number.

What actually meets what, within 1 km: payload against payload 88.3%, debris
against payload 7.3%, debris against debris 4.3%. With 21% of catalogued debris
included, debris appears in 11.6% of the closest passages.

**Verified, with the output**

- Screening correctness against an independent dense reference (0.02 s scan, no
  optimiser) over a 540-570 km altitude band: **0 missed, 0 extra**, worst-case
  miss-distance disagreement **2.6 m**, median 0.08 m. Run three times: 30 pairs on
  active only, 30 again after the window fix, 31 once debris joined the band.
- First version of that check disagreed on one pair. Cause was real: the refinement
  bracket ran past the end of the requested window and found a TCA 5.75 s outside
  it. Both the linear test and the minimiser now clamp to the window.
- Determinism: two full runs, one on numpy 2.2.6 / scipy 1.16.3, one on numpy 2.5.2
  / scipy 1.18.0, produced **byte-identical counts and percentiles**.
- Shared-element-set filter: 3 groups of sizes 11, 5, 2 imply C(11,2)+C(5,2)+C(2,2)
  = 66 pairs. The survey removed exactly 66.
- SGP4 measured at **2.20M state vectors/s** single process, matching the figure
  taken before this project started.

**Decided without asking**

- 10 s screening cadence. The gate radius follows from it rigorously: threshold plus
  the furthest a pair can close in half a step, 21.93 km/s from the fastest perigee
  in the catalogue, so 134.6 km at a 25 km threshold. Nothing can hide between
  samples, and the validation run confirms it.
- One contiguous run of steps for one pair is **one encounter**, not one per step.
  Without this, two satellites flying in formation would be counted 8,641 times.
- A second artefact class beyond the one that was expected. See below.
- The committed CSV holds passages within 5 km plus every artefact at any distance,
  48,603 rows, 7.2 MB. The full 1.47M would be 200 MB and nobody would read it.
- Screening threshold reported at four levels rather than one, because the answer
  changes character across them.

**Debris inclusion rule, settled on evidence**

`scripts/debris_families.py` ranks the on-orbit debris population from the committed
SATCAT, no network. It splits families by international designator: fragments sharing
one launch id are one breakup, fragments spanning several are a vehicle type that has
shed debris on separate flights.

That split decided the question. CZ-6A, the second largest family at 1,206 fragments,
spans **8 launches**. It is not an event, so there is no parent object a CelesTrak
group could be named after. Same for DELTA 1 (35 launches) and BREEZE-M (82).

Then the endpoint check: CelesTrak's `elements/index.php` publishes exactly **three**
debris groups. `cosmos-1408-debris` is on no index page but its endpoint still
answers. So the rule is not a size threshold, because size is not the binding
constraint:

> **kessler includes every debris cloud CelesTrak publishes as a fetchable GROUP.**

A reader checks it in one request. The cost of the rule is measured, not waved at: the
largest single-event families with no endpoint are COSMOS 1275 (402 fragments),
NOAA 16 (356) and OPS 4682 (208), about 1,200 objects that would be included if an
endpoint existed. No further fetching was needed and E0 was not rerun.

**Open**

- Cosmos 1408 contributes 3 objects with current element sets. The 2021 test debris
  sat near 480 km and has almost entirely decayed. Kept for the record, and because
  its decay is part of the story, but it is not a numerical contribution.
- CZ-6A upper stage breakups are 1,206 on-orbit catalogued debris objects, larger
  than Cosmos 2251, Iridium 33 and Cosmos 1408 combined. Not one of the four
  canonical clouds. Flagged, not added.
- Rocket bodies: 2 of 2,421 screened.


## E1 to E6, 2026-08-18

**Shipped**

- `backend/kessler/`, the screening engine as a package rather than a script:
  `catalogue` (snapshot, SATCAT join, coverage), `screening` (gate, three passes,
  separation curve, shell sieve), `artefacts` (the two predicates), `manoeuvre`
  (SGP4 inversion and burns), `probability` (Pc, conditional on a stated covariance),
  `tle` (re-encoding for the browser), `api` (FastAPI).
- `web/`, the interface. One full-width time axis as the spine, globe above it,
  separation curve below, CDM-style record panel beside it.
- `scripts/debris_families.py`, the evidence behind the debris inclusion rule.
- README to the standard's anatomy, CI, 110 Python tests and 32 frontend tests.

**Verified, with the output**

- Behavioural 74, integrity 36, frontend 32, counted separately. Typecheck and build
  clean. `ruff check` and `ruff format --check` clean over backend, scripts and tests.
- **Clean-clone test passed.** A copy with no `.venv`, `node_modules` or caches:
  `pip install -e "backend[dev]"` succeeds, the API answers `/api/health` and returns
  the ISS record, `npm ci` and `npm run build` succeed, and all 142 tests pass from
  the fresh copy.
- The screen against an independent dense reference: 0 missed, 0 extra, 2.6 m worst.
- SGP4 inversion, zero burn, whole catalogue: median 1.1e-7 m, 99.989% under a
  micrometre. Two geostationary objects do not converge and the API returns 422.
- TLE round trip over the whole snapshot: median 0.27 m, worst 83 m over 24 hours.
- SGP4 measured at 1,958,883 state vectors/s on this machine with 18,984 objects.

**Bugs found, all real**

- Canvases were sized once during boot, before the browser had laid out the new DOM,
  so every canvas kept its default 300x150 backing store stretched to fill its
  element until the user happened to resize the window. Found by driving the running
  app, not by any test. Fixed with a ResizeObserver.
- `parseTle` compacted its array when it skipped a malformed record, which would
  shift every later index. Index is the only thing tying a point to its name, colour
  and catalogue number, so one bad line would have silently relabelled most of the
  globe. Now a skipped record leaves a null in place.
- **265 objects have catalogue numbers past 99999**, which do not fit the five column
  TLE field. Formatting with %05d turned 100000 into 10000 and shifted every column
  after it. Implemented Alpha-5. satellite.js reads it correctly, checked.
- 104 of 105 non-zero second derivatives need a two digit exponent, which the format
  has no room for. They now write as zero, which costs nothing because standard SGP4
  does not read that field.
- `groups` was assigned twice in the survey's `main()`, so `objects_by_group` in the
  summary was the element-set map, 281 KB of garbage.
- The refine bracket ran past the end of the requested window and reported a time of
  closest approach 5.75 s outside it. Found by the validation reference.

**Decided without asking**

- Precomputed screening rather than on demand. A full screen is about 14 minutes, so
  it cannot be a request. The manoeuvre is 1.2 ms, so that one is computed live.
- FastAPI service plus a static frontend, with the browser propagating the globe
  itself from TLE text and every displayed number coming from the server.
- Collision probability implemented, but `position_sigma_km` has no default and
  omitting it returns no probability at all.

**Outstanding**

- **The walkthrough recording.** The build environment's browser does not composite,
  so no frame can be captured there.
- **The light against dark comparison** in `docs/design.md`, same reason. The pass
  criterion is committed and unrevised; the two frames are not.


## Visual pass in a real browser, 2026-08-18

The build environment's browser never composites, so none of this was visible until
the work moved to a real Chrome. Everything below was found by driving the running
application, and none of it would have failed the suite as it stood.

**The design changed.** `docs/design.md` argued for a dark ground and committed a pass
criterion before rendering anything. The pale frame passed both halves of it, so by
the rule as written the argument was rationalisation and the design switched to a pale
ground. The correction is appended to that file, the rejected frame is committed at
`docs/ground-comparison/dark-rejected.png`, and `?ground=dark` still renders it.

**Bugs found and fixed**

- Points were about twenty CSS pixels across. The 2,637 debris objects merged into an
  opaque shell that hid the Earth and made debris look like the bulk of the population
  rather than 14% of it. The palette test passed the whole time.
- The selected object was white at 3.2x size, which passes the palette distance rule
  and is still unfindable among nineteen thousand pale dots. Selection is now a ring,
  because shape is the channel that was free.
- On the pale ground the amber partner colour sat **0.132** from the debris ochre. The
  discipline check caught it before it shipped.
- The separation curve was linear, so every encounter was the same giant V and a burn
  moving the miss from 201 m to 490 m produced no visible change. Logarithmic now.
- The lead time slider silently rescaled the curve's x-axis.
- The post-burn curve painted over the pre-burn one where they coincide. Dashed now.
- Two minimum labels printed on top of each other when the values were close.
- Coastlines were too dark to see, and the loader swallowed a failure silently.
- Every canvas kept its default 300x150 backing store until a window resize.
- The spine's passage marks were drawn in the rule colour: four of five were invisible.
- The spine covers 24 h at 57 s per pixel and the curve covers 20 minutes, so the
  design's claim that both always show the same instant was only true at the moment a
  passage was selected. The curve scrubs now too.

**Verified after the changes:** 74 behavioural, 37 integrity, 33 frontend, lint,
format, typecheck and build all clean. The palette rule now runs against both grounds.

**Still outstanding: the walkthrough.** See the note in the README. ffmpeg is not
installed on this machine, so the MP4 and poster cannot be produced here, and the
frame capture available through browser automation is a slideshow of discrete states
rather than an uninterrupted recording of the globe in motion.


## Redesign and deep interaction pass, 2026-08-18

**Why.** Put side by side, kessler and anneal were one application with different
content: two row header, fixed left record column, dominant visual right, full width
strip along the bottom, same information order. The brief constrained type and colour
and never constrained layout. A shared skeleton is the same batch signature as a
shared build file, only in smaller print.

**The redesign.** The left column is gone. The globe is full bleed and is the page.
The record is a card that does not exist until something is selected and that closes
again. Search is an overlay, provenance and legend and the disclosure are corner
marginalia the way a chart carries a source note, and the clock is an overlay along
the bottom edge rather than a row in a stack. No flex column of panels remains.

**The ground went back to dark, for a stated reason that is not the first one.** The
committed legibility criterion asked whether dark was necessary and the honest answer
was no; that answer stands unrevised. A second constraint the criterion never covered
decided it: kessler must not look like anneal, which is pale. Legibility is satisfied
by either. Differentiation is not, and it is what selects dark. The pale ground stays
a real design with a toggle, a remembered choice, and the palette rule running against
both. See the second correction in docs/design.md.

**The serious bug the sweep found.** `_least_squares_inversion` returns three values
and `invert_sgp4` unpacked them into two, so it raised `ValueError` on every object
that reached it. The fallback had never run once. `apply_burn` passed the exception
up and the API turned it into a 422 reading "too many values to unpack (expected 2)".
The whole-catalogue check caught `ValueError` and counted those objects as skips,
which is precisely why the measurement missed it: the objects excluded from the sample
were exactly the ones the fallback existed for.

Fixing it changed published numbers, all now corrected in the README:

| claim | was | is |
|---|---|---|
| objects inverted | 18,772 | 18,983 |
| under one micrometre | 99.989% of a 198 object sample | 99.9473% of the whole catalogue |
| objects that do not converge | 2 | 10 |
| crashes | 211, silently counted as skips | 0 |

`scripts/benchmark.py` now sweeps every object rather than a sample, for that reason.

**Other bugs found by sweeping rather than confirming**

- A stray click on the globe threw away a record with a burn set up on it, and the end
  of a rotate drag fires a click too. Deselect now requires the pointer not to have
  moved.
- The card and the approach panel both anchored right and overlapped, so the curve's
  own axis labels went underneath the card. The bottom is three zones now and a test
  measures that they do not intersect.
- A burn too small to matter reported "&minus;0 m". It says so in words now.
- The spine said "no passage under 5 km for this object" when no object was selected
  at all. Two empty states, two sentences.
- The source note had the point field reading straight through it. It sits on a soft
  scrim, not a panel, because a panel would put the left column back.

**Swept, working:** search by name, by NORAD id, by both Alpha-5 ids (100000 and
100332), a miss, and below the two character floor. An object with zero passages and
one with five. Select, deselect by close button, by Escape, and by clicking empty sky.
Spine and curve both scrubbing one clock. Burn at +20, &minus;20, 0 and 0.1 mm/s, both
signs increasing the miss as the geometry requires. Lead time at both ends, 0.25 h
moving nothing and 18.5 h moving 1.67 km. The 422 path surfaced in the interface with
the real message. Reload mid-selection recovering clean. Vertical resize with all
canvases refitting and no overlap.

**Not verified here:** the narrow window layout below 1180 px. The browser window
would not resize horizontally in this environment, only vertically.

**Verified after everything:** 74 behavioural, 37 integrity, 33 frontend, lint,
format, typecheck, build. Clean-clone test rerun from a fresh copy because the
redesign touched the frontend build: install, 111 Python tests, npm ci, typecheck, 33
frontend tests, build, and a live end-to-end manoeuvre through the API all pass.
