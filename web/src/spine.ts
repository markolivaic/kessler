/**
 * The time spine, and the separation curve that hangs under it.
 *
 * These are one module because they are one idea: a single axis that the globe above
 * and the curve below both read from. The spine owns the clock. Everything else on
 * the page is a projection of wherever it is pointing.
 */

import { ink } from "./palette";
import { axisKm, clock, duration, km } from "./format";

const WINDOW_S = 86400;

function fitCanvas(canvas: HTMLCanvasElement): CanvasRenderingContext2D | null {
  const ratio = Math.min(window.devicePixelRatio, 2);
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (width === 0 || height === 0) return null;
  if (canvas.width !== width * ratio || canvas.height !== height * ratio) {
    canvas.width = width * ratio;
    canvas.height = height * ratio;
  }
  const context = canvas.getContext("2d");
  if (!context) return null;
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, width, height);
  return context;
}

export interface SpineMark {
  offsetS: number;
  missKm: number;
  partner: string;
}

export interface SpineState {
  playheadS: number;
  marks: SpineMark[];
  selectedOffsetS: number | null;
  startDate: Date;
  hasSelection: boolean;
}

/** The 24 hour ruler. Hour ticks, a mark per passage, and the playhead. */
export function drawSpine(canvas: HTMLCanvasElement, state: SpineState): void {
  const context = fitCanvas(canvas);
  if (!context) return;
  const c = ink();
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  const padding = 16;
  const usable = width - padding * 2;
  const axisY = height - 20;
  const x = (offset: number) => padding + (offset / WINDOW_S) * usable;

  context.strokeStyle = c.rule;
  context.lineWidth = 1;
  context.beginPath();
  context.moveTo(padding, axisY + 0.5);
  context.lineTo(width - padding, axisY + 0.5);
  context.stroke();

  context.font = '10px "JetBrains Mono", ui-monospace, monospace';
  context.fillStyle = c.dim;
  context.textAlign = "center";
  for (let hour = 0; hour <= 24; hour += 1) {
    const px = x(hour * 3600);
    const major = hour % 6 === 0;
    context.strokeStyle = c.rule;
    context.beginPath();
    context.moveTo(px + 0.5, axisY);
    context.lineTo(px + 0.5, axisY - (major ? 9 : 5));
    context.stroke();
    if (major) context.fillText(`${String(hour).padStart(2, "0")}:00`, px, height - 6);
  }

  // One tick per passage. Height carries how close it was, so the day's shape is
  // readable before anything is selected.
  const closest = state.marks.length ? Math.min(...state.marks.map((m) => m.missKm)) : 1;
  for (const mark of state.marks) {
    const px = x(mark.offsetS);
    const weight = Math.max(0.15, 1 - Math.log10(1 + mark.missKm) / Math.log10(1 + 5));
    const tall = 10 + weight * (axisY - 26);
    const isSelected =
      state.selectedOffsetS !== null && Math.abs(mark.offsetS - state.selectedOffsetS) < 1;
    // Unselected marks used to be drawn in the rule colour, which is four steps off
    // the ground and left four of five passages invisible. The spine exists to show
    // the shape of the day before anything is picked, so they have to be readable.
    context.strokeStyle = isSelected ? c.partner : c.dim;
    context.lineWidth = isSelected ? 2 : 1;
    context.globalAlpha = isSelected ? 1 : 0.7;
    context.beginPath();
    context.moveTo(px + 0.5, axisY - 2);
    context.lineTo(px + 0.5, axisY - tall);
    context.stroke();
  }
  context.globalAlpha = 1;
  context.lineWidth = 1;

  const playX = x(state.playheadS);
  context.strokeStyle = c.selected;
  context.beginPath();
  context.moveTo(playX + 0.5, 4);
  context.lineTo(playX + 0.5, axisY);
  context.stroke();

  const now = new Date(state.startDate.getTime() + state.playheadS * 1000);
  const label = `${clock(now)} UTC`;
  context.font = '11px "JetBrains Mono", ui-monospace, monospace';
  const textWidth = context.measureText(label).width;
  const boxX = Math.min(Math.max(playX - textWidth / 2 - 5, 2), width - textWidth - 12);
  // The clock label sits on a plate so it stays readable over a passage tick.
  context.fillStyle = c.plate;
  context.fillRect(boxX, 2, textWidth + 10, 15);
  context.fillStyle = c.text;
  context.textAlign = "left";
  context.fillText(label, boxX + 5, 13);

  if (state.marks.length === 0) {
    // Two different empty states. Nothing selected is not the same as selected and
    // clean, and the first version said the second thing in both cases.
    context.fillStyle = c.dim;
    context.textAlign = "center";
    context.font = '11px "Atkinson Hyperlegible", system-ui, sans-serif';
    context.fillText(
      state.hasSelection
        ? "no passage under 5 km for this object in the 24 hours screened"
        : "24 hours from the snapshot epoch. Pick an object to mark its close approaches",
      width / 2,
      axisY - 14,
    );
  } else if (closest > 0) {
    context.fillStyle = c.dim;
    context.textAlign = "right";
    context.font = '10px "JetBrains Mono", ui-monospace, monospace';
    context.fillText(`${state.marks.length} passages, closest ${km(closest)}`, width - padding, 13);
  }
}

