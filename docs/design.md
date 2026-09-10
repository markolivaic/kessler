# Design brief

Written before the globe was built, and not revised after seeing it. If something
here turned out wrong, the correction is appended at the bottom with the reason,
rather than edited into the original so it looks like it was always right.

## The structural idea

One full-width time axis is the spine of the page: the globe hangs above it and the
miss-distance curve below it, and both always show the same instant, so scrubbing
time or adding a burn moves everything at once.

Everything else follows from that. There is no dashboard grid, no cards. There is a
clock, and two views of it stacked.

## The reference

The Conjunction Data Message, CCSDS 508.0-B-1. It is the thing the stated user
actually receives from the 18th Space Defense Squadron and cannot interrogate: a
keyword-value record with a header naming the originator and the message epoch, then
a metadata block per object, then the numbers. A university cubesat team gets one of
these in an email and has no way to ask what a 5 cm/s burn tomorrow would do to it.

So the readout is built as a CDM you can scrub. That is honest to the premise, it is
the domain's own document rather than a generic telemetry aesthetic, and it puts the
provenance where it belongs. In a real CDM the originator and epoch are the first
fields on the record. Here that same header block carries the snapshot date, the
coverage fraction, and the line saying no covariance was used and no probability is
computed. The disclosure is a field of the record, not a footnote under it.

## Type

- **Atkinson Hyperlegible** for interface text.
- **JetBrains Mono** for records, element sets and numeric columns.

The reason is not aesthetic. NORAD catalogue numbers and international designators
are strings where `0` against `O` and `1` against `l` against `I` decide which object
you are looking at. Atkinson Hyperlegible was drawn by the Braille Institute
specifically to separate those glyph pairs at small sizes. And a two-line element set
is a fixed-width format where column position carries meaning, so it needs a mono or
it stops being a TLE.

Both are OFL. Neither is Inter or Geist. Neither is Libertinus Serif or IBM Plex
Mono, which is what anneal used.

## Palette

Ground `#0D1014`, panels `#161A20`, rules `#262C35`, text `#DCE1E8`, dim `#8A93A0`.

Colour encodes class, not mood:

| meaning | colour |
|---|---|
| payload | cool pale blue |
| debris | dull warm ochre |
| rocket body | neutral grey |
| the object you selected | white, larger |
| its encounter partner, and the miss-distance curve | saturated amber |
| the same curve after a burn | teal |

Amber against teal and blue against ochre both survive the common colour vision
deficiencies. Nothing anywhere depends on telling red from green.

The Earth is a graticule and coastline wireframe, not a photographic texture. That is
the domain's own drawing convention, and a photo texture would compete with 19,000
points drawn on top of it.

## The dark ground, and how it gets checked

Dark is the obvious choice for a space application and therefore the suspect one. The
argument for it here is legibility: the centre of this app draws about 19,000 moving
points over a sphere, and on a pale ground those are 19,000 dark specks that read as
dirt, with the altitude shells washing out.

That argument might be a rationalisation. So it gets tested, and the pass criterion
is written down here **before either frame is rendered**, so the test cannot be
settled by looking at both and picking the nicer one.

**Procedure.** Render the identical frame, same camera, same objects, same instant,
once on the dark ground and once on a pale ground with the point colours inverted to
suit it. Commit both to `docs/`.

**Pass criterion.** At the default zoom, without zooming or rotating, can a viewer:

1. tell the altitude shells apart, and
2. tell a payload from a debris object?

**Decision rule.** If the light frame passes both, the legibility argument was
rationalisation and the design switches to light. If it fails either, dark is earned
and the two frames stay in `docs/` as the evidence.

## Layout constraints

- Flex column for the vertical structure. No `calc(100vh - Npx)` with a hand-counted
  header height.
- Wide content scrolls inside its own container. The page body never scrolls
  sideways.
- The header disclosure is always on screen. It does not scroll away.

---

## Outstanding: the dark ground has not been tested yet

The procedure and the pass criterion above were written before any rendering, which was
the point of writing them down. **The comparison itself has not been run.**

The browser available in the build environment does not composite: `requestAnimationFrame`
never fires in it, so no frame is ever produced and a screenshot times out. That is a
property of that environment, not of the application, and it also means the walkthrough
recording cannot be made there.

So the dark ground currently rests on the argument alone, which is exactly the state the
criterion was written to get out of. Until the two frames exist in this directory, treat
the palette as provisional. The criterion stands as written and is not to be revised
after seeing the images.


---

## Correction, 2026-08-18: the criterion went against the argument

The section above headed "Outstanding: the dark ground has not been tested yet" is
superseded. The comparison has now been run in a real browser and **the design is a
pale ground.** The dark one is rejected.

**What was claimed.** That about 19,000 points over a sphere would, on a pale ground,
be "19,000 dark specks that read as dirt, with the altitude shells washing out".

**What the render showed.** Neither. On the pale ground the low orbit payload band
reads as a dense blue ring at the limb and the debris sits as a visibly separate,
higher ochre band outside it. Payload against debris is unambiguous. Applying the
criterion exactly as it was written:

