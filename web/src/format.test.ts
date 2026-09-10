import { describe, expect, it } from "vitest";

import { clock, duration, km, probability, speed } from "./format";
import { toScene } from "./globe";

describe("km", () => {
  it("switches to metres below a kilometre, because that is where it matters", () => {
    expect(km(0.164)).toBe("164 m");
    expect(km(0.0104)).toBe("10 m");
  });

  it("keeps three decimals in the single-kilometre range", () => {
    expect(km(4.886)).toBe("4.886 km");
  });

  it("drops precision as the number stops deserving it", () => {
    expect(km(17.87)).toBe("17.87 km");
    expect(km(134.6)).toBe("134.6 km");
  });

  it("does not invent a number from nothing", () => {
    expect(km(null)).toBe("-");
    expect(km(undefined)).toBe("-");
    expect(km(NaN)).toBe("-");
  });
});

describe("speed", () => {
  it("shows metres per second where formations live", () => {
    expect(speed(0.0008)).toBe("0.8 m/s");
    expect(speed(0.05)).toBe("50.0 m/s");
  });

  it("shows km/s where passages live", () => {
    expect(speed(14.93)).toBe("14.930 km/s");
  });
});

describe("duration", () => {
  it("reads as time, not as a number of seconds", () => {
    expect(duration(0)).toBe("0s");
    expect(duration(95)).toBe("1m 35s");
    expect(duration(7200)).toBe("2h 00m");
    expect(duration(-600)).toBe("-10m 00s");
  });
});

describe("clock", () => {
  it("is UTC and always the same width", () => {
    expect(clock(new Date("2026-08-17T08:21:42Z"))).toBe("08:21:42");
    expect(clock(new Date("2026-08-17T00:00:00Z"))).toBe("00:00:00");
  });
});

describe("probability", () => {
  it("uses exponent form where the numbers actually are", () => {
    expect(probability(1.2e-5)).toBe("1.20e-5");
    expect(probability(0)).toBe("0");
    expect(probability(null)).toBe("-");
  });
});

describe("toScene", () => {
  it("puts the north pole up", () => {
    const [, y] = toScene(0, 0, 6378.137);
    expect(y).toBeGreaterThan(0);
    const [, southY] = toScene(0, 0, -6378.137);
    expect(southY).toBeLessThan(0);
  });

  it("stays right-handed, so the coastlines are not mirrored", () => {
    // ECEF x cross ECEF y must equal ECEF z after the mapping too. A sign slip here
    // renders a mirror-image Earth that looks plausible until you find Africa.
    const x = toScene(1, 0, 0);
    const y = toScene(0, 1, 0);
    const z = toScene(0, 0, 1);
    const cross: [number, number, number] = [
      x[1] * y[2] - x[2] * y[1],
      x[2] * y[0] - x[0] * y[2],
      x[0] * y[1] - x[1] * y[0],
    ];
    const dot = cross[0] * z[0] + cross[1] * z[1] + cross[2] * z[2];
    expect(dot).toBeGreaterThan(0);
  });

  it("scales the Earth to a size the camera bounds expect", () => {
    const [, y] = toScene(0, 0, 6378.137);
    expect(y).toBeCloseTo(6.378137, 5);
  });
});