/** Where on the spine a click landed, in seconds from the window start. */
export function spineOffsetAt(canvas: HTMLCanvasElement, clientX: number): number {
  const rect = canvas.getBoundingClientRect();
  const padding = 16;
  const usable = rect.width - padding * 2;
  const fraction = (clientX - rect.left - padding) / usable;
  return Math.min(Math.max(fraction, 0), 1) * WINDOW_S;
}

export interface CurveSeries {
  offsetsS: number[];
  separationKm: (number | null)[];
  colour: string;
  label: string;
  dashed?: boolean;
}

export interface CurveState {
  series: CurveSeries[];
  playheadS: number | null;
  thresholdKm?: number;
}

/**
 * The horizontal mapping of the last curve drawn, so a click on it can be read back.
 *
 * The spine covers 24 hours across about 1,500 pixels, which is 57 seconds a pixel,
 * while the curve covers 20 minutes. Scrubbing the spine therefore lands inside the
 * curve's window roughly never, and the design's claim that both views always show
 * the same instant was only true at the moment a passage was selected. Letting the
 * curve scrub as well makes the coarse and fine controls two ends of one clock.
 */
let lastCurveMapping: { left: number; right: number; minX: number; maxX: number } | null = null;

/** Where on the separation curve a click landed, in seconds from the window start. */
export function curveOffsetAt(canvas: HTMLCanvasElement, clientX: number): number | null {
  if (!lastCurveMapping) return null;
  const { left, right, minX, maxX } = lastCurveMapping;
  const rect = canvas.getBoundingClientRect();
  const usable = rect.width - left - right;
  if (usable <= 0) return null;
  const fraction = (clientX - rect.left - left) / usable;
  return minX + Math.min(Math.max(fraction, 0), 1) * (maxX - minX);
}

