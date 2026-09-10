/**
 * Catalogue propagation for the globe, separate from the worker that runs it.
 *
 * The worker is a message pump. The arithmetic lives here so it can be tested in the
 * suite rather than only by looking at a browser, which is how a whole class of bug
 * used to reach a screen recording before anybody noticed.
 */

import { eciToEcf, gstime, propagate, twoline2satrec } from "satellite.js";

export type Satrec = ReturnType<typeof twoline2satrec>;

export interface ParsedCatalogue {
  /** One slot per record in the file. Unparseable records are null, never removed. */
  satrecs: (Satrec | null)[];
  names: string[];
  skipped: number;
}

/**
 * Three lines per object: name, line 1, line 2.
 *
 * A record that will not parse leaves a null in place rather than being dropped.
 * Compacting the array would shift every later index by one, and index is the only
 * thing tying these objects to their names, colours, catalogue numbers and to what
 * the picker returns when you click a point. A single malformed line would have
 * silently relabelled most of the catalogue.
 */
export function parseTle(text: string): ParsedCatalogue {
  const lines = text.split("\n");
  const satrecs: (Satrec | null)[] = [];
  const names: string[] = [];
  let skipped = 0;

  for (let i = 0; i + 2 < lines.length; i += 3) {
    const name = lines[i].trim();
    const line1 = lines[i + 1];
    const line2 = lines[i + 2];
    names.push(name);

    if (!line1?.startsWith("1 ") || !line2?.startsWith("2 ")) {
      satrecs.push(null);
      skipped += 1;
      continue;
    }
    try {
      const satrec = twoline2satrec(line1, line2);
      // twoline2satrec reports a bad element set through a field rather than by
      // throwing, so checking for an exception alone is not enough.
      if (satrec.error && satrec.error !== 0) {
        satrecs.push(null);
        skipped += 1;
        continue;
      }
      satrecs.push(satrec);
    } catch {
      satrecs.push(null);
      skipped += 1;
    }
  }
  return { satrecs, names, skipped };
}

export interface Frame {
  positions: Float32Array;
  velocities: Float32Array;
  ok: Uint8Array;
  alive: number;
}

/**
 * Every object at one instant, in earth-fixed kilometres.
 *
 * Earth-fixed rather than inertial so the coastline mesh can be static and the
 * satellites move across it, which is the way the picture is meant to be read.
 */
export function propagateAll(satrecs: (Satrec | null)[], when: Date): Frame {
  const gmst = gstime(when);
  const count = satrecs.length;
  const positions = new Float32Array(count * 3);
  const velocities = new Float32Array(count * 3);
  const ok = new Uint8Array(count);
  let alive = 0;

  for (let i = 0; i < count; i += 1) {
    const satrec = satrecs[i];
    if (satrec === null) continue;
    let state;
    try {
      state = propagate(satrec, when);
    } catch {
      continue;
    }
    // satellite.js signals failure by putting `true` in these slots rather than by
    // throwing, so a truthiness check would let a boolean through as a vector.
    const eci = state?.position;
    const eciVelocity = state?.velocity;
    if (typeof eci !== "object" || typeof eciVelocity !== "object") continue;

    const p = eciToEcf(eci, gmst);
    const v = eciToEcf(eciVelocity, gmst);
    if (!Number.isFinite(p.x) || !Number.isFinite(p.y) || !Number.isFinite(p.z)) continue;

    positions[i * 3] = p.x;
    positions[i * 3 + 1] = p.y;
    positions[i * 3 + 2] = p.z;
    velocities[i * 3] = v.x;
    velocities[i * 3 + 1] = v.y;
    velocities[i * 3 + 2] = v.z;
    ok[i] = 1;
    alive += 1;
  }

  return { positions, velocities, ok, alive };
}
