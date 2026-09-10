/**
 * The colour rule, in one place, as data.
 *
 * Colour here encodes object class and nothing else. It is not decoration and it is
 * not mood. Getting it wrong is a correctness bug, not a taste one: if debris and
 * payloads read the same, the globe stops answering the question it exists to answer.
 *
 * `assertPaletteDiscipline` is run by the test suite, not only by a browser console.
 * On the last project a palette rule shipped that only ever wrote to a console no
 * build read, and every atom rendered black for a week.
 */

export const GROUND = "#0d1014";
export const PANEL = "#161a20";
export const RULE = "#262c35";
export const TEXT = "#dce1e8";
export const DIM = "#8a93a0";

/** Class colours. Cool for intact payloads, dull warm for debris, neutral for stages. */
export const CLASS_COLOUR: Record<string, string> = {
  PAY: "#93b7e3",
  DEB: "#b08050",
  "R/B": "#8b8b96",
  UNK: "#5f6773",
};

/** Signal colours. These mean "you chose this", not "this is a category". */
export const SELECTED = "#ffffff";
export const PARTNER = "#f2b441";
export const AFTER_BURN = "#4fd1c5";

/**
 * The pale-ground counterpart, used only to settle the comparison docs/design.md
 * commits to. Same encoding, same meaning, inverted for a light background: cool
 * stays cool, warm stays warm, both darkened so they sit on paper rather than glow.
 */
export const LIGHT_GROUND = "#eeece7";
export const LIGHT_CLASS_COLOUR: Record<string, string> = {
  PAY: "#2f7fd0",
  DEB: "#8a5410",
  "R/B": "#4a4d55",
  UNK: "#6f747c",
};

export type Ground = "dark" | "light";

// Dark is the default, and the reason is not the one originally argued.
//
// Two separate constraints bear on this. The first is legibility, and docs/design.md
// committed a pass criterion for it before anything was rendered. That criterion was
// answered honestly and the answer was that dark is *not* necessary: the pale ground
// passed both of its questions. That answer stands and is not revised.
//
// The second constraint was never in the criterion. kessler must not look like the
// previous project in this portfolio, which is pale. Two repositories sharing a
// skeleton read as one template used twice, and detecting exactly that from the
// outside is why this portfolio is being rebuilt. Under that constraint the dark
// ground is chosen. It is a differentiation decision, not a legibility one.
//
// The pale ground therefore stays a real design rather than a rejected draft: the
// toggle switches to it, ?ground=light selects it, and the discipline check below
// runs against both so neither can rot.
let ground: Ground = "dark";

export function setGroundMode(mode: Ground): void {
  ground = mode;
}

export function isLightGround(): boolean {
  return ground === "light";
}

/**
 * Every colour the canvases draw with, for the ground currently in force.
 *
 * The 2D canvases cannot read CSS variables, so when the ground flipped they kept
 * painting with the dark palette's constants: the playhead was drawn white on a pale
 * background and disappeared, and the clock label went pale-on-pale. Colours that the
 * canvas code uses have to come through here rather than from a module constant.
 */
export interface Ink {
  ground: string;
  text: string;
  dim: string;
  rule: string;
  selected: string;
  partner: string;
  afterBurn: string;
  plate: string;
}

const DARK_INK: Ink = {
  ground: GROUND,
  text: TEXT,
  dim: DIM,
  rule: RULE,
  selected: SELECTED,
  partner: PARTNER,
  afterBurn: AFTER_BURN,
  plate: "rgba(13,16,20,0.9)",
};

const LIGHT_INK: Ink = {
  ground: LIGHT_GROUND,
  text: "#23262a",
  dim: "#5f636a",
  rule: "#c9c4b9",
  // Near-black rather than white: this marks the instant and the object you chose,
  // and on paper the darkest thing on the page is what reads as chosen.
  selected: "#111418",
  // Crimson, not the dark palette's amber. On paper the amber sat 0.13 from the
  // debris ochre, so a highlighted encounter partner read as a debris object. The
  // discipline check caught it before it shipped.
  partner: "#c2185b",
  afterBurn: "#00838f",
  plate: "rgba(238,236,231,0.92)",
};

export function ink(): Ink {
  return ground === "light" ? LIGHT_INK : DARK_INK;
}

export function groundColour(): string {
  return ground === "light" ? LIGHT_GROUND : GROUND;
}

export function colourFor(objectType: string): string {
  const table = ground === "light" ? LIGHT_CLASS_COLOUR : CLASS_COLOUR;
  return table[objectType] ?? table.UNK;
}

function toRgb(hex: string): [number, number, number] {
  const value = hex.replace("#", "");
  return [
    parseInt(value.slice(0, 2), 16) / 255,
    parseInt(value.slice(2, 4), 16) / 255,
    parseInt(value.slice(4, 6), 16) / 255,
  ];
}