/** Separation against time, through a time of closest approach. */
export function drawCurve(canvas: HTMLCanvasElement, state: CurveState): void {
  const context = fitCanvas(canvas);
  if (!context) return;
  const c = ink();
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  const left = 62;
  const right = 14;
  const top = 12;
  const bottom = 26;

  if (state.series.length === 0 || state.series.every((s) => s.offsetsS.length === 0)) {
    context.fillStyle = c.dim;
    context.font = '12px "Atkinson Hyperlegible", system-ui, sans-serif';
    context.textAlign = "center";
    context.fillText("pick a passage to see its approach", width / 2, height / 2);
    lastCurveMapping = null;
    return;
  }

  const allOffsets = state.series.flatMap((s) => s.offsetsS);
  const allValues = state.series.flatMap((s) =>
    s.separationKm.filter((v): v is number => v !== null && v > 0),
  );
  const minX = Math.min(...allOffsets);
  const maxX = Math.max(...allOffsets);

  // Logarithmic, and not for style. Two objects passing at 6.8 km/s are 4,000 km
  // apart ten minutes either side of a 200 m miss, so on a linear axis every
  // encounter is the same giant V with its only interesting feature crushed into
  // one pixel at the vertex. Worse, a burn that moves the miss from 200 m to 2 km
  // is a tenfold improvement that a linear axis renders as no visible change at
  // all, which would have made the whole point of the tool invisible.
  const smallest = Math.min(...allValues);
  const largest = Math.max(...allValues);
  const lo = Math.max(smallest * 0.45, 0.005);
  const hi = largest * 1.35;
  const logLo = Math.log10(lo);
  const logHi = Math.log10(hi);

  lastCurveMapping = { left, right, minX, maxX };

  const x = (offset: number) => left + ((offset - minX) / (maxX - minX)) * (width - left - right);
  const y = (value: number) => {
    const clamped = Math.max(value, lo);
    return (
      height -
      bottom -
      ((Math.log10(clamped) - logLo) / (logHi - logLo)) * (height - top - bottom)
    );
  };

  context.lineWidth = 1;
  context.font = '10px "JetBrains Mono", ui-monospace, monospace';
  context.textAlign = "right";
  for (let exponent = Math.ceil(logLo); exponent <= Math.floor(logHi); exponent += 1) {
    const value = 10 ** exponent;
    const py = y(value);
    context.strokeStyle = c.rule;
    context.beginPath();
    context.moveTo(left, py + 0.5);
    context.lineTo(width - right, py + 0.5);
    context.stroke();
    context.fillStyle = c.dim;
    context.fillText(axisKm(value), left - 8, py + 3);
  }

  context.textAlign = "center";
  for (let i = 0; i <= 4; i += 1) {
    const offset = minX + ((maxX - minX) * i) / 4;
    const centre = (minX + maxX) / 2;
    context.fillText(duration(offset - centre), x(offset), height - 8);
  }

  state.series.forEach((series, seriesIndex) => {
    context.strokeStyle = series.colour;
    context.lineWidth = 1.8;
    // The counterfactual is dashed. Away from closest approach the two trajectories
    // are identical, so a solid post-burn line simply painted over the pre-burn one
    // and the comparison looked like a single curve. Dashes let both read where they
    // coincide, and they carry the distinction without relying on hue.
    context.setLineDash(series.dashed ? [5, 4] : []);
    context.beginPath();
    let drawing = false;
    for (let i = 0; i < series.offsetsS.length; i += 1) {
      const value = series.separationKm[i];
      if (value === null || !Number.isFinite(value)) {
        drawing = false;
        continue;
      }
      const px = x(series.offsetsS[i]);
      const py = y(value);
      if (!drawing) {
        context.moveTo(px, py);
        drawing = true;
      } else {
        context.lineTo(px, py);
      }
    }
    context.stroke();
    context.setLineDash([]);

    // Mark the minimum. It is the number the whole page is about.
    let bestIndex = -1;
    let best = Infinity;
    for (let i = 0; i < series.separationKm.length; i += 1) {
      const value = series.separationKm[i];
      if (value !== null && value < best) {
        best = value;
        bestIndex = i;
      }
    }
    if (bestIndex >= 0) {
      const px = x(series.offsetsS[bestIndex]);
      const py = y(best);
      context.fillStyle = series.colour;
      context.beginPath();
      context.arc(px, py, 3.2, 0, Math.PI * 2);
      context.fill();
      context.font = '11px "JetBrains Mono", ui-monospace, monospace';
      context.textAlign = px > width - 110 ? "right" : "left";
      // Stack the labels rather than letting them land on each other. Two minima a
      // few hundred metres apart printed at the same height and read as one
      // unintelligible string, which is exactly the comparison this chart is for.
      const labelY = py - 8 - seriesIndex * 13;
      context.fillText(km(best), px + (px > width - 110 ? -8 : 8), labelY);
    }
  });

  if (state.playheadS !== null && state.playheadS >= minX && state.playheadS <= maxX) {
    context.strokeStyle = c.selected;
    context.globalAlpha = 0.55;
    context.beginPath();
    context.moveTo(x(state.playheadS) + 0.5, top);
    context.lineTo(x(state.playheadS) + 0.5, height - bottom);
    context.stroke();
    context.globalAlpha = 1;
  }

  const legend = state.series.filter((s) => s.label);
  context.font = '10px "JetBrains Mono", ui-monospace, monospace';
  context.textAlign = "left";
  let legendX = left + 4;
  for (const series of legend) {
    context.fillStyle = series.colour;
    context.fillRect(legendX, top - 4, 8, 2);
    context.fillStyle = c.dim;
    context.fillText(series.label, legendX + 12, top);
    legendX += context.measureText(series.label).width + 30;
  }
}

export function curveColours() {
  const c = ink();
  return { before: c.partner, after: c.afterBurn };
}