1. Can a viewer tell the altitude shells apart at the default zoom? **Yes.**
2. Can a viewer tell a payload from a debris object? **Yes.**

The decision rule said that if the light frame passes both, the legibility argument
was rationalisation and the design switches. It passes both. So it switches.

The rule was deliberately asymmetric: dark had to be *necessary*, not merely adequate.
Both grounds are adequate. That is exactly the case the rule was written to resolve
against the thing I had already talked myself into.

**Two things the switch then improved, which were not part of the criterion.**

The selected object was white at 3.2x size on the dark ground and was genuinely hard
to find among nineteen thousand pale dots, even though white sits 0.52 from the
payload blue and passed the palette distance rule. On paper the selected marker is
near black, and the darkest thing on the page reads as the chosen one immediately.

The encounter partner was amber. On the pale ground amber sat **0.132** from the
debris ochre, well inside the 0.3 minimum, so a highlighted partner would have read
as a debris object. `assertPaletteDiscipline` caught that before it shipped, which is
the entire reason the palette rule is a test rather than a comment. The partner is now
crimson, and the whole light palette was recomputed against the same constraints.

**What was fixed independently of the ground**, all found by driving the running
application and none catchable by the suite as it stood:

- Points were drawn about twenty CSS pixels across. The 2,637 debris objects merged
  into one opaque shell that hid the Earth and made debris look like the bulk of the
  population rather than 14% of it. The size constant is now derived from the scene
  scale and the camera distance instead of guessed.
- The coastline was too dark to see under the point field, so the globe had nothing
  to read position against.
- Every canvas kept its default 300x150 backing store, stretched to fill its element,
  until the user happened to resize the window.
- The separation curve was linear. A pass at 6.8 km/s is 4,000 km away ten minutes
  either side of a 200 m miss, so every encounter was the same giant V, and a burn
  taking the miss from 200 m to 480 m was invisible. It is logarithmic now, which is
  what makes the manoeuvre readable at all.
- The lead time slider silently rescaled the curve's x-axis, so moving one control
  changed the axis of another.
- The post-burn curve is dashed. Away from closest approach the two trajectories
  coincide, and a solid second line simply painted over the first.

**Evidence.** `docs/ground-comparison/dark-rejected.png` is the rejected frame, taken
from the running application. `?ground=dark` still renders it in full, so the
comparison is reproducible rather than being a claim about a committed image, and the
palette discipline test now runs against both grounds so neither can rot.


---

## Second correction, 2026-08-18: the skeleton was the problem, and the ground goes back

Two separate things are recorded here. Keeping them apart matters, because collapsing
them would turn a real constraint into a excuse for a preference.

### The layout was the same as the previous project's

Put the first version of this interface beside anneal and they are one application
with different content. Shared: a two row header of masthead plus disclosure bar, a
fixed left column carrying a monospace tag-and-value record and the controls, the
dominant visual panel on the right, a full width strip along the bottom, and the same
information order of identity, record, controls, visual, trace. Typeface and palette
differed. The skeleton did not, and the skeleton is what a reader sees before they
read a word.

This brief constrained type and constrained colour and never once constrained layout,
which is how it happened. Four repositories generated from one scaffold are detectable
from the outside in an hour; two repositories sharing a skeleton are the same tell in
smaller print.

**What changed.** The left column is gone. The globe is full bleed and is the page.
The object record is a card that does not exist until you select something and that
closes again, which is also what was asked for originally: clickable points that open
their data. Search is an overlay. Provenance, legend and the disclosure became corner
marginalia, the way a chart carries its source note, rather than a banner. The clock
runs along the bottom edge as an overlay on the globe rather than as a row in a
stack. There is no flex column of stacked panels left anywhere.

### The ground goes back to dark, and not for the reason first argued

The legibility criterion at the top of this file asked whether a dark ground was
**necessary**. It was answered honestly in the first correction and the answer was
no: the pale frame passed both of its questions. **That answer stands and is not
revised.** Legibility does not choose between these two.

A second constraint exists that the criterion never covered. **kessler must not look
like anneal.** anneal is pale. With the skeleton now rebuilt, ground is the largest
remaining shared signal between the two, and this one is a portfolio level constraint
rather than a rendering one.

So: **the legibility constraint is satisfied by either ground. The differentiation
constraint is not, and it is what selects dark.** That is the whole reasoning, and it
is a differentiation decision rather than a legibility one. Saying "dark is more
legible" would be the rationalisation, which is why the criterion was written first
and why its verdict is left standing above.

The pale ground is therefore not a rejected draft. It passed the only test that was
ever posed to it. It stays a real design: there is a toggle in the top right, the
choice is remembered, `?ground=light` still selects it, `docs/ground-comparison/`
holds the frame, and `assertPaletteDiscipline` runs against **both** palettes so
neither can rot. If anneal is ever redesigned away from pale, this decision should be
revisited, because its only support is the differentiation constraint.
