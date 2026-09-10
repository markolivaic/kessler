import { describe, expect, it } from "vitest";

import {
  AFTER_BURN,
  CLASS_COLOUR,
  GROUND,
  LIGHT_CLASS_COLOUR,
  LIGHT_GROUND,
  PARTNER,
  SELECTED,
  assertPaletteDiscipline,
  colourFor,
  contrast,
  distance,
  rgbFor,
  setGroundMode,
} from "./palette";

describe("palette discipline", () => {
  // Both grounds are real: light is the design, dark stays reachable at ?ground=dark
  // as the evidence for that decision. The rules have to hold for whichever is in
  // force, or changing ground would quietly break the encoding.
  it.each(["light", "dark"] as const)("passes every rule on the %s ground", (mode) => {
    const failures = assertPaletteDiscipline(mode);
    expect(
      failures.map((f) => `${f.rule}: ${f.detail}`).join("\n"),
      `palette rules broken on ${mode}`,
    ).toBe("");
  });

  it("would catch a class colour that vanishes into the ground", () => {
    // The rule is only worth having if it fails when it should.
    expect(contrast("#101318", GROUND)).toBeLessThan(3);
    expect(contrast(CLASS_COLOUR.PAY, GROUND)).toBeGreaterThanOrEqual(3);
    expect(contrast("#e8e6e1", LIGHT_GROUND)).toBeLessThan(3);
    expect(contrast(LIGHT_CLASS_COLOUR.PAY, LIGHT_GROUND)).toBeGreaterThanOrEqual(3);
  });

  it("keeps payload and debris apart, which is what the globe is for", () => {
    expect(distance(CLASS_COLOUR.PAY, CLASS_COLOUR.DEB)).toBeGreaterThanOrEqual(0.35);
  });

  it("keeps the before and after burn curves apart", () => {
    expect(distance(PARTNER, AFTER_BURN)).toBeGreaterThanOrEqual(0.4);
  });

  it("does not let a signal colour be mistaken for a class", () => {
    for (const colour of Object.values(CLASS_COLOUR)) {
      expect(distance(SELECTED, colour)).toBeGreaterThanOrEqual(0.3);
      expect(distance(PARTNER, colour)).toBeGreaterThanOrEqual(0.3);
    }
  });
});

describe("colour lookup", () => {
  it("returns the class colour for known types, on whichever ground", () => {
    setGroundMode("dark");
    expect(colourFor("PAY")).toBe(CLASS_COLOUR.PAY);
    expect(colourFor("DEB")).toBe(CLASS_COLOUR.DEB);
    setGroundMode("light");
    expect(colourFor("PAY")).toBe(LIGHT_CLASS_COLOUR.PAY);
    expect(colourFor("DEB")).toBe(LIGHT_CLASS_COLOUR.DEB);
  });

  it("falls back rather than returning undefined for an unknown type", () => {
    // A missing type used to paint a point black, which read as "no object".
    setGroundMode("light");
    expect(colourFor("SOMETHING NEW")).toBe(LIGHT_CLASS_COLOUR.UNK);
    setGroundMode("dark");
    expect(colourFor("SOMETHING NEW")).toBe(CLASS_COLOUR.UNK);
    setGroundMode("light");
    const [r, g, b] = rgbFor("SOMETHING NEW");
    expect(r + g + b).toBeGreaterThan(0);
  });

  it("never returns a black point for any type in the catalogue", () => {
    for (const mode of ["light", "dark"] as const) {
      setGroundMode(mode);
      for (const type of ["PAY", "DEB", "R/B", "UNK", "", "unexpected"]) {
        const [r, g, b] = rgbFor(type);
        expect(r + g + b, `${type} rendered black on ${mode}`).toBeGreaterThan(0.15);
      }
    }
    setGroundMode("light");
  });
});
