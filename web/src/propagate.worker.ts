/**
 * SGP4 for the whole catalogue, off the main thread.
 *
 * Nineteen thousand objects is about 200 ms of satellite.js per full update, which
 * would drop every frame if it ran on the main thread. So it runs here, at its own
 * pace, and the renderer extrapolates along the returned velocity between updates.
 *
 * This file is a message pump on purpose. The arithmetic is in ./propagate so the
 * suite can test it without a browser.
 */

import { parseTle, propagateAll, type Satrec } from "./propagate";

let satrecs: (Satrec | null)[] = [];

interface InitMessage {
  type: "init";
  tle: string;
}
interface PropagateMessage {
  type: "propagate";
  epochMs: number;
}
type Incoming = InitMessage | PropagateMessage;

self.onmessage = (event: MessageEvent<Incoming>) => {
  const message = event.data;

  if (message.type === "init") {
    const parsed = parseTle(message.tle);
    satrecs = parsed.satrecs;
    self.postMessage({
      type: "ready",
      count: satrecs.length,
      names: parsed.names,
      skipped: parsed.skipped,
    });
    return;
  }

  if (message.type === "propagate") {
    const frame = propagateAll(satrecs, new Date(message.epochMs));
    self.postMessage(
      {
        type: "positions",
        epochMs: message.epochMs,
        positions: frame.positions,
        velocities: frame.velocities,
        ok: frame.ok,
      },
      { transfer: [frame.positions.buffer, frame.velocities.buffer, frame.ok.buffer] },
    );
  }
};