export function rgbFor(objectType: string): [number, number, number] {
  return toRgb(colourFor(objectType));
}

export const rgb = toRgb;

/** Relative luminance, for contrast checks. */
function luminance(hex: string): number {
  const channels = toRgb(hex).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

export function contrast(a: string, b: string): number {
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (high + 0.05) / (low + 0.05);
}

/** Perceptual distance, crude but enough to catch two classes that look alike. */
export function distance(a: string, b: string): number {
  const [ar, ag, ab] = toRgb(a);
  const [br, bg, bb] = toRgb(b);
  return Math.hypot(ar - br, ag - bg, ab - bb);
}

export interface PaletteFailure {
  rule: string;
  detail: string;
}

/**
 * Every rule the design depends on, checked. Returns failures rather than throwing so
 * a test can report all of them at once.
 */
export function assertPaletteDiscipline(mode: Ground = ground): PaletteFailure[] {
  const failures: PaletteFailure[] = [];
  const CLASS = mode === "light" ? LIGHT_CLASS_COLOUR : CLASS_COLOUR;
  const BACK = mode === "light" ? LIGHT_GROUND : GROUND;
  const signals = mode === "light"
    ? { SELECTED: LIGHT_INK.selected, PARTNER: LIGHT_INK.partner, AFTER_BURN: LIGHT_INK.afterBurn }
    : { SELECTED, PARTNER, AFTER_BURN };

  // 1. Every class colour has to be legible against the ground it is drawn on.
  for (const [name, colour] of Object.entries(CLASS)) {
    const ratio = contrast(colour, BACK);
    if (ratio < 3) {
      failures.push({
        rule: "class colours are legible on the ground",
        detail: `${name} ${colour} has contrast ${ratio.toFixed(2)} against ${BACK}, want >= 3`,
      });
    }
  }

  // 2. Payload and debris are the distinction the globe exists to show. If those two
  //    converge the picture is lying about what is up there.
  const payloadVsDebris = distance(CLASS.PAY, CLASS.DEB);
  if (payloadVsDebris < 0.35) {
    failures.push({
      rule: "payload and debris are clearly different",
      detail: `distance ${payloadVsDebris.toFixed(3)}, want >= 0.35`,
    });
  }

  // 3. Signal colours must not collide with class colours, or "selected" reads as a
  //    category and the interface means something it does not intend.
  for (const [signalName, signal] of Object.entries(signals)) {
    for (const [className, colour] of Object.entries(CLASS)) {
      const apart = distance(signal, colour);
      if (apart < 0.3) {
        failures.push({
          rule: "signal colours do not collide with class colours",
          detail: `${signalName} is ${apart.toFixed(3)} from ${className}, want >= 0.3`,
        });
      }
    }
  }

  // 4. Before and after a burn are the one comparison the tool is for. They have to
  //    be separable, and not by hue alone.
  const beforeAfter = distance(signals.PARTNER, signals.AFTER_BURN);
  if (beforeAfter < 0.4) {
    failures.push({
      rule: "the before and after curves are separable",
      detail: `distance ${beforeAfter.toFixed(3)}, want >= 0.4`,
    });
  }

  // 5. Nothing may depend on telling red from green. Approximate deuteranopia by
  //    collapsing the red and green channels and re-checking the pairs that carry
  //    meaning.
  const collapse = (hex: string): [number, number, number] => {
    const [r, g, b] = toRgb(hex);
    const rg = (r + g) / 2;
    return [rg, rg, b];
  };
  const collapsedDistance = (a: string, b: string) => {
    const [ar, , ab] = collapse(a);
    const [br, , bb] = collapse(b);
    return Math.hypot(ar - br, ab - bb);
  };
  const meaningfulPairs: [string, string, string][] = [
    [CLASS.PAY, CLASS.DEB, "payload against debris"],
    [signals.PARTNER, signals.AFTER_BURN, "before against after a burn"],
  ];
  for (const [a, b, label] of meaningfulPairs) {
    const apart = collapsedDistance(a, b);
    if (apart < 0.2) {
      failures.push({
        rule: "no meaning depends on telling red from green",
        detail: `${label} collapses to ${apart.toFixed(3)} under deuteranopia, want >= 0.2`,
      });
    }
  }

  // 6. The banned look. A hard rule, so it cannot drift back in by increments.
  const banned = ["#a855f7", "#d946ef", "#ec4899", "#8b5cf6"];
  for (const colour of [...Object.values(CLASS), ...Object.values(signals)]) {
    for (const forbidden of banned) {
      if (distance(colour, forbidden) < 0.15) {
        failures.push({
          rule: "no purple to pink gradient palette",
          detail: `${colour} is within 0.15 of ${forbidden}`,
        });
      }
    }
  }

  return failures;
}
