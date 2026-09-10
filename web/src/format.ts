/**
 * Number and time formatting for a readout where columns are compared vertically.
 *
 * Everything here returns fixed-width strings. A table of miss distances is only
 * scannable if the decimal points line up, and they only line up if the digit count
 * does not change with the value.
 */

/** Kilometres, with the precision that actually means something at that scale. */
export function km(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  if (value < 1) return `${(value * 1000).toFixed(0)} m`;
  if (value < 10) return `${value.toFixed(3)} km`;
  if (value < 100) return `${value.toFixed(2)} km`;
  return `${value.toFixed(1)} km`;
}

/** Relative speed. Below 100 m/s a pair is co-orbiting, so metres matter there. */
export function speed(kms: number | null | undefined): string {
  if (kms === null || kms === undefined || !Number.isFinite(kms)) return "-";
  if (kms < 1) return `${(kms * 1000).toFixed(1)} m/s`;
  return `${kms.toFixed(3)} km/s`;
}

/**
 * An axis tick label. Always kilometres, unlike `km` above.
 *
 * `km` switches to metres below a kilometre, which is right for a single callout and
 * wrong for an axis: the first version of the separation chart ran 4130.6 km, 3098.0
 * km, 2065.3 km, 1032.7 km, 0 m, changing unit on the last tick.
 */
export function axisKm(value: number): string {
  if (value >= 100) return `${Math.round(value)} km`;
  if (value >= 1) return `${value < 10 ? value.toFixed(0) : Math.round(value)} km`;
  if (value >= 0.1) return `${value.toFixed(1)} km`;
  if (value >= 0.01) return `${value.toFixed(2)} km`;
  return `${value.toFixed(3)} km`;
}

/** Seconds as a duration a person reads, not as a number. */
export function duration(seconds: number): string {
  const sign = seconds < 0 ? "-" : "";
  const total = Math.abs(Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${sign}${h}h ${String(m).padStart(2, "0")}m`;
  if (m > 0) return `${sign}${m}m ${String(s).padStart(2, "0")}s`;
  return `${sign}${s}s`;
}

/** UTC clock, always the same width. */
export function clock(date: Date): string {
  return (
    `${String(date.getUTCHours()).padStart(2, "0")}:` +
    `${String(date.getUTCMinutes()).padStart(2, "0")}:` +
    `${String(date.getUTCSeconds()).padStart(2, "0")}`
  );
}

export function isoDay(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** A probability, in the form people can actually compare. */
export function probability(p: number | null | undefined): string {
  if (p === null || p === undefined || !Number.isFinite(p)) return "-";
  if (p === 0) return "0";
  if (p >= 0.01) return p.toFixed(4);
  const exponent = Math.floor(Math.log10(p));
  const mantissa = p / 10 ** exponent;
  return `${mantissa.toFixed(2)}e${exponent}`;
}

/** Pad a keyword so a record block stays a record block. */
export function field(name: string, width = 22): string {
  return name.toUpperCase().padEnd(width, " ");
}
