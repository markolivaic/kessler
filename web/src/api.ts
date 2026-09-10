/** Typed client for the kessler service. One origin, proxied in dev by vite. */

export interface Coverage {
  on_orbit_catalogued: number;
  screened: number;
  screened_percent: number;
  debris_on_orbit: number;
  debris_screened: number;
  debris_percent: number;
  by_object_type: Record<string, { on_orbit: number; screened: number; percent: number }>;
}

export interface Provenance {
  snapshot_date: string;
  objects: number;
  coverage: Coverage;
  source: string;
  propagator: string;
  model_output: boolean;
  trained_model: boolean;
  covariance: string;
  not_a_warning_service: string;
}

export interface CatalogueResponse {
  snapshot_date: string;
  count: number;
  norad: number[];
  name: string[];
  type: string[];
  group: string[];
  perigee_km: number[];
  apogee_km: number[];
}

export interface Passage {
  norad_a: number;
  name_a: string;
  type_a: string;
  group_a: string;
  norad_b: number;
  name_b: string;
  type_b: string;
  group_b: string;
  tca_utc: string;
  miss_km: number;
  rel_speed_kms: number;
  altitude_km: number;
  steps_in_run: string;
  classification: string;
}

export interface ObjectDetail {
  norad: number;
  name: string;
  object_id: string;
  object_type: string;
  owner: string;
  group: string;
  epoch: string;
  rcs_m2: number | null;
  passages: Passage[];
  passages_total: number;
  artefacts: Passage[];
  screened_to_km: number;
  note: string;
}

export interface Curve {
  offsets_s: number[];
  separation_km: (number | null)[];
  min_km: number | null;
  tca_offset_s: number | null;
}

export interface ProbabilityBlock {
  probability: number;
  one_in: number | null;
  miss_km: number;
  combined_radius_m: number;
  position_sigma_km: number;
  assumption: string;
}

export interface ManoeuvreResult {
  burn: {
    at_offset_s: number;
    radial_ms: number;
    in_track_ms: number;
    cross_track_ms: number;
    magnitude_ms: number;
    lead_time_s: number;
  };
  before: { min_km: number; tca_offset_s: number; offsets_s: number[]; separation_km: number[] };
  after: { min_km: number; tca_offset_s: number; offsets_s: number[]; separation_km: number[] };
  change_km: number;
  inversion: { residual_m: number; iterations: number; converged: boolean; note: string };
  probability?: {
    before: ProbabilityBlock;
    after: ProbabilityBlock;
    sweep_before: ProbabilityBlock[];
    warning: string;
  };
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return (await response.json()) as T;
}

export const api = {
  provenance: () => get<Provenance>("/api/provenance"),
  catalogue: () => get<CatalogueResponse>("/api/catalogue"),

  async tle(): Promise<string> {
    const response = await fetch("/api/catalogue.tle");
    if (!response.ok) throw new Error(`catalogue.tle returned ${response.status}`);
    return response.text();
  },

  object: (norad: number) => get<ObjectDetail>(`/api/object/${norad}`),

  encounter: (a: number, b: number, tcaOffsetS: number, spanS = 600) =>
    get<Curve>(`/api/encounter?a=${a}&b=${b}&tca_offset_s=${tcaOffsetS}&span_s=${spanS}`),

  async manoeuvre(body: {
    norad: number;
    partner_norad: number;
    tca_offset_s: number;
    burn_offset_s: number;
    radial_ms?: number;
    in_track_ms?: number;
    cross_track_ms?: number;
    position_sigma_km?: number | null;
  }): Promise<ManoeuvreResult> {
    const response = await fetch("/api/manoeuvre", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(detail.detail ?? `manoeuvre returned ${response.status}`);
    }
    return (await response.json()) as ManoeuvreResult;
  },
};
