import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { parseTle, propagateAll } from "./propagate";

const fixture = readFileSync(
  fileURLToPath(new URL("./fixtures/sample.tle", import.meta.url)),
  "utf8",
);

const EARTH_RADIUS_KM = 6378.137;

function radius(positions: Float32Array, index: number): number {
  return Math.hypot(
    positions[index * 3],
    positions[index * 3 + 1],
    positions[index * 3 + 2],
  );
}

describe("parseTle", () => {
  it("reads every object in the fixture", () => {
    const parsed = parseTle(fixture);
    expect(parsed.satrecs.length).toBe(6);
    expect(parsed.skipped).toBe(0);
    expect(parsed.names[0]).toBe("ISS (ZARYA)");
  });

  it("holds a malformed record's place instead of shifting every later index", () => {
    // Compacting used to shift every later object by one, so the globe coloured and
    // selected the wrong satellites from the first bad line onward. Index is the only
    // thing tying a point to its name, its colour and what the picker returns.
    const broken = `BAD OBJECT\nnot a line one\nnot a line two\n${fixture}`;
    const parsed = parseTle(broken);
    expect(parsed.skipped).toBe(1);
    expect(parsed.satrecs.length).toBe(7);
    expect(parsed.satrecs[0]).toBeNull();
    expect(parsed.names[0]).toBe("BAD OBJECT");
    expect(parsed.names[1]).toBe("ISS (ZARYA)");
    expect(parsed.satrecs[1]).not.toBeNull();
  });

  it("propagates around a hole without shifting anything", () => {
    const broken = `BAD OBJECT\nnot a line one\nnot a line two\n${fixture}`;
    const parsed = parseTle(broken);
    const frame = propagateAll(parsed.satrecs, new Date("2026-08-17T12:00:00Z"));
    expect(frame.ok[0]).toBe(0);
    expect(frame.ok[1]).toBe(1);
    expect(frame.alive).toBe(6);
    expect(frame.ok.length).toBe(parsed.names.length);
  });

  it("reads an Alpha-5 catalogue number, which 265 objects now need", () => {
    // Catalogue numbers ran past 99999 in 2026. If satellite.js could not read the
    // replacement encoding, those objects would propagate from a wrong element set.
    const alpha5 = [
      "ALPHA FIVE OBJECT",
      "1 A0000U 26067CY  26228.87295269  .00000000  00000-0  00000-0 0  9993",
      "2 A0000  97.4000 100.0000 0001000  90.0000 270.0000 15.20000000    07",
    ].join("\n");
    const parsed = parseTle(`${alpha5}\n`);
    expect(parsed.skipped).toBe(0);
    expect(parsed.satrecs[0]).not.toBeNull();
    const frame = propagateAll(parsed.satrecs, new Date("2026-08-17T12:00:00Z"));
    expect(frame.alive).toBe(1);
    const r = Math.hypot(frame.positions[0], frame.positions[1], frame.positions[2]);
    expect(r).toBeGreaterThan(6500);
    expect(r).toBeLessThan(7500);
  });

  it("ignores a trailing partial record rather than throwing", () => {
    const parsed = parseTle(`${fixture}DANGLING NAME\n`);
    expect(parsed.satrecs.length).toBe(6);
  });
});

describe("propagateAll", () => {
  const parsed = parseTle(fixture);
  const when = new Date("2026-08-17T12:00:00Z");
  const frame = propagateAll(parsed.satrecs, when);

  it("propagates every object in the fixture", () => {
    expect(frame.alive).toBe(6);
    expect(frame.ok.every((v) => v === 1)).toBe(true);
  });

  it("puts the space station where the space station is", () => {
    // A low orbit, so a few hundred kilometres above the surface and nowhere near
    // geostationary. This catches a units slip between metres and kilometres.
    const r = radius(frame.positions, 0);
    expect(r - EARTH_RADIUS_KM).toBeGreaterThan(300);
    expect(r - EARTH_RADIUS_KM).toBeLessThan(500);
  });

  it("puts a geostationary satellite at geostationary radius", () => {
    const index = parsed.names.indexOf("EXPRESS-AMU1");
    expect(index).toBeGreaterThanOrEqual(0);
    const r = radius(frame.positions, index);
    expect(r).toBeGreaterThan(41000);
    expect(r).toBeLessThan(43500);
  });

  it("gives low orbit objects a speed near eight kilometres a second", () => {
    const speed = Math.hypot(
      frame.velocities[0],
      frame.velocities[1],
      frame.velocities[2],
    );
    expect(speed).toBeGreaterThan(7);
    expect(speed).toBeLessThan(8.5);
  });

  it("returns earth-fixed coordinates, so the ground does not slide under the points", () => {
    // In an inertial frame the same object an hour later has rotated with the Earth
    // by 15 degrees of longitude even if it had not moved. Earth-fixed is the whole
    // reason the coastline can be a static mesh, so it is worth pinning down: a
    // geostationary satellite is by definition almost stationary in this frame.
    const later = propagateAll(parsed.satrecs, new Date(when.getTime() + 3600_000));
    const index = parsed.names.indexOf("EXPRESS-AMU1");
    const moved = Math.hypot(
      later.positions[index * 3] - frame.positions[index * 3],
      later.positions[index * 3 + 1] - frame.positions[index * 3 + 1],
      later.positions[index * 3 + 2] - frame.positions[index * 3 + 2],
    );
    // An hour of inertial motion at geostationary radius would be over 11,000 km.
    expect(moved).toBeLessThan(400);
  });

  it("keeps array positions aligned with the input order", () => {
    // Index is the contract between the worker, the colours and the picker.
    expect(parsed.names.length).toBe(frame.ok.length);
    for (let i = 0; i < parsed.names.length; i += 1) {
      expect(radius(frame.positions, i)).toBeGreaterThan(EARTH_RADIUS_KM);
    }
  });

  it("marks an object it cannot propagate rather than leaving a zero at the origin", () => {
    const frameNow = propagateAll(parsed.satrecs, new Date("2100-01-01T00:00:00Z"));
    for (let i = 0; i < frameNow.ok.length; i += 1) {
      if (frameNow.ok[i] === 0) {
        expect(radius(frameNow.positions, i)).toBe(0);
      }
    }
    expect(frameNow.ok.length).toBe(6);
  });
});
